# Real-Time ECG Monitoring Prototype

Educational undergraduate ECG thesis prototype:

**Design and Implementation of a Real-Time ECG Monitoring System for PQRST Detection and Preliminary Arrhythmia Risk Estimation Using Arduino, AD8232, and Computer-Based Digital Signal Processing**

This project is a non-diagnostic signal-processing system. It is not a medical
device and must not be used for clinical diagnosis, treatment decisions, or
emergency monitoring.

## Repository Layout

- `arduino/ad8232_sampler/ad8232_sampler.ino` — Arduino acquisition sketch.
- `ecg_monitor/` — Python DSP, QRS detection, PQRST estimation, SQI, warnings, and exploratory ML.
- `scripts/` — evaluation, log analysis, and ML scripts.
- `tests/` — unit tests.
- `docs/deepresearch/` — research synthesis inputs and thesis synthesis.
- `docs/thesis/` — generated thesis Chapter 4, Chapter 5, IEEE references, and figures.
- `results/` — generated evaluation outputs.

## Hardware Setup

Recommended wiring:

| AD8232 | Arduino |
|---|---|
| OUTPUT | A5 |
| LO+ | D3 |
| LO- | D2 |
| VCC | 3.3V in the final recording setup |
| GND | GND |

Use disposable ECG electrodes according to the module cable labels. For human
testing, use battery power where possible and prefer a USB isolator. The final
Arduino sketch in `arduino/ad8232_sampler/ad8232_sampler.ino` matches this
wiring.

## Arduino Packet Format

Default CSV packet:

```text
S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>,<checksum>
```

Fields:

- `seq`: monotonically increasing sample counter.
- `micros`: Arduino timestamp.
- `adc`: raw 10-bit ADC value.
- `lo_plus`, `lo_minus`: AD8232 lead-off flags.
- `checksum`: optional XOR packet-integrity check used by the current Arduino
  sketch.

The Python parser also keeps backward compatibility with the older
`S,seq,micros,adc,lo_plus,lo_minus` and `timestamp,adc,lead_off` formats.

## Installation

```bash
cd /Users/ali/Documents/Bachlor
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

## Run Tests

```bash
.venv/bin/python -m unittest discover -s tests
```

## MIT-BIH QRS Evaluation

Single record:

```bash
.venv/bin/python scripts/evaluate_mitdb.py --record 100 --seconds 60
```

Representative subset:

```bash
.venv/bin/python scripts/evaluate_mitdb.py \
  --records 100 101 103 105 106 118 200 208 \
  --seconds 30
```

Outputs are saved under `results/`.

Multi-duration thesis table:

```bash
.venv/bin/python scripts/evaluate_mitdb_durations.py \
  --all-local --local-dir data/physionet/mitdb --durations 60 300

# Full-record mode is supported but can take longer:
.venv/bin/python scripts/evaluate_mitdb_durations.py \
  --all-local --local-dir data/physionet/mitdb --durations 60 300 --include-full
```

Detector comparison:

```bash
.venv/bin/python scripts/compare_mitdb_detectors.py \
  --all-local --local-dir data/physionet/mitdb --seconds 60
```

Results: `results/mitdb_qrs_summary.json`,
`results/mitdb_duration_summary.csv`, and
`results/mitdb_detector_comparison.csv`.

## QTDB Fiducial Evaluation

Matches predicted P/R/T (and approximate Q/S boundary) landmarks against the QT
Database reference annotations:

```bash
.venv/bin/python scripts/evaluate_qtdb.py --record sel100 --seconds 60
.venv/bin/python scripts/evaluate_qtdb.py --records sel100 sel103 sel114
```

Results: `results/qtdb_fiducial_results.csv` / `.json`. See
`results/qtdb_fiducial_todo.md` for the documented annotation mapping.

## NSTDB SQI Noise Stress Test

Shows how SQI and warning gating degrade with added noise:

```bash
.venv/bin/python scripts/evaluate_nstdb_sqi.py --max-records 1 --seconds 60
.venv/bin/python scripts/evaluate_nstdb_sqi.py --records 118e24 118e06 118e_6

# Reproducible offline (one-time download, then read locally):
.venv/bin/python -c "import wfdb; wfdb.dl_database('nstdb','nstdb_local', \
  records=['118e24','118e18','118e12','118e06','118e00','118e_6'])"
.venv/bin/python scripts/evaluate_nstdb_sqi.py --local-dir nstdb_local \
  --seconds 60 --plot-output results/nstdb_sqi_plot.png
```

Results: `results/nstdb_sqi_results.csv` / `.json` / `nstdb_sqi_plot.png`.

## Real AD8232 Hardware Log

Record from hardware (see `docs/hardware_recording_protocol.md` for wiring and
safety):

```bash
# Record 30 s at rest (find the port with: ls /dev/cu.usbmodem*)
.venv/bin/python scripts/record_ad8232_log.py \
  --port /dev/cu.usbmodemXXXX --duration 30 --subject-id demo001 --condition rest

