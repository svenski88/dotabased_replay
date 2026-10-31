"""Offline graph contracts, feature extraction, inference and shape categories.

Gold/XP categories never depend on the model or its output. Heavy inference
dependencies are loaded only in the parse worker, never while browsing a catalog.
"""
from collections import deque
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import sys

GRAPH_SCHEMA = 1
CLASSIFIER_VERSION = "shape-1"
CATEGORIES = ("Comeback", "Stomp", "Close Game", "Other", "Insufficient data", "Not parsed")
FEATURES = [*(f"nw_s{i}" for i in range(10)), "nw_r", "nw_d", "nw_diff",
            "towers_dead_R", "towers_dead_D", "towers_diff", "rax_dead_R", "rax_dead_D", "rax_diff"]
RULES = {"start": 300, "coverage": .95, "smoothing": 30, "comeback": .10,
         "comeback_seconds": 120, "stomp": .075, "stomp_seconds": 120,
         "stomp_deadline": 600, "dominance": .05, "dominance_fraction": .90,
         "dip_seconds": 60, "neutral": .025, "neutral_seconds": 30,
         "close_band": .05, "close_fraction": .60, "close_minimum": 120}


class GraphCancelled(RuntimeError):
    pass


def finite(value, nonnegative=False):
    return type(value) in (int, float) and math.isfinite(value) and (not nonnegative or value >= 0)


def validate_sample(entry):
    if not isinstance(entry, dict) or type(entry.get("time")) is not int or entry["time"] < 0:
        raise ValueError("Invalid graph sample time")
    tick = entry.get("replay_tick")
    if tick is not None and (type(tick) is not int or not 0 <= tick <= 0xffffffff):
        raise ValueError("Invalid graph replay tick")
    for key in ("radiant_net_worth", "dire_net_worth", "radiant_xp", "dire_xp", "radiant_score", "dire_score"):
        if entry.get(key) is not None and not finite(entry[key], True):
            raise ValueError(f"Invalid graph {key}")
    for name, r, d in (("net_worth_difference", "radiant_net_worth", "dire_net_worth"),
                       ("xp_difference", "radiant_xp", "dire_xp")):
        value = entry.get(name)
        if value is not None and not finite(value):
            raise ValueError(f"Invalid graph {name}")
        if entry.get(r) is not None and entry.get(d) is not None:
            if value is None or not math.isclose(value, entry[r] - entry[d], abs_tol=.001):
                raise ValueError(f"Inconsistent graph {name}")
    players = entry.get("player_net_worth")
    if players is not None and (not isinstance(players, list) or len(players) != 10 or
                               any(v is not None and not finite(v, True) for v in players)):
        raise ValueError("Invalid graph player net worth")
    for name, maximum in (("towers_dead_R", 11), ("towers_dead_D", 11), ("rax_dead_R", 6), ("rax_dead_D", 6)):
        value = entry.get(name)
        if value is not None and (not finite(value, True) or value != int(value) or value > maximum):
            raise ValueError(f"Invalid graph {name}")
    return entry


def validate_event(entry):
    if not isinstance(entry, dict) or entry.get("kind") not in ("hero_death", "tower", "barracks", "roshan"):
        raise ValueError("Invalid graph event kind")
    if type(entry.get("tick")) is not int or entry["tick"] < 0:
        raise ValueError("Invalid graph event tick")
    if entry.get("time") is not None and not finite(entry["time"]):
        raise ValueError("Invalid graph event time")
    for name in ("attacker", "target", "source"):
        if not isinstance(entry.get(name), str) or len(entry[name]) > 1024:
            raise ValueError(f"Invalid graph event {name}")
    for name in ("attacker_team", "target_team"):
        if entry.get(name) is not None and not finite(entry[name], True):
            raise ValueError(f"Invalid graph event {name}")
    return entry


def feature_row(sample):
    """Strict README contract; no zero imputation or wealth-based slot sorting."""
    players = sample.get("player_net_worth")
    if not isinstance(players, list) or len(players) != 10 or not all(finite(v, True) for v in players):
        return None
    required = ("radiant_net_worth", "dire_net_worth", "net_worth_difference",
                "towers_dead_R", "towers_dead_D", "rax_dead_R", "rax_dead_D")
    if not all(finite(sample.get(k)) for k in required):
        return None
    r, d = sample["radiant_net_worth"], sample["dire_net_worth"]
    if not math.isclose(sum(players[:5]), r, abs_tol=1) or not math.isclose(sum(players[5:]), d, abs_tol=1):
        return None
    if not math.isclose(sample["net_worth_difference"], r - d, abs_tol=.001):
        return None
    tr, td, rr, rd = (sample[k] for k in required[3:])
    if any(v < 0 or v != int(v) or v > limit for v, limit in ((tr, 11), (td, 11), (rr, 6), (rd, 6))):
        return None
    return [*players, r, d, r-d, tr, td, td-tr, rr, rd, rd-rr]


