# Offline win-probability model

`micro19/model.txt` and `model_meta.json` are copied from the workspace's
`other/dotaprediction/micro19` bundle at the operator's request. The app reads
these bundled files only; no sibling project or online service is needed at runtime.

Inputs follow that project's README: ten stable player-slot net-worth values
(Radiant 0–4, Dire 5–9), both team totals, Radiant-minus-Dire NW, cumulative tower
and barracks losses, and loss differences positive for Radiant advantage. Unknown
inputs prevent scoring rather than being imputed as zero.

The supplied booster's building-labelled training ranges conflict with those
documented semantics. The operator explicitly selected the README contract for
this integration. Results are model estimates; their calibration and predictive
quality on freshly extracted features have not been established. No model was
retrained or relabelled. Shape categories are computed independently from NW/XP.

Inference uses LightGBM with the supplied best iteration and no added calibration.
The loader normalizes model text line endings in memory. Canonical model and
metadata hashes identify cached results; updating an artifact causes explicit
parsing actions to rescore retained graph features.
