# Test fixtures

`demo_ad8232_log.csv` is a **synthetic / demo** AD8232 packet log generated from
`ecg_monitor.synthetic`. It is used only to test the log parser and evaluator.

It is **not** a real hardware recording and must never be presented as one. It
contains, on purpose:

- ~24 s of synthetic ECG at 250 Hz in the `S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>` format,
- a lead-off period (electrodes "detached", LO flag high, ADC railed) from ~10 s to ~13 s,
- a sequence-number gap around ~16 s (simulated dropped packet),
- a small amount of timing jitter,
- two malformed lines to exercise the safe parser.

Real recordings live under `data/real_ad8232/` and are produced by
`scripts/record_ad8232_log.py` from actual hardware.
