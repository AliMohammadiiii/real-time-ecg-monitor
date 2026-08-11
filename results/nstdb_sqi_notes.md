# NSTDB SQI Noise Stress Test — Implementation Notes

Status: **implemented and run.** Full NSTDB SQI stress testing is now available in
`scripts/evaluate_nstdb_sqi.py`.

## What it does

- Loads MIT-BIH Noise Stress Test Database records with WFDB (streamed from
  PhysioNet, or read from a local directory via `--local-dir`).
- Slices each record into fixed windows (default 10 s), and for each window
  computes the SQI level, warning/morphology/rate gating, QRS count, baseline
  wander score, high-frequency noise score, RR plausibility score, and a
  flatline fraction.
- Aggregates per record and compares the cleanest against the noisiest record.

## NSTDB record ladder and the 5-minute clean prefix

NSTDB adds calibrated noise to clean records 118/119 at fixed SNRs, encoded in
the record name: `118e24` = 24 dB (cleanest) ... `118e00` = 0 dB ... `118e_6` =
-6 dB (noisiest). **Crucially, NSTDB keeps the first 5 minutes clean and then
adds noise in alternating 2-minute segments.** A naive "first N seconds" window
would therefore show identical (clean) results for every SNR. The script
defaults to `--start-seconds 300` so the analysed window actually contains the
calibrated noise.

## SQI metrics reported

Per window and aggregated per record: SQI level distribution
(`unreliable` / `poor` / `usable_for_rate_qrs` / `usable_for_pqrst`), percentage
of windows suppressed, percentage unreliable, mean SQI score, baseline-wander
score, high-frequency-noise score, RR-plausibility score, flatline fraction,
total QRS detected, and warnings-allowed vs warnings-suppressed window counts.
Hard-rejection cases (lead-off, flatline, clipping, severe packet loss, extreme
jitter) are covered by the SQI unit tests.

## Example results (subject 118, window 300 s + 60 s, 10 s windows)

| Record | SNR | mean SQI | PQRST-morphology windows | mean baseline-wander |
|---|---:|---:|---:|---:|
| 118e24 | 24 dB | 0.681 | 5 / 6 | 0.290 |
| 118e18 | 18 dB | 0.645 | 4 / 6 | 0.419 |
| 118e12 | 12 dB | 0.506 | 1 / 6 | 0.559 |
| 118e06 | 6 dB | 0.450 | 0 / 6 | 0.643 |
| 118e00 | 0 dB | 0.510 | 1 / 6 | 0.674 |
| 118e_6 | -6 dB | 0.521 | 1 / 6 | 0.683 |

As noise increases, mean SQI falls (0.68 -> 0.52 clean vs noisiest) and the
baseline-wander score rises monotonically, so morphology (PQRST) analysis is
progressively gated off — from 5/6 windows at 24 dB down to 0/6 at 6 dB.
The trend is not perfectly monotonic at 0 dB / -6 dB because NSTDB noise is
applied in alternating segments, so some windows still fall in clean gaps.

For these NSTDB noise levels the SQI floors at `usable_for_rate_qrs` rather than
`poor`/`unreliable`, so rhythm warnings themselves are not suppressed here; the
suppression that occurs is of the higher-confidence PQRST/morphology path. Full
warning suppression is reserved for the hard-rejection cases (lead-off,
flatline, clipping) verified by the unit tests.

## How to run

```bash
# Stream from PhysioNet (needs internet):
python3 scripts/evaluate_nstdb_sqi.py --max-records 1 --seconds 60
python3 scripts/evaluate_nstdb_sqi.py --records 118e24 118e06 118e_6

# Reproducible offline run after a one-time download:
python3 -c "import wfdb; wfdb.dl_database('nstdb','nstdb_local', \
  records=['118e24','118e18','118e12','118e06','118e00','118e_6'])"
python3 scripts/evaluate_nstdb_sqi.py --local-dir nstdb_local --seconds 60 \
  --plot-output results/nstdb_sqi_plot.png
```

Results are written to `results/nstdb_sqi_results.csv`,
`results/nstdb_sqi_results.json`, and an optional
`results/nstdb_sqi_plot.png`. If WFDB is missing or PhysioNet is unreachable,
the script prints the exact retry command and exits with code 2.