def model_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "models/micro19"


@lru_cache(maxsize=1)
def model_identity():
    try:
        directory = model_root()
        canonical = (directory / "model.txt").read_text(encoding="utf-8")
        meta = json.loads((directory / "model_meta.json").read_text(encoding="utf-8"))
        return "micro19:" + hashlib.sha256((canonical + json.dumps(meta, sort_keys=True)).encode()).hexdigest()
    except (OSError, ValueError):
        return "micro19:unavailable"


class Micro19:
    def __init__(self):
        import lightgbm as lgb
        self.directory = model_root()
        self.meta = json.loads((self.directory / "model_meta.json").read_text(encoding="utf-8"))
        self.booster = lgb.Booster(model_str=(self.directory / "model.txt").read_text(encoding="utf-8"))
        if self.meta.get("feature_names") != FEATURES or self.booster.feature_name() != FEATURES:
            raise ValueError("micro19 feature order does not match the bundled contract")

    def predict(self, rows):
        import numpy as np
        values = self.booster.predict(np.asarray(rows, dtype=np.float64),
                                      num_iteration=self.meta.get("best_iteration"), num_threads=1)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError("Model returned invalid probabilities")
        return values.tolist()


@lru_cache(maxsize=1)
def predictor():
    return Micro19()


def longest_run(values, predicate):
    longest = current = 0
    for value in values:
        current = current + 1 if value is not None and predicate(value) else 0
        longest = max(longest, current)
    return longest


def smooth_signal(samples, resource, end):
    observed = {}
    for sample in samples:
        r, d = sample.get(f"radiant_{resource}"), sample.get(f"dire_{resource}")
        if finite(r, True) and finite(d, True) and r+d > 0:
            observed[sample["time"]] = (r-d) / (r+d)
    smoothed, window = {}, deque()
    for second in range(end):
        value = observed.get(second)
        if value is None:
            window.clear()  # a gap cannot bridge sustained qualification
            continue
        window.append(value)
        if len(window) > RULES["smoothing"]:
            window.popleft()
        smoothed[second] = median(window)
    return observed, smoothed


def classify(graph):
    result = {"label": "Insufficient data", "basis": None, "version": CLASSIFIER_VERSION,
              "explanation": "A verified outcome and sufficient gold or XP coverage are required.", "details": {}}
    duration, winner = graph.get("duration"), graph.get("winner")
    if not graph.get("complete") or not finite(duration, True) or winner not in (2, 3):
        return result
    end = math.ceil(duration)
    if end - RULES["start"] < 120:
        result["explanation"] = "Too little observed play after minute five for sustained shape rules."
        return result
    source, smoothed = None, {}
    for resource in ("net_worth", "xp"):
        observed, values = smooth_signal(graph.get("samples", []), resource, end)
        fraction = sum(t in observed for t in range(RULES["start"], end)) / (end - RULES["start"])
        if fraction >= RULES["coverage"]:
            source, smoothed = resource, values
            result["details"]["coverage"] = fraction
            break
    if source is None:
        result["explanation"] = "Neither net worth nor XP covers 95% of play after minute five."
        return result
    result["basis"] = "Gold" if source == "net_worth" else "XP fallback"
    sign = 1 if winner == 2 else -1
    values = [smoothed.get(t) * sign if t in smoothed else None for t in range(RULES["start"], end)]
    deficit = longest_run(values, lambda v: v <= -RULES["comeback"] + 1e-12)
    result["details"]["sustained_deficit_seconds"] = deficit
    result["details"]["winner_max_deficit"] = max(0, max((-v for v in values if v is not None), default=0))
    recorded_deficits = []
    for sample in graph.get("samples", []):
        if not RULES["start"] <= sample["time"] < end:
            continue
        r, d = sample.get(f"radiant_{source}"), sample.get(f"dire_{source}")
        if finite(r, True) and finite(d, True):
            recorded_deficits.append((max(0, -sign*(r-d)), sample["time"]))
    if recorded_deficits:
        peak, second = max(recorded_deficits, key=lambda pair: pair[0])
        result["details"].update(resource_deficit_max=peak, resource_deficit_second=second)
    current = 0
    for index, value in enumerate(values):
        current = current + 1 if value is not None and value <= -RULES["comeback"] + 1e-12 else 0
        if current == deficit and current:
            result["details"].update(deficit_start=RULES["start"]+index+1-current,
                                     deficit_end=RULES["start"]+index+1)
            break
    if result["details"]["winner_max_deficit"] > 0:
        result["details"]["maximum_deficit_second"] = min(
            ((value, second+RULES["start"]) for second, value in enumerate(values) if value is not None))[1]
    if deficit >= RULES["comeback_seconds"]:
        result.update(label="Comeback", explanation=f"{result['basis']}: winner trailed by at least 10% of combined resources for {deficit}s after minute five, then won.")
        return result
    run, established = 0, None
    for offset, value in enumerate(values):
        second = offset + RULES["start"]
        run = run + 1 if value is not None and value >= RULES["stomp"] - 1e-12 else 0
        if run >= RULES["stomp_seconds"] and second + 1 <= RULES["stomp_deadline"]:
            established = offset + 1 - run
            break
    if established is not None:
        tail = values[established:]
        dominance = sum(v is not None and v >= RULES["dominance"] - 1e-12 for v in tail) / len(tail)
        # Missing samples break sustained qualification and cannot count as dominance.
        dips = longest_run(tail, lambda v: v < RULES["dominance"] - 1e-12)
        neutral = longest_run(tail, lambda v: abs(v) <= RULES["neutral"] + 1e-12)
        reversal = longest_run(tail, lambda v: v < -RULES["neutral"] - 1e-12)
        result["details"].update(lead_start=established + RULES["start"], dominance_fraction=dominance,
                                 longest_dip=dips, longest_neutral=neutral, longest_reversal=reversal)
        if dominance >= RULES["dominance_fraction"] and dips <= RULES["dip_seconds"] and neutral <= RULES["neutral_seconds"] and reversal < RULES["neutral_seconds"]:
            result.update(label="Stomp", explanation=f"{result['basis']}: 7.5% lead sustained for two minutes by minute 10; dominant for {dominance:.0%} afterward without a sustained recovery.")
            return result
    close_start, close_end = max(0, math.ceil(duration - 300)), max(0, math.ceil(duration - 60))
    ending = [smoothed.get(t) for t in range(close_start, close_end)]
    valid = sum(v is not None for v in ending)
    if valid < RULES["close_minimum"] or not ending or valid / len(ending) < RULES["coverage"]:
        result["explanation"] = "The ending window has insufficient coverage to distinguish Close Game from Other."
        return result
    close = sum(v is not None and abs(v) <= RULES["close_band"] + 1e-12 for v in ending) / len(ending)
    result["details"].update(ending_start=close_start, ending_end=close_end, ending_neutral_fraction=close)
    if close >= RULES["close_fraction"]:
        result.update(label="Close Game", explanation=f"{result['basis']}: {close:.0%} of the ending window stayed within ±5%, excluding the final minute. Earlier swings are allowed.")
    else:
        result.update(label="Other", explanation=f"{result['basis']}: adequate data, but no sustained comeback, early stomp or near-neutral ending.")
    return result


