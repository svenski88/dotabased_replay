# Replay graph feasibility study

Historical study preceding the production graph integration. See the repository
README for the implemented classifier, XP fallback, UI and current parser behavior;
the recommendations and development-only scope below describe this earlier stage.

Reviewed on 2026-10-30. **Offline graph extraction is feasible, with build-dependent
coverage.** Three sampled builds provide net worth and cumulative XP; two older
builds provide XP but lack the inspected direct net-worth fields. All five complete
samples provide hero deaths and objective events. Valve's exact win probability
has not been recovered from replay data.

This stage adds a development probe and study runner, not application graphs,
classification filters, a cache migration or a release. Normal helper output and
version remain unchanged unless `--graph-probe` is explicitly selected.

## Measured compatibility

A disposable database scanned the two default replay libraries: 1,048 physical
files, 1,046 catalog entries, 1,016 entries with usable Source 2 summaries and 30
summary-error entries. A library's modern/classic assignment is a playback
preference, not a guarantee about the recording's build. Selection used oldest
and newest dated summaries in each library, a middle dated modern summary, and
one recording missing its footer. No Source 1 sample was identified among usable
summaries; summary-error entries are not proof of another format.

| Sample | Recorded era / build | NW samples | XP samples | Hero deaths / towers / barracks / Roshan | Parse seconds | Raw JSON MiB |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| 1 | 2015 / 1048 | unavailable | 3,635 | 64 / 14 / 4 / 2 | 3.79 | 1.15 |
| 2 | 2018 / 3261 | 3,468 | 3,468 | 97 / 21 / 5 / 3 | 4.84 | 1.14 |
| 3 | 2015 / 1156 | unavailable | 3,722 | 95 / 6 / 0 / 3 | 3.71 | 1.19 |
| 4 | 2026 / 6969 | 3,152 | 3,152 | 92 / 15 / 4 / 2 | 5.96 | 1.07 |
| 5 | 2023 / 5608 | 2,282 | 2,282 | 74 / 13 / 6 / 2 | 3.58 | 0.78 |
| 6 | Missing footer / undetermined | unavailable | unavailable | unavailable | <0.01 | <0.01 |

These are warm development-machine timings, excluding inventory and plotting,
not a performance guarantee. Each successful timeline covers every observed
integer game second from zero through the last in-game second, with no gaps.
Five recordings reached authoritative post-game team-score snapshots. Sample 6
failed before stream decoding because Manta could not determine the build; it
returned structured unavailable data, not zero-valued graphs. This sample does
not validate how much a different truncated recording could recover.

The ignored `.validation/graph-study/` folder contains `inventory.json` (local
paths), `results.json`, six raw probe JSON files, and six PNG/SVG previews. The
sample-4 preview shows the strongest comeback candidate. No replay files,
account identities, player names or chat were copied into tracked study files.

## Extraction and checks

- Team totals sum five distinct playing team slots, identified through
  `CDOTA_PlayerResource.m_vecPlayerData.*.m_iPlayerTeam` and
  `m_vecPlayerTeamData.*.m_iTeamSlot`. Missing contributors remain unknown;
  coaches and duplicate slots cannot silently inflate totals.
- `CDOTA_DataRadiant` / `CDOTA_DataDire` expose
  `m_vecDataTeam.*.m_iNetWorth` in builds 3261, 5608 and 6969 and
  `m_iTotalEarnedXP` in all five successful samples. Builds 1048 and 1156 lack
  direct NW in the inspected data/player-resource entities. Gold earned is not
  substituted for net worth. Reconstructing older NW from inventories and item
  values would require a separate compatibility investigation.
- Older clocks use recorded `m_fGameTime - m_flGameStartTime`. Build 6969 uses
  `(server tick - total paused ticks) * recorded server tick_interval`, using
  the pause-start tick while paused, then subtracts game start. Sampling is once
  per observed game second; no wall clock, assumed tick rate or gap interpolation
  supplies missing data. Pre-horn events retain negative timestamps.
- Death records come from legacy `dota_combatlog` or modern
  `CMsgDOTACombatLogEntry`/bulk data. The probe filters illusions and ordinary
  creeps and suppresses duplicate retransmissions. It retains target/attacker
  unit identifiers, recorded team attribution where present, and summary
  hero/team mappings otherwise. Unresolved attribution remains unknown (including
  some old objective attackers); kill credit is not inferred from the winning
  team or target's opponent. Building unit names retain lane/tier/type detail.
- Final team kills are 39–24, 37–57, 19–73, 48–41 and 27–47 (Radiant–Dire).
  Corresponding death totals are 64, 97, 95, 92 and 74. Differences are retained:
  death events and credited team kills are distinct, and the probe does not
  diagnose every discrepancy. No unresolved target-name deaths were reported.
- The first observed post-horn score increase follows a nearby death by 0.30–1.00
  seconds in each successful sample. In build 6969 the first five increases agree
  within 0.30–0.93 seconds. Its pre-horn kills already appear at the zero-second
  sample, so comparing only the first death to the first nonzero score would be
  misleading. Final samples occur within one second before recorded game end.

