"""Bounded, offline graph feasibility study; never opens the personal database.

Run from source. Build the development helper into .validation/graph-probe.exe
first; see docs/graph-feasibility.md. Raw diagnostics stay under .validation.
Matplotlib is a development-only dependency for standalone graph previews.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from library import Store  # noqa: E402


def select_samples(catalog):
    """At most six unique physical inputs, spanning both configured eras."""
    chosen, seen = [], set()

    def add(match, copy, reason):
        if copy["path"] in seen or len(chosen) == 6:
            return
        seen.add(copy["path"])
        chosen.append({"label": f"sample-{len(chosen) + 1}", "reason": reason,
                       "path": copy["path"], "client": copy["client"],
                       "size": copy["size"], "format": match.get("format"),
                       "summary_end_time": match.get("end_time"),
                       "summary_winner": match.get("winner")})

    for era in ("classic", "modern"):
        candidates = [(m, c) for m in catalog for c in m["copies"]
                      if c["client"] == era and m.get("end_time") and m.get("players")]
        candidates.sort(key=lambda pair: (pair[0]["end_time"], pair[1]["path"]))
        if candidates:
            add(*candidates[0], f"oldest dated {era} summary")
            add(*candidates[-1], f"newest dated {era} summary")
            if era == "modern":
                add(*candidates[len(candidates) // 2], "middle dated modern summary")
    incomplete = [(m, c) for m in catalog if not m.get("players")
                  for c in m["copies"] if m.get("errors") and c["size"] > 1024 * 1024]
    # Prefer a missing footer to other summary errors; no synthetic truncation
    # or copying of real replay inputs is necessary.
    incomplete.sort(key=lambda pair: (
        not any("footer" in str(e).lower() for e in pair[0].get("errors", [])),
        pair[1]["size"], pair[1]["path"]))
    if incomplete:
        add(*incomplete[0], "missing/invalid summary; inspect partial coverage")
    return chosen


def summarize(data):
    samples = data.get("samples") or []
    events = data.get("events") or []
    result = {key: data.get(key) for key in (
        "engine_build", "complete", "error", "elapsed_seconds", "game_start", "game_end", "final_score")}
    result["samples"] = len(samples)
    result["event_counts"] = dict(Counter(e["kind"] for e in events))
    result["untimed_events"] = sum(e.get("time") is None for e in events)
    result["coverage"] = {}
    for field in ("net_worth", "xp"):
        values = [s for s in samples if s.get(f"radiant_{field}") is not None
                  and s.get(f"dire_{field}") is not None]
        result["coverage"][field] = {
            "valid_samples": len(values), "first_second": values[0]["time"] if values else None,
            "last_second": values[-1]["time"] if values else None}
    result["largest_sample_gap_seconds"] = max(
        (b["time"] - a["time"] for a, b in zip(samples, samples[1:])), default=None)
    first_death = min((e["time"] for e in events if e["kind"] == "hero_death"
                       and e.get("time") is not None), default=None)
    first_score = next((s["observed_time"] for s in samples
                        if s.get("radiant_score") is not None and s.get("dire_score") is not None
                        and s["radiant_score"] + s["dire_score"] > 0), None)
    final = data.get("final_score") or {}
    result["score_crosscheck"] = {
        "hero_deaths": sum(e["kind"] == "hero_death" for e in events),
        "recorded_team_kills": (final["radiant"] + final["dire"])
        if final.get("radiant") is not None and final.get("dire") is not None else None,
        "first_death_second": first_death, "first_nonzero_score_second": first_score,
        "first_score_delay_seconds": first_score - first_death
        if first_death is not None and first_score is not None else None,
        "note": "Deaths can exceed team hero kills (e.g. neutral deaths or denies); do not replace scores with death counts."}
    # Also check a post-horn transition: a pre-horn kill can already be present
    # in the score at the first sample, so the first-nonzero delay is not enough.
    first_change = next((b["observed_time"] for a, b in zip(samples, samples[1:])
                         if all(s.get(k) is not None for s in (a, b)
                                for k in ("radiant_score", "dire_score"))
                         and b["radiant_score"] + b["dire_score"] > a["radiant_score"] + a["dire_score"]), None)
    death_times = [e["time"] for e in events if e["kind"] == "hero_death" and e.get("time") is not None]
    nearest = min(death_times, key=lambda t: abs(t - first_change)) if death_times and first_change is not None else None
    result["score_crosscheck"]["first_observed_score_increase"] = first_change
    result["score_crosscheck"]["nearest_death_delay_seconds"] = first_change - nearest if nearest is not None else None
    # Exploratory features only: no category is assigned by this study.
    leads = [(s["time"], s["net_worth_difference"] /
              (s["radiant_net_worth"] + s["dire_net_worth"]))
             for s in samples if s.get("net_worth_difference") is not None
             and s.get("radiant_net_worth") is not None and s.get("dire_net_worth") is not None
             and s["radiant_net_worth"] + s["dire_net_worth"] > 0 and s["time"] >= 600]
    winner = data.get("winner")
    result["shape_features"] = {
        "normalization": "(Radiant NW - Dire NW) / (Radiant NW + Dire NW), from minute 10",
        "fraction_within_5_percent": sum(abs(v) <= .05 for _, v in leads) / len(leads) if leads else None,
        "winner_largest_deficit_fraction": max(
            (max(0, -v if winner == 2 else v) for _, v in leads), default=None
        ) if winner in (2, 3) else None}
    result["diagnostics"] = data.get("diagnostics", {})
    return result


def plot(data, target):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    samples = data.get("samples") or []
    fig, axes = plt.subplots(5, 1, figsize=(13, 13), sharex=True,
                             gridspec_kw={"height_ratios": [3, 3, 2, 2, 1.4]})

    def series(field):
        times, values = [], []
        previous = None
        for sample in samples:
            if previous is not None and sample["time"] - previous > 1:
                times.append((previous + .5) / 60)
                values.append(None)
            times.append(sample["time"] / 60)
            values.append(sample.get(field))
            previous = sample["time"]
        return times, values

    for ax, field, title in zip(axes[:2], ("net_worth", "xp"), ("Team net worth", "Cumulative team XP")):
        for team, color in (("radiant", "#28854b"), ("dire", "#c34444")):
            ax.plot(*series(f"{team}_{field}"),
                    label=team.title(), color=color, linewidth=1)
        ax.set_ylabel(title)
        ax.grid(alpha=.2)
        ax.legend(loc="upper left")
        if not any(s.get(f"radiant_{field}") is not None or s.get(f"dire_{field}") is not None for s in samples):
            ax.text(.5, .5, "Unavailable in this recording / probe", transform=ax.transAxes, ha="center")
    for ax, field, title in zip(axes[2:4], ("net_worth_difference", "xp_difference"),
                               ("NW advantage (R − D)", "XP advantage (R − D)")):
        ax.plot(*series(field), color="#3b617e", linewidth=1)
        ax.axhline(0, color="#888888", linewidth=.6)
        ax.set_ylabel(title)
        ax.grid(alpha=.2)
        if not any(s.get(field) is not None for s in samples):
            ax.text(.5, .5, "Unavailable in this recording / probe", transform=ax.transAxes, ha="center")
    colors = {"hero_death": "#666666", "tower": "#377eb8", "barracks": "#984ea3", "roshan": "#e18723"}
    for level, (kind, color) in enumerate(colors.items()):
        times = [e["time"] / 60 for e in data.get("events", [])
                 if e["kind"] == kind and e.get("time") is not None]
        axes[4].scatter(times, [level] * len(times), color=color, s=16, marker="|")
    axes[4].set_yticks(range(4), ["Hero death", "Tower", "Barracks", "Roshan"])
    axes[4].set_ylim(-.6, 3.6)
    axes[4].set_xlabel("Game clock (minutes; horn = 0)")
    fig.suptitle(f"{target.stem} · build {data.get('engine_build', '?')} · "
                 f"{'complete recording' if data.get('complete') else 'partial / unsupported'}\n"
                 "Observed values only; missing data remains gaps. Win probability not inferred.")
    fig.tight_layout()
    fig.savefig(target.with_suffix(".png"), dpi=150)
    fig.savefig(target.with_suffix(".svg"))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".validation/graph-study")
    parser.add_argument("--helper", type=Path, default=ROOT / ".validation/graph-probe.exe")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / ".validation").resolve()):
        parser.error("Raw study output must stay inside this repository's ignored .validation directory")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="replay-graph-study-") as directory:
        store = Store(Path(directory) / "inventory.sqlite3")
        scan = store.scan()
        catalog = store.catalog()
    selected = select_samples(catalog)
    inventory = {"created_utc": datetime.now(timezone.utc).isoformat(),
                 "files": scan["files"], "unique_matches": len(catalog),
                 "summary_errors": len(scan["errors"]),
                 "formats": dict(Counter(m.get("format", "unknown") for m in catalog)),
                 "selected": selected}
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(f"Inventoried {scan['files']} files; selected {len(selected)} inputs", flush=True)
    if args.inventory_only:
        return
    reports = []
    for sample in selected:
        print(f"Parsing {sample['label']}: {sample['reason']}", flush=True)
        try:
            process = subprocess.run([str(args.helper.resolve()), "--graph-probe", sample["path"]],
                                     capture_output=True, text=True, encoding="utf-8", timeout=600,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads(process.stdout)
            if not isinstance(data, dict) or data.get("probe_version") != 1:
                raise ValueError("Unexpected graph probe protocol")
            data["helper_exit_code"] = process.returncode
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            data = {"probe_version": 1, "complete": False, "error": str(exc), "samples": [], "events": []}
        (output / f"{sample['label']}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        report = {"label": sample["label"], "reason": sample["reason"],
                  "client": sample["client"], "input_bytes": sample["size"], **summarize(data)}
        report["output_bytes"] = (output / f"{sample['label']}.json").stat().st_size
        reports.append(report)
        (output / "results.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        if not args.no_plots:
            plot(data, output / sample["label"])
        print(json.dumps({k: report[k] for k in ("label", "engine_build", "complete", "elapsed_seconds", "samples", "event_counts", "error")}), flush=True)


if __name__ == "__main__":
    main()