def derive_graph(graph, cancelled=lambda: False, model=None):
    """Mutate derived fields only; model failures do not discard extracted graphs."""
    if cancelled():
        raise GraphCancelled("Parsing stopped")
    graph["category"] = classify(graph)
    graph["classifier_version"] = CLASSIFIER_VERSION
    graph["model_version"] = model_identity()
    valid = []
    for sample in graph.get("samples", []):
        sample.pop("radiant_win_probability", None)
        row = feature_row(sample)
        if row is not None:
            valid.append((sample, row))
    prediction = {"model": "micro19", "status": "unavailable", "scored_samples": 0,
                  "explanation": "Required player net worth or building state is unavailable."}
    graph["prediction"] = prediction
    if not valid:
        return graph
    try:
        scorer = model or predictor()
        for start in range(0, len(valid), 600):
            if cancelled():
                raise GraphCancelled("Parsing stopped")
            block = valid[start:start+600]
            values = scorer.predict([row for _, row in block])
            if len(values) != len(block) or not all(finite(v) and 0 <= v <= 1 for v in values):
                raise ValueError("Invalid prediction batch")
            for (sample, _), probability in zip(block, values):
                sample["radiant_win_probability"] = float(probability)
            prediction["scored_samples"] += len(block)
        if cancelled():
            raise GraphCancelled("Parsing stopped")
        prediction.update(status="complete" if len(valid) == len(graph["samples"]) else "partial",
                          explanation="Estimated Radiant win probability from the bundled micro19 model.")
    except GraphCancelled:
        raise
    except Exception as exc:
        for sample in graph.get("samples", []):
            sample.pop("radiant_win_probability", None)
        prediction.update(status="error", scored_samples=0, explanation=f"Win estimate unavailable: {exc}")
    return graph


def graph_summary(graph):
    return {"schema_version": graph.get("schema_version"), "complete": graph.get("complete", False),
            "sample_count": len(graph.get("samples", [])), "event_count": len(graph.get("events", [])),
            "category": graph.get("category", {"label": "Insufficient data", "explanation": "Graph has not been categorized."}),
            "prediction": graph.get("prediction", {}), "model_version": graph.get("model_version"),
            "classifier_version": graph.get("classifier_version")}


def needs_derivation(summary):
    return summary.get("classifier_version") != CLASSIFIER_VERSION or summary.get("model_version") != model_identity() or summary.get("prediction", {}).get("status") == "error"
