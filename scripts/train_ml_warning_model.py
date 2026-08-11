"""Train the exploratory, non-diagnostic ML warning model.

Two data sources:

* ``--source synthetic`` (default): a small synthetic feature table so the model
  can be trained without any dataset download. This only exercises the code path
  and carries no clinical validity.
* ``--source mitdb``: real MIT-BIH beats using a **patient-wise** DS1/DS2 split
  (train on DS1). Labels come from the cardiologist annotations, so this is a
  beat-type classification experiment, reported only as an exploratory advisory.

Examples
--------
    python3 scripts/train_ml_warning_model.py --source synthetic
    python3 scripts/train_ml_warning_model.py --source mitdb --split ds1ds2 \
        --output models/ml_warning_model.pkl
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from ecg_monitor import ExploratoryMLWarningModel, delineate_pqrst, feature_matrix_from_markers
from ecg_monitor.ml_features import FEATURE_NAMES
from ecg_monitor.ml_model import SklearnUnavailable
from ecg_monitor.synthetic import synthetic_ecg
from ecg_monitor import mitdb_ml


def synthetic_training_table() -> tuple[np.ndarray, np.ndarray]:
    rows = []
    labels = []
    for hr, label, noise in [
        (72.0, "normal_like", 0.015),
        (80.0, "normal_like", 0.020),
        (45.0, "warning_like", 0.015),
        (125.0, "warning_like", 0.015),
        (95.0, "warning_like", 0.090),
    ]:
        signal, _ = synthetic_ecg(16.0, 250.0, heart_rate_bpm=hr, noise_std=noise, seed=int(hr * 10))
        markers = delineate_pqrst(signal, 250.0)
        x = feature_matrix_from_markers(signal, 250.0, markers)
        rows.append(x)
        labels.extend([label] * len(x))
    return np.vstack(rows), np.asarray(labels, dtype=object)


def _class_counts(y: np.ndarray) -> dict:
    return {label: int(np.sum(y == label)) for label in sorted(set(y.tolist()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["synthetic", "mitdb"], default="synthetic")
    parser.add_argument("--split", choices=["ds1ds2"], default="ds1ds2", help="Patient-wise split (train on DS1)")
    parser.add_argument("--labels", choices=["binary", "aami"], default="binary")
    parser.add_argument("--records", nargs="*", type=str, help="Override training records (default DS1)")
    parser.add_argument("--max-records", type=int, default=None, help="Cap number of training records")
    parser.add_argument("--seconds", type=float, default=60.0, help="Seconds per MIT-BIH record")
    parser.add_argument("--lead", type=int, default=0)
    parser.add_argument("--local-dir", default=None, help="Read MIT-BIH records from a local directory")
    parser.add_argument("--model-type", choices=["logreg", "linsvc", "rf"], default="logreg")
    parser.add_argument("--output", default="results/ml_warning_model.pkl", help="Output model .pkl path")
    parser.add_argument("--features-csv", default=None, help="Optional features CSV path")
    parser.add_argument("--summary-json", default=None, help="Training summary JSON path")
    args = parser.parse_args(argv)

    skipped = {}
    per_record = {}
    if args.source == "synthetic":
        x, y = synthetic_training_table()
        training_source = "synthetic ECG feature table"
        records_used = None
        summary_json = args.summary_json or "results/ml_train_summary.json"
    else:
        records = args.records or [str(r) for r in mitdb_ml.DS1]
        if args.max_records is not None:
            records = records[: args.max_records]
        try:
            x, y, groups, skipped, per_record = mitdb_ml.build_dataset(
                records, scheme=args.labels, seconds=args.seconds, lead=args.lead, local_dir=args.local_dir
            )
        except mitdb_ml.DatasetUnavailable as exc:
            print(
                f"\nMIT-BIH training data unavailable: {exc}\n"
                "Install wfdb / restore internet, or pre-download with --local-dir, then run:\n"
                "  python3 scripts/train_ml_warning_model.py --source mitdb --split ds1ds2 "
                "--output models/ml_warning_model.pkl",
                file=sys.stderr,
            )
            return 2
        training_source = f"MIT-BIH DS1 (patient-wise), scheme={args.labels}"
        records_used = records
        summary_json = args.summary_json or "results/ml_mitdb_train_summary.json"

    if x.shape[0] == 0 or len(set(y.tolist())) < 2:
        print(f"\nNot enough labelled beats / classes to train (n={x.shape[0]}, "
              f"classes={sorted(set(y.tolist()))}).", file=sys.stderr)
        return 2

    out_model = Path(args.output)
    out_model.parent.mkdir(parents=True, exist_ok=True)
    try:
        model = ExploratoryMLWarningModel().fit(x, y, model_type=args.model_type)
    except SklearnUnavailable as exc:
        raise SystemExit(str(exc))
    model.save(out_model)

    if args.features_csv:
        features_csv = Path(args.features_csv)
        features_csv.parent.mkdir(parents=True, exist_ok=True)
        with features_csv.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([*FEATURE_NAMES, "label"])
            for row, label in zip(x, y):
                writer.writerow([*row, label])

    counts = _class_counts(y)
    unstable = min(counts.values()) < 10 if counts else True
    summary = {
        "scope": "exploratory_non_diagnostic",
        "model": f"{args.model_type} + StandardScaler (class_weight=balanced)",
        "training_source": training_source,
        "label_scheme": args.labels if args.source == "mitdb" else "binary_synthetic",
        "split": args.split if args.source == "mitdb" else "n/a",
        "records": records_used,
        "n_samples": int(len(y)),
        "class_counts": counts,
        "skipped": skipped,
        "per_record": per_record,
        "feature_names": list(FEATURE_NAMES),
        "unstable_small_classes": bool(unstable),
        "note": "Beat-type ML experiment; not a validated diagnosis. Advisory only.",
    }
    summary_path = Path(summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps({k: v for k, v in summary.items() if k != "per_record"}, indent=2))
    print(f"saved_model={out_model}")
    print(f"saved_summary={summary_path}")
    if unstable:
        print("WARNING: small class counts — treat metrics as unstable/exploratory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