Synthetic tests verify five-player arithmetic, recorded zeros, missing NW with
known XP, duplicate slots, pause handling, absent clock inputs, event filtering,
deduplication, structured failure, bounded sampling and winner-relative features.
The Python suite passed 74 tests; Go tests passed including five new probe tests.
A later full Python run hit the existing four-second parse-progress UI deadline,
alongside Tk image-finalizer warnings. The six parse-progress tests then passed
independently, as did all three new study tests. This timing-sensitive UI failure
was not changed as part of the study. PNG previews were inspected locally. Some
existing Tk tests also print stale `after` callback messages while passing.

These checks establish replay-internal consistency. They do **not** independently
verify exact values or all objective counts against the Dota client graph page.
Before UI integration, manually compare several timestamps, objective markers and
end totals in a compatible client. No client was launched during this study.

## Win probability

The pinned Manta protobufs define
`CDOTAMatchPrivateMetadata.graph_win_probability`; that is a separate private
match-metadata structure, not evidence that a replay carries this curve. No
win-probability candidate field was found in the inspected rules, player-resource,
team or team-data entities. The probe does not exhaustively inspect arbitrary
message payloads, and this finding does not prove the data is absent everywhere.

Treat the client-equivalent curve as **unavailable pending further evidence**.
Neither an API request nor a new prediction model is required for the proposed
NW/XP classification. Do not label a gold-based heuristic as win probability.

Primary implementation references: [Manta v1.5.2](https://github.com/dotabuff/manta/tree/v1.5.2),
[private metadata protobuf](https://github.com/dotabuff/manta/blob/v1.5.2/dota/dota_match_metadata.proto),
and [OpenDota parser](https://github.com/odota/parser/blob/master/src/main/java/opendota/Parse.java)
for independently established entity-field and pause-aware clock approaches.
Compatibility conclusions above come from the local samples, not those projects'
general support claims.

## Recommended classification and integration

Use one automatic category per match, with a stored explanation and classifier
version. Keep `Other` separate from `Insufficient data`. Recommend NW as the
primary signal, XP and objective markers as explanatory context. Do not silently
use XP alone for old recordings under the same NW classifier.

For a first reviewable classifier, use the winner-relative NW difference divided
by combined team NW, evaluated after minute 10. Proposed starting rules, in order:

1. **Insufficient data:** unknown winner, no verified end state, or less than 95%
   NW coverage of the post-minute-10 interval; games ending before minute 15 also
   remain insufficient for these duration-based rules.
2. **Comeback:** eventual winner trails by at least 10% of combined team NW for
   at least 120 consecutive observed game seconds.
3. **Stomp:** winner leads by at least 7.5% for at least 75% of the evaluation
   interval and never trails by more than 2.5% during it.
4. **Close Game:** absolute lead stays within 5% for at least 70% of that interval.
5. **Other:** adequate data without one of those shapes.

These thresholds are recommendations, not calibrated labels. Missing seconds
break sustained runs. A 10% combined-NW deficit corresponds to about a 22% lead
relative to the trailing team's NW, so the denominator must be clear in user
explanations. Preserve raw gold deficit and its timestamp alongside percentages.

Sample 2 spends 88.2% of its evaluation interval within the 5% band, supporting a
close-game candidate. Sample 4's eventual Dire winner overcomes a 16,666-gold
Radiant lead; its largest normalized deficit is 15.9%. The previews demonstrate
the intended comeback shape, but the sustained rule still needs classifier
implementation and review. The sample does not establish a calibrated stomp
example. Sample 5 spends 52.2% in the close band; avoid forcing it into a category.

Later integration should emit versioned timeline data through the existing
serialized/cancellable helper queue, cache it per physical file signature and
helper version, and store compact classification features separately from raw
diagnostics. Keep graph availability independent of existing metadata success:
an old replay can have valid XP and score with unavailable NW. Reuse successful
unchanged results, preserve annotations, and never classify an old cache row as
`Other` merely because its timeline has not been parsed. Bump the production
helper version only when integrating that protocol. Put graphs and event details
in the selected-match pane and expose one category column/filter in the inventory.

## Reproduce from the repository directory

The commands write only development artifacts and source test caches. Use an
installed Go 1.25+ instead of the portable executable if appropriate.

```powershell
$env:GOCACHE = "$PWD/.validation/go-cache"
$env:GOMODCACHE = "$PWD/.validation/go-mod-cache"
$env:CGO_ENABLED = '0'
& ./.validation/toolchain/go/bin/go.exe -C parser_helper test ./...
& ./.validation/toolchain/go/bin/go.exe -C parser_helper build -o ../.validation/graph-probe.exe .
python -m pip install --target .validation/plot-deps matplotlib==3.11.2
$env:PYTHONPATH = "$PWD/.validation/plot-deps"
python scripts/study_graphs.py --inventory-only
python scripts/study_graphs.py
python -m unittest discover -s tests -v
```

The runner scans default libraries into a temporary database and parses at most
six unique physical inputs serially, with a ten-minute timeout per input. It does
not read or migrate the personal database. `--no-plots` skips Matplotlib;
`--output` must remain inside ignored `.validation`. No packaged app or existing
`bin/replay-parser.exe` needs replacement. Source 1 support, older NW reconstruction,
client graph verification and production UI/classifier implementation remain
future work.
