"""Evaluate the exploratory, non-diagnostic ML warning model.

Mirrors ``train_ml_warning_model.py``:

* ``--source synthetic`` (default): evaluate on a synthetic holdout table.
* ``--source mitdb --split ds1ds2``: evaluate on MIT-BIH **DS2** (patient-wise),
  using a model trained on DS1. Because DS1 and DS2 are disjoint patient sets,
  there is no beat/patient leakage.

Examples
--------
    python3 scripts/evaluate_ml_warning_model.py --source synthetic
    python3 scripts/evaluate_ml_warning_model.py --source mitdb --split ds1ds2 \
        --model models/ml_warning_model.pkl
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
from ecg_monitor.synthetic import synthetic_ecg
from ecg_monitor import mitdb_ml


def synthetic_eval_table() -> tuple[np.ndarray, np.ndarray]:
    rows = []
    labels = []
    for hr, label, noise, seed in [
        (70.0, "normal_like", 0.018, 11),
        (58.0, "normal_like", 0.020, 12),
        (42.0, "warning_like", 0.018, 13),
        (132.0, "warning_like", 0.018, 14),
        (78.0, "warning_like", 0.120, 15),
    ]:
        signal, _ = synthetic_ecg(14.0, 250.0, heart_rate_bpm=hr, noise_std=noise, seed=seed)
        markers = delineate_pqrst(signal, 250.0)
        rows.append(feature_matrix_from_markers(signal, 250.0, markers))
        labels.extend([label] * len(markers))
    return np.vstack(rows), np.asarray(labels, dtype=object)


def _metrics(y_true, y_pred, labels, proba=None, pos_label=None):
    from sklearn.metrics import (
        accuracy_score, classification_report, confusion_matrix,
        f1_score, precision_score, recall_score, roc_auc_score,
    )
    out = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_macro": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "labels": labels,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "classification_report": classification_report(y_true, y_pred, labels=labels, zero_division=0),
    }
    if proba is not None and pos_label is not None and len(set(y_true)) == 2:
        try:
            out["auroc"] = float(roc_auc_score((np.asarray(y_true) == pos_label).astype(int), proba))
        except Exception:
            out["auroc"] = None
    return out


def _save_outputs(summary, out_json, out_csv, cm_csv):
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    with Path(out_json).open("w") as f:
        json.dump(summary, f, indent=2)
    with Path(out_csv).open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key, value in summary.items():
            if key not in {"confusion_matrix", "classification_report", "per_record", "class_counts_test", "class_counts_train"}:
                writer.writerow([key, value])
    if cm_csv:
        with Path(cm_csv).open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["true\\pred", *summary["labels"]])
            for label, row in zip(summary["labels"], summary["confusion_matrix"]):
                writer.writerow([label, *row])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["synthetic", "mitdb"], default="synthetic")
    parser.add_argument("--split", choices=["ds1ds2"], default="ds1ds2")
    parser.add_argument("--labels", choices=["binary", "aami"], default="binary")
    parser.add_argument("--records", nargs="*", type=str, help="Override test records (default DS2)")
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--lead", type=int, default=0)
    parser.add_argument("--local-dir", default=None)
    parser.add_argument("--model", default="results/ml_warning_model.pkl", help="Model .pkl path")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-csv", default=None)
    parser.add_argument("--confusion-csv", default=None)
    args = parser.parse_args(argv)

    try:
        import sklearn  # noqa: F401
    except ImportError as exc:
        raise SystemExit("Install scikit-learn to evaluate the exploratory ML module.") from exc

    model_path = Path(args.model)
    if not model_path.exists():
        raise SystemExit(f"Model not found: {model_path}. Train it first with train_ml_warning_model.py.")
    try:
        model = ExploratoryMLWarningModel.load(model_path)
    except Exception as exc:
        raise SystemExit(f"Could not load model: {exc}") from exc

    skipped = {}
    per_record = {}
    if args.source == "synthetic":
        x, y = synthetic_eval_table()
        eval_source = "synthetic holdout ECG feature table"
        records_used = None
        out_json = args.output_json or "results/ml_results.json"
        out_csv = args.output_csv or "results/ml_results.csv"
        cm_csv = args.confusion_csv
    else:
        records = args.records or [str(r) for r in mitdb_ml.DS2]
        if args.max_records is not None:
            records = records[: args.max_records]
        try:
            x, y, groups, skipped, per_record = mitdb_ml.build_dataset(
                records, scheme=args.labels, seconds=args.seconds, lead=args.lead, local_dir=args.local_dir
            )
        except mitdb_ml.DatasetUnavailable as exc:
            print(
                f"\nMIT-BIH test data unavailable: {exc}\n"
                "Install wfdb / restore internet or use --local-dir, then run:\n"
                "  python3 scripts/evaluate_ml_warning_model.py --source mitdb --split ds1ds2 "
                "--model models/ml_warning_model.pkl",
                file=sys.stderr,
            )
            return 2
        eval_source = f"MIT-BIH DS2 (patient-wise, no leakage), scheme={args.labels}"
        records_used = records
        out_json = args.output_json or "results/ml_mitdb_results.json"
        out_csv = args.output_csv or "results/ml_mitdb_results.csv"
        cm_csv = args.confusion_csv or "results/ml_mitdb_confusion_matrix.csv"

    if x.shape[0] == 0:
        print("\nNo labelled test beats available.", file=sys.stderr)
        return 2

    pred = np.asarray(model.predict(x), dtype=object)
    labels = sorted(set(y.tolist()) | set(pred.tolist()))

    proba = None
    pos_label = None
    if args.labels == "binary" or args.source == "synthetic":
        proba_arr = model.predict_proba(x)
        if proba_arr is not None and "warning_like" in getattr(model.pipeline, "classes_", []):
            classes = list(model.pipeline.classes_)
            pos_label = "warning_like"
            proba = proba_arr[:, classes.index(pos_label)]

    summary = _metrics(y, pred, labels, proba=proba, pos_label=pos_label)
    unstable = min([int(np.sum(y == c)) for c in set(y.tolist())]) < 10
    summary.update({
        "scope": "exploratory_non_diagnostic",
        "evaluation_source": eval_source,
        "split": args.split if args.source == "mitdb" else "n/a",
        "records": records_used,
        "n_samples": int(len(y)),
        "class_counts_test": {c: int(np.sum(y == c)) for c in sorted(set(y.tolist()))},
        "skipped_beats": skipped,
        "per_record": per_record,
        "unstable_small_classes": bool(unstable),
        "note": "Beat-type ML advisory; not a validated arrhythmia diagnosis.",
    })

    _save_outputs(summary, out_json, out_csv, cm_csv)
    printable = {k: v for k, v in summary.items() if k not in {"classification_report", "per_record"}}
    print(json.dumps(printable, indent=2))
    print("\n" + summary["classification_report"])
    print(f"saved_json={out_json}")
    print(f"saved_csv={out_csv}")
    if cm_csv:
        print(f"saved_confusion={cm_csv}")
    if unstable:
        print("WARNING: small class counts — treat metrics as unstable/exploratory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
