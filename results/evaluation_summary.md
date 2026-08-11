# Evaluation Summary

Educational prototype; not a medical device and not for diagnosis.

This file summarizes the current validation artifacts after the final detector,
SQI, GUI replay, report-generation and documentation updates.

## Unit and Integration Checks

- `python3 -m py_compile ecg_monitor/*.py scripts/*.py` — OK.
- `python3 -m pytest tests/test_ecg_pipeline.py tests/test_gui.py tests/test_realtime_log.py tests/test_qtdb_fiducials.py -q` — 50 passed.
- `.venv/bin/python -m unittest discover -s tests -v` — 71 tests OK, 1 skipped.

## MIT-BIH QRS Evaluation

Source: local MIT-BIH Arrhythmia Database records.

| Scope | Records | TP | FP | FN | Sensitivity | PPV | F1 | FP/min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| First 60 s | 48 | 3660 | 54 | 127 | 96.65% | 98.55% | 97.59% | 1.125 |
| First 5 min | 48 | 18221 | 293 | 555 | 97.04% | 98.42% | 97.73% | 1.221 |

The main detector improvement was false-positive reduction through
T-wave/double-detection suppression. The current detector keeps sensitivity high
while raising PPV above 98%.

## Detector Comparison

Scope: MIT-BIH, first 60 s of all 48 local records.

| Detector | Sensitivity | PPV | F1 | Runtime ms/min ECG |
|---|---:|---:|---:|---:|
| Pan-Tompkins baseline | 89.91% | 99.91% | 94.65% | 17.73 |
| Current detector | 96.65% | 98.55% | 97.59% | 4.95 |
| Hamilton-style | 96.70% | 96.67% | 96.69% | 4.16 |

The current detector has the best F1 in this comparison.

## QTDB Fiducial Evaluation

Source: local QT Database, 105 records, manual `q1c` annotations when available.

| Marker | Mean coverage | Mean MAE |
|---|---:|---:|
| P | 91.17% | 19.09 ms |
| R | 99.94% | 8.28 ms |
| T | 94.58% | 39.18 ms |
| Q vs QRS onset approximation | 99.94% | 26.80 ms |
| S vs QRS offset approximation | 99.92% | 24.65 ms |

QTDB does not annotate Q and S peaks directly, so Q/S are reported only as
explicit approximate-boundary comparisons against QRS onset/offset.

## NSTDB SQI Noise Stress Test

Source: local MIT-BIH Noise Stress Test Database, subject 118, 60 s window after
the 5-minute clean prefix.

| Record | SNR | Mean SQI | PQRST-usable windows | QRS count |
|---|---:|---:|---:|---:|
| 118e24 | 24 dB | 0.681 | 5/6 | 75 |
| 118e18 | 18 dB | 0.645 | 4/6 | 78 |
| 118e12 | 12 dB | 0.506 | 1/6 | 83 |
| 118e06 | 6 dB | 0.450 | 0/6 | 95 |
| 118e00 | 0 dB | 0.510 | 1/6 | 94 |
| 118e_6 | -6 dB | 0.521 | 1/6 | 84 |

SQI progressively gates morphology analysis as noise increases. The trend is not
perfectly monotonic at 0 dB and -6 dB because NSTDB noise is applied in
alternating segments.

## Scenario Suite

Synthetic scenario suite:

- Scenarios: 7.
- Scenario pass rate: 100%.
- HR pass rate: 100%.
- Rhythm/warning pass rate: 100%.
- Mean marker completeness: 99.05%.

## Real-Time / AD8232 Real Recordings

Two final hardware recordings were captured through the live GUI, with raw
serial packets saved at the same time as the waveform display.

| Subject | Duration | Valid samples | Packet loss | Checksum errors | Overall SQI | Mean HR |
|---|---:|---:|---:|---:|---|---:|
| Female 23 (F23) | 130.64 s | 32662 | 0.00% | 0 | usable_for_pqrst (0.80) | 79.48 bpm |
| Male 24 (M24) | 246.28 s | 61570 | 0.00% | 0 | usable_for_pqrst (0.94) | 78.06 bpm |

Focused PQRST analysis uses only automatically selected clean 6-second windows,
because parts of the real recordings include motion/device-placement artifacts.
Windows are ranked by SQI, lead-off status, clipping, RR stability, sufficient
R-peaks and P/Q/R/S/T marker visibility. The final clean windows were:

| Subject | Clean window | HR | SQI | Rule-based label |
|---|---:|---:|---|---|
| Female 23 (F23) | 24.0-30.0 s | 72.70 bpm | usable_for_pqrst (0.75) | Normal rhythm candidate |
| Female 23 (F23) | 18.0-24.0 s | 75.06 bpm | usable_for_pqrst (0.74) | Normal rhythm candidate |
| Male 24 (M24) | 132.0-138.0 s | 77.26 bpm | usable_for_pqrst (0.83) | Low preliminary rhythm warning |
| Male 24 (M24) | 77.0-83.0 s | 73.58 bpm | usable_for_pqrst (0.82) | Normal rhythm candidate |

The rule-based rhythm labels remain educational and non-diagnostic.

## Exploratory ML

Synthetic holdout is a code-path check only:

- Accuracy: 100%.
- Macro F1: 100%.
- AUROC: 100%.

MIT-BIH patient-wise exploratory run:

- Train samples: 278.
- Test samples: 288.
- Test normal-like: 287.
- Test warning-like: 1.
- Accuracy: 99.65%.
- Macro F1: 49.91%.
- Weighted F1: 99.48%.

The MIT-BIH ML result is flagged as unstable because the test set is extremely
imbalanced. It is not used as diagnostic evidence.

## Generated Figures and Report

Figures are in `results/figures/`:

- `raw_vs_filtered_branches.png`
- `ecg_pqrst_markers.png`
- `sqi_timeline_scenarios.png`
- `mitdb_per_record_f1.png`
- `mitdb_duration_sweep.png`
- `mitdb_detector_comparison.png`
- `qtdb_timing_error_distribution.png`
- `nstdb_sqi_stress.png`
- `realtime_acquisition_summary.png`
- `ml_mitdb_confusion_matrix.png`

Real-recording figures are in `results/real_ad8232_comparison/`:

- `real_subject_filtered_snippets.png`
- `real_subject_gui_marker_snapshots.png`
- `real_subject_hr_sqi_timeline.png`
- `real_subject_condition_hr_sqi.png`
- `real_subject_acquisition_quality.png`

Report and screenshot:

- `results/ecg_session_report.html`
- `results/real_ad8232_comparison/real_ad8232_comparison_report.md`
- `results/real_ad8232_comparison/real_ad8232_comparison_report.html`
- `output/playwright/ecg_session_report_full.png`
