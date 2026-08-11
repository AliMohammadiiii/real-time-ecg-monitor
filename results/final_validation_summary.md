# Final ECG Validation Summary

Educational prototype; not a medical device and not for diagnosis.

## Final Status

The project now has a complete end-to-end ECG prototype pipeline:

- AD8232/Arduino acquisition packet format with sequence number, timestamp,
  lead-off flags and checksum.
- Robust serial parser with malformed-packet, checksum, packet-loss and jitter
  accounting.
- Two-branch ECG preprocessing for QRS detection and morphology display.
- QRS/R-peak detection with T-wave/double-detection suppression.
- Tentative P/Q/R/S/T delineation with confidence gating.
- SQI-based suppression for unreliable signal windows.
- Rule-based, non-diagnostic warning logic.
- Live GUI with serial, replay and scenario sources.
- MIT-BIH, QTDB, NSTDB, synthetic scenario and real-time log evaluators.
- Automatic validation figures and HTML report.

## Current Numeric Results

| Area | Result |
|---|---|
| MIT-BIH 60 s QRS | 48 records, Se 96.65%, PPV 98.55%, F1 97.59% |
| MIT-BIH 5 min QRS | 48 records, Se 97.04%, PPV 98.42%, F1 97.73% |
| Best detector by F1 | Current detector, F1 97.59% |
| QTDB P marker | Coverage 91.17%, MAE 19.09 ms |
| QTDB R marker | Coverage 99.94%, MAE 8.28 ms |
| QTDB T marker | Coverage 94.58%, MAE 39.18 ms |
| NSTDB cleanest tested level | 118e24, mean SQI 0.681, PQRST usable 5/6 windows |
| NSTDB 6 dB level | mean SQI 0.450, PQRST usable 0/6 windows |
| Synthetic scenarios | 7/7 passed |
| Real AD8232 F23 recording | 32662 valid samples, packet loss 0.00%, SQI 0.80, mean HR 79.48 bpm |
| Real AD8232 M24 recording | 61570 valid samples, packet loss 0.00%, SQI 0.94, mean HR 78.06 bpm |
| Real AD8232 clean-window PQRST | 4 selected 6 s windows, all usable_for_pqrst |
| Focused pytest | 50 passed |
| Full unittest suite | 71 tests OK, 1 skipped |

## Output Artifacts

Core result files:

- `results/mitdb_qrs_summary.json`
- `results/mitdb_duration_summary.json`
- `results/mitdb_detector_comparison.json`
- `results/qtdb_fiducial_results.json`
- `results/nstdb_sqi_results.json`
- `results/scenario_suite_results.json`
- `results/real_ad8232_log_summary.json`
- `results/real_ad8232_F23_summary.json`
- `results/real_ad8232_M24_summary.json`
- `results/real_ad8232_comparison/real_ad8232_session_comparison.json`
- `results/ml_mitdb_results.json`

Generated visual artifacts:

- `results/figures/raw_vs_filtered_branches.png`
- `results/figures/ecg_pqrst_markers.png`
- `results/figures/sqi_timeline_scenarios.png`
- `results/figures/mitdb_per_record_f1.png`
- `results/figures/mitdb_duration_sweep.png`
- `results/figures/mitdb_detector_comparison.png`
- `results/figures/qtdb_timing_error_distribution.png`
- `results/figures/nstdb_sqi_stress.png`
- `results/figures/realtime_acquisition_summary.png`
- `results/figures/ml_mitdb_confusion_matrix.png`
- `results/real_ad8232_comparison/real_subject_filtered_snippets.png`
- `results/real_ad8232_comparison/real_subject_gui_marker_snapshots.png`
- `results/real_ad8232_comparison/real_subject_hr_sqi_timeline.png`
- `results/real_ad8232_comparison/real_subject_condition_hr_sqi.png`
- `results/real_ad8232_comparison/real_subject_acquisition_quality.png`

Presentation/report artifacts:

- `results/ecg_session_report.html`
- `results/real_ad8232_comparison/real_ad8232_comparison_report.md`
- `results/real_ad8232_comparison/real_ad8232_comparison_report.html`
- `output/playwright/ecg_session_report_full.png`
- `docs/technical_report/chapter4_implementation.md`
- `docs/technical_report/chapter5_conclusion.md`

## Remaining Scientific Limitations

These are documented limitations, not missing implementation tasks:

- The system is single-lead and educational.
- AD8232/Arduino is not medical-grade hardware.
- Q/S in QTDB are only approximate boundary comparisons because QTDB does not
  annotate Q and S peaks directly.
- T-wave timing remains the weakest fiducial result.
- Real AD8232 field validation now includes two healthy young-adult recordings,
  but broader validation still needs more people, repeated sessions, controlled
  condition-change timestamps, and clinical-grade reference comparison.
- Focused real-recording PQRST analysis intentionally uses only clean 6-second
  windows; motion/device-placement artifacts are excluded from marker figures and
  interval tables.
- Exploratory ML is unstable on MIT-BIH because the reduced patient-wise test set
  is highly imbalanced.
- Full-record MIT-BIH can be run by the scripts, but the reported thesis result
  uses 60 s and 5 min windows for reproducibility and runtime control.
