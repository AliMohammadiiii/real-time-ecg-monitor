# Test Summary

Educational, non-diagnostic ECG prototype. This file records the current
verification state after the final report/documentation pass.

## Compile Check

```bash
python3 -m py_compile ecg_monitor/*.py scripts/*.py
```

- Status: OK.

## Focused Pytest

```bash
python3 -m pytest tests/test_ecg_pipeline.py tests/test_gui.py tests/test_realtime_log.py tests/test_qtdb_fiducials.py -q
```

- Result: 50 passed.
- Coverage focus: ECG pipeline, SQI/warning behavior, GUI replay/source logic,
  real-time log parsing/evaluation and QTDB fiducial matching.

## Full Unittest Suite

```bash
.venv/bin/python -m unittest discover -s tests -v
```

- Result: 71 tests OK, 1 skipped.
- Covered suites include ECG pipeline, serial/realtime parsing, GUI logic, QTDB,
  NSTDB, MIT-BIH ML helpers and model wrapper behavior.

## Validation Runs Reflected in the Thesis

- MIT-BIH QRS, 48 records, first 60 s:
  Se 96.65%, PPV 98.55%, F1 97.59%.
- MIT-BIH QRS, 48 records, first 5 min:
  Se 97.04%, PPV 98.42%, F1 97.73%.
- Detector comparison:
  current detector has the best F1 at 97.59%.
- QTDB fiducials, 105 records:
  P coverage 91.17% / MAE 19.09 ms,
  R coverage 99.94% / MAE 8.28 ms,
  T coverage 94.58% / MAE 39.18 ms.
- NSTDB SQI:
  morphology gating drops from 5/6 PQRST-usable windows at 24 dB to 0/6 at 6 dB.
- Synthetic scenario suite:
  7/7 scenarios passed.
- Real AD8232 recordings:
  F23 has 32662 valid samples, 0 packet loss, SQI 0.80, mean HR 79.48 bpm.
  M24 has 61570 valid samples, 0 packet loss, SQI 0.94, mean HR 78.06 bpm.
  Focused PQRST/interval reporting uses four automatically selected clean
  6-second windows, excluding motion/device-placement artifacts from the marker
  figures.
- Exploratory ML:
  synthetic holdout is perfect as a code-path check; MIT-BIH patient-wise run is
  flagged unstable because the test split has 287 normal-like samples and only 1
  warning-like sample.

## Generated Artifacts Verified

- `results/figures/*.png` contains 10 rendered validation figures.
- `results/ecg_session_report.html` embeds all default figures with relative
  paths that work from the report location.
- `results/real_ad8232_comparison/real_ad8232_comparison_report.md` contains
  the final two-subject real-recording comparison and references four generated
  comparison plots.
- `output/playwright/ecg_session_report_full.png` is a 1440 x 7579 full-page
  screenshot captured from the locally served HTML report.

## Known Skips / Limitations

- One unit test is skipped by design because it requires optional GUI/runtime
  support not always present in the environment.
- The current real-time validation includes two physical recordings. Broader
  claims still need more participants, repeated sessions, controlled protocol
  timestamps, and comparison against a clinical-grade reference.
- Exploratory ML is not clinically valid; it remains an advisory/code-path
  experiment only.
