# Exploratory ML Module

The ML module is **secondary, exploratory, and non-diagnostic**. It never
replaces the rule-based warning module and is suppressed when SQI is `poor` or
`unreliable`. Its output must always be described as an "exploratory ML
advisory", never as a diagnosis.

## Two data sources

### 1. Synthetic (default, reproducible without downloads)

```bash
python3 scripts/train_ml_warning_model.py --source synthetic
python3 scripts/evaluate_ml_warning_model.py --source synthetic
```

The synthetic tables give accuracy / macro-F1 / AUROC of 1.0, but this only
confirms that feature extraction, training, save/load, and prediction work. It
carries **no** clinical validity and no generalisation claim.

### 2. MIT-BIH patient-wise (DS1/DS2)

```bash
python3 scripts/train_ml_warning_model.py --source mitdb --split ds1ds2 \
    --output models/ml_warning_model.pkl
python3 scripts/evaluate_ml_warning_model.py --source mitdb --split ds1ds2 \
    --model models/ml_warning_model.pkl
```

Training uses **DS1** and testing uses **DS2** — the standard de Chazal
patient-wise split. DS1 and DS2 are disjoint patient sets, so no beat or patient
appears in both training and testing (a unit test enforces the disjointness).
This is the scientifically correct protocol: a random beat split would leak
patient-specific morphology and inflate the scores.

## Label schemes

* `--labels binary` (default): `normal_like` vs `warning_like`.
* `--labels aami`: the five AAMI classes `N / S / V / F / Q`.

AAMI symbol mapping (documented and unit-tested):

| Class | MIT-BIH symbols |
|---|---|
| N | `N L R e j` |
| S | `A a J S` |
| V | `V E` |
| F | `F` |
| Q | `/ f Q` |

In binary mode the N group maps to `normal_like`, the S/V/F groups map to
`warning_like`, and the Q group (paced / unclassifiable) is **skipped** because a
paced/unknown beat is not a rhythm warning. Non-beat annotations (`+ ~ | "`) are
always skipped and counted.

## Features

Beat-level, handcrafted features (`ecg_monitor/ml_features.py`): previous/next
RR, RR ratio to local median, instantaneous and local-median HR, RR CV, QRS
duration estimate, R amplitude, QRS energy, numeric SQI, and P/T visibility
flags. Features are computed over the full beat sequence so RR neighbours stay
physiological; beats whose symbol maps to no class are dropped afterwards.

## Model

Default `LogisticRegression(class_weight='balanced')` inside a `StandardScaler`
pipeline. `--model-type linsvc` and `--model-type rf` are available but not the
default. AUROC is reported for the binary task when class probabilities are
available (LinearSVC has none, so AUROC is skipped for it).

## Metrics saved

- `results/ml_mitdb_train_summary.json` — records used, class counts, skipped
  beats and reasons, instability flag.
- `results/ml_mitdb_results.json` / `.csv` — accuracy, macro/weighted
  precision/recall/F1, per-class report, AUROC (binary), test class counts,
  skipped beats.
- `results/ml_mitdb_confusion_matrix.csv` — confusion matrix.

(For the synthetic source the outputs are `results/ml_train_summary.json`,
`results/ml_results.json`, and `results/ml_results.csv`.)

## Scientific guard-rails

- No training and testing on beats from the same records in patient-wise mode.
- Synthetic ML results are never reported as real performance.
- ML output is an advisory only and never overrides the rule-based safety logic.
- When SQI is poor/unreliable, ML prediction returns `suppressed_low_sqi`.
- When class counts are small, the scripts flag the result as
  `unstable_small_classes` and print a warning.

## Reproducible offline run

MIT-BIH records can be pre-downloaded once and read locally (`--local-dir`),
which avoids re-streaming and makes the experiment reproducible:

```bash
python3 -c "import wfdb; wfdb.dl_database('mitdb','mitdb_local')"
python3 scripts/train_ml_warning_model.py --source mitdb --split ds1ds2 \
    --local-dir mitdb_local --output models/ml_warning_model.pkl
python3 scripts/evaluate_ml_warning_model.py --source mitdb --split ds1ds2 \
    --local-dir mitdb_local --model models/ml_warning_model.pkl
```

By default only the first `--seconds` of each record are used (60 s) to keep the
pure-Python filtering tractable; increase `--seconds` (or set 0 for whole
records) for a heavier, more complete run.
