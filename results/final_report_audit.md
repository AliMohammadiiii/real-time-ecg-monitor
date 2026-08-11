# Final Report Audit

Educational, non-diagnostic ECG prototype. This audit records the final report
cleanup after adding the real AD8232 recordings and the supplied hardware
figures.

## Content Checks

- Chapter 4 hardware wiring now matches the final Arduino sketch:
  AD8232 OUTPUT -> A5, LO+ -> D3, LO- -> D2, VCC -> 3.3 V, GND -> GND.
- Chapter 4 includes the supplied RA/LA/RL electrode-placement figure and the
  AD8232/Arduino/three-electrode wiring figure.
- Chapter 4 figure numbering was renumbered after adding the two hardware
  figures.
- Chapter 5 real-recording analysis describes clean-window PQRST analysis rather
  than equal-half splitting.
- README and `docs/hardware_recording_protocol.md` no longer claim that no real
  AD8232 recordings are included.
- Real-recording PQRST figures use clean 6-second windows only, excluding
  obvious motion/device-placement artifacts.

## Key Real AD8232 Results

| Subject | Clean window | HR | SQI | Rule-based output |
|---|---:|---:|---:|---|
| F23 | 24.0-30.0 s | 72.70 bpm | 0.75 | Normal rhythm candidate |
| F23 | 18.0-24.0 s | 75.06 bpm | 0.74 | Normal rhythm candidate |
| M24 | 132.0-138.0 s | 77.26 bpm | 0.83 | Low preliminary rhythm warning |
| M24 | 77.0-83.0 s | 73.58 bpm | 0.82 | Normal rhythm candidate |

## Verified Artifacts

- `docs/technical_report/chapter4_implementation.md`
- `docs/technical_report/chapter5_conclusion.md`
- `Technical_Report/Real_Time_ECG_Monitor_Technical_Report.docx`
- `results/real_ad8232_comparison/real_ad8232_comparison_report.html`
- `results/real_ad8232_comparison/real_subject_gui_marker_snapshots.png`

## Validation Commands

```bash
python3 -m py_compile scripts/analyze_real_ad8232_sessions.py scripts/append_real_ad8232_docx_section.py
python3 -m pytest tests/test_gui.py tests/test_realtime_log.py tests/test_ecg_pipeline.py tests/test_qtdb_fiducials.py -q
.venv/bin/python -m unittest discover -s tests -v
```

Results:

- Focused pytest: 50 passed.
- Full unittest suite: 71 OK, 1 skipped.
- Markdown image references: 0 missing.
- DOCX rendered successfully to page PNGs and PDF for visual QA.

## Remaining Limitations

- The system is still single-lead and educational, not medical-grade.
- P-R peak, QRS, QT and QTc are tentative single-lead estimates.
- Broader real-hardware validation still needs more people, repeated sessions,
  controlled protocol timestamps and comparison against a clinical reference.