# Evaluate a recorded log
.venv/bin/python scripts/evaluate_realtime_log.py \
  data/real_ad8232/YYYYMMDD_HHMMSS_ad8232_log.csv \
  --ecg-plot results/real_ad8232_ecg_plot.png \
  --sqi-plot results/real_ad8232_sqi_timeline.png
```

The evaluator reports duration, sampling-rate estimate, packet loss, malformed
count, timing jitter, lead-off periods, ADC clipping, flatline periods, an SQI
timeline, R-peak count, mean HR, and the warning timeline. The repository also
contains two final real AD8232 recordings from a 23-year-old female subject and
a 24-year-old male subject:

- `data/real_ad8232/20260704_190653_ad8232_live_log.csv`
- `data/real_ad8232/20260704_191215_ad8232_live_log.csv`

The comparison report uses only clean 6-second windows for PQRST analysis so
motion/device-placement artifacts do not dominate the marker figures:

```bash
.venv/bin/python scripts/analyze_real_ad8232_sessions.py
```

Outputs are written to `results/real_ad8232_comparison/`. You can also validate
the evaluator on the labelled **synthetic** demo log without hardware:

```bash
.venv/bin/python scripts/evaluate_realtime_log.py tests/fixtures/demo_ad8232_log.csv
```

## Live GUI

Optional; needs a Qt binding + PyQtGraph (`pip install pyqtgraph PyQt5`). If they
are missing the script exits with install instructions.

```bash
# Demo (no Arduino needed)
.venv/bin/python scripts/run_live_gui.py --demo synthetic

# Dataset replay from a local WFDB record
.venv/bin/python scripts/run_live_gui.py --mode replay \
  --replay-wfdb 100 --local-dir data/physionet/mitdb

# Scenario simulation panel
.venv/bin/python scripts/run_live_gui.py --mode scenario

# Live from Arduino
.venv/bin/python scripts/run_live_gui.py --port /dev/cu.usbmodemXXXX --baud 115200 --fs 250
```

See `docs/gui_usage.md`.

## Exploratory ML

The ML path is optional, secondary, and non-diagnostic. Synthetic mode runs
without downloads; MIT-BIH mode uses a patient-wise DS1/DS2 split.

```bash
# Synthetic (reproducible, no downloads)
.venv/bin/python scripts/train_ml_warning_model.py --source synthetic
.venv/bin/python scripts/evaluate_ml_warning_model.py --source synthetic

# MIT-BIH patient-wise (train DS1, test DS2 — no leakage)
.venv/bin/python scripts/train_ml_warning_model.py --source mitdb --split ds1ds2 \
  --output models/ml_warning_model.pkl
.venv/bin/python scripts/evaluate_ml_warning_model.py --source mitdb --split ds1ds2 \
  --model models/ml_warning_model.pkl
```

ML output must be treated only as an exploratory advisory. It is suppressed
when SQI is poor and does not override rule-based safety logic. See
`docs/ml_experiment.md`.

## Scenario Suite, Figures, and HTML Report

```bash
.venv/bin/python scripts/evaluate_scenario_suite.py --source synthetic
.venv/bin/python scripts/generate_validation_figures.py
python3 scripts/generate_ecg_session_report.py
```

Generated artifacts:

- `results/scenario_suite_results.json`
- `results/figures/ecg_pqrst_markers.png`
- `results/figures/raw_vs_filtered_branches.png`
- `results/figures/sqi_timeline_scenarios.png`
- `results/figures/mitdb_per_record_f1.png`
- `results/figures/qtdb_timing_error_distribution.png`
- `results/ecg_session_report.html`

## Thesis Files

- `docs/thesis/chapter4_implementation.md`
- `docs/thesis/chapter5_conclusion.md`
- `docs/thesis/references_ieee.md`
- `docs/thesis/figures/*.svg`

## Additional Documentation

- `docs/hardware_recording_protocol.md` — wiring, safety, recording, evaluation.
- `docs/gui_usage.md` — live GUI usage.
- `docs/ml_experiment.md` — synthetic vs MIT-BIH patient-wise ML.
- `results/qtdb_fiducial_todo.md`, `results/nstdb_sqi_todo.md` — evaluation notes.

## Current Limitations

- Single-lead ECG only.
- AD8232/Arduino are not medical-grade hardware.
- P and T fiducials are approximate and confidence-gated (T timing is the
  weakest fiducial in the QTDB evaluation).
- QTDB does not annotate Q/S peaks, so those are only compared against QRS
  onset/offset as an approximate boundary metric.
- NSTDB noise levels drive SQI down to `usable_for_rate_qrs` (morphology gated
  off) rather than full warning suppression; hard suppression is reserved for
  lead-off / flatline / clipping.
- Real AD8232 validation currently includes two healthy young-adult recordings.
  Broader hardware claims still require more participants, repeated sessions,
  controlled protocol timestamps, and comparison against a clinical reference.
- The MIT-BIH patient-wise ML result committed here is a reduced demonstration
  (a small record subset); the full DS1/DS2 run requires downloading all records.
- Exploratory ML is a non-diagnostic beat-type experiment, not a validated
  arrhythmia classifier.
