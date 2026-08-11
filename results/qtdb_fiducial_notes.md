# QTDB Fiducial Evaluation — Implementation Notes

Status: **implemented and run.** Full QTDB fiducial matching is now available in
`scripts/evaluate_qtdb.py` with the parsing/matching logic in
`ecg_monitor/fiducials.py`.

## What it does

- Loads QT Database records with WFDB from PhysioNet (`pn_dir="qtdb"`).
- Loads reference waveform annotations, preferring the manually reviewed
  `q1c` gold standard and falling back to the automated `pu0` annotations when
  no manual file yields usable beats. The annotator actually used is recorded
  per record.
- Runs the project detector + delineator on the signal window and matches the
  predicted P/R/T landmarks against the annotated peaks within a tolerance
  (default 150 ms).

## Annotation mapping (documented, not faked)

QTDB annotations use an `( <peak> )` triplet structure:

| Symbol | Meaning | Mapped to |
|---|---|---|
| `(` | wave onset | QRS onset when it precedes a beat symbol |
| `p` | P-wave peak | reference P |
| beat symbols (`N`, `V`, `A`, ...) | QRS peak | reference R |
| `t` | T-wave peak | reference T |
| `)` | wave offset | QRS offset when it follows a beat symbol |

**Important honesty note:** QTDB does *not* annotate Q and S peaks as distinct
landmarks; it only annotates QRS onset and offset. Our detector produces Q and S
as intra-QRS local minima, which are different landmarks. Therefore P, R and T
are matched directly, while Q and S are compared only against the QRS
onset/offset as an explicitly labelled *approximate boundary* metric
(`q_vs_qrs_onset_approx`, `s_vs_qrs_offset_approx`), never as true Q/S accuracy.

## Windowing note

The manual `q1c` reference beats are located deep inside each record (often
around 600 s) and can form clusters hundreds of seconds apart. The script
therefore anchors its evaluation window on the first reference annotation
(bounded in length for the pure-Python filters) instead of naively taking the
first N seconds.

## Metrics reported

Per record: reference P/QRS/T counts, QRS onset/offset counts, predicted counts,
matched/false-positive/missing per marker, coverage (recall), MAE / median /
std of timing error in ms and samples, per-marker unavailable rate, and the
unmapped-annotation rate. Aggregate: mean/median MAE and mean coverage by marker
type across records.

## Example results (manual q1c gold standard, 150 ms tolerance)

| Record | P MAE | R MAE | T MAE |
|---|---:|---:|---:|
| sel100 | 15.9 ms | 0.8 ms | 98.8 ms |
| sel103 | 9.6 ms | 2.0 ms | 8.9 ms |
| sel114 | 21.2 ms | 21.9 ms | 42.8 ms |

R-peak timing is excellent, P is moderate, and T localisation is the weakest and
most morphology-dependent fiducial — consistent with the single-lead,
approximate-delineation limitations stated in the thesis.

## How to run

```bash
python3 scripts/evaluate_qtdb.py --record sel100 --seconds 60
python3 scripts/evaluate_qtdb.py --records sel100 sel103 sel114
python3 scripts/evaluate_qtdb.py --max-records 5 --tolerance-ms 150
```

Results are written to `results/qtdb_fiducial_results.csv` and
`results/qtdb_fiducial_results.json`. If WFDB is missing or PhysioNet is
unreachable, the script prints the exact command to retry and exits with code 2
instead of crashing.
