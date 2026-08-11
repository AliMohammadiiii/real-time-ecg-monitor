from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from ecg_monitor import delineate_pqrst, detect_r_peaks, extract_features, assess_rhythm


def _load_wfdb_record(record: str, local_dir: str | None = None):
    try:
        import wfdb
    except ImportError as exc:
        raise SystemExit("wfdb is required for MIT-BIH evaluation. Install with: pip install -r requirements.txt") from exc

    if local_dir:
        record_path = str(Path(local_dir) / record)
        signals, fields = wfdb.rdsamp(record_path)
        annotations = wfdb.rdann(record_path, "atr")
    else:
        signals, fields = wfdb.rdsamp(record, pn_dir="mitdb")
        annotations = wfdb.rdann(record, "atr", pn_dir="mitdb")
    fs = float(fields["fs"])
    return signals[:, 0], fs, np.asarray(annotations.sample, dtype=int)


def _local_records(local_dir: str) -> list[str]:
    return sorted(path.stem for path in Path(local_dir).glob("*.hea"))


def score_r_peaks(detected: np.ndarray, reference: np.ndarray, tolerance_samples: int) -> dict[str, float]:
    used = np.zeros(reference.size, dtype=bool)
    tp = 0
    timing_errors = []
    for peak in detected:
        if reference.size == 0:
            break
        distances = np.abs(reference - peak)
        nearest = int(np.argmin(distances))
        if distances[nearest] <= tolerance_samples and not used[nearest]:
            used[nearest] = True
            tp += 1
            timing_errors.append(int(peak - reference[nearest]))
    fp = int(detected.size - tp)
    fn = int(reference.size - tp)
    sensitivity = tp / (tp + fn) if tp + fn else 0.0
    ppv = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2.0 * sensitivity * ppv / (sensitivity + ppv) if sensitivity + ppv else 0.0
    abs_errors = np.abs(timing_errors) if timing_errors else np.asarray([], dtype=float)
    mean_abs_error = float(np.mean(abs_errors)) if abs_errors.size else float("nan")
    median_abs_error = float(np.median(abs_errors)) if abs_errors.size else float("nan")
    jitter = float(np.std(timing_errors)) if timing_errors else float("nan")
    return {
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
        "sensitivity": sensitivity,
        "positive_predictive_value": ppv,
        "f1": f1,
        "mean_abs_timing_error_samples": mean_abs_error,
        "median_abs_timing_error_samples": median_abs_error,
        "timing_jitter_samples": jitter,
    }


def aggregate_rows(rows: list[dict], worst_records: int = 8) -> dict:
    """Aggregate per-record MIT-BIH QRS metrics for thesis/report output."""
    total_tp = sum(float(row["tp"]) for row in rows)
    total_fp = sum(float(row["fp"]) for row in rows)
    total_fn = sum(float(row["fn"]) for row in rows)
    sensitivity = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0.0
    ppv = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0.0
    f1 = 2.0 * sensitivity * ppv / (sensitivity + ppv) if sensitivity + ppv else 0.0
    total_minutes = sum(float(row["analysed_seconds"]) for row in rows) / 60.0
    ranked = sorted(
        rows,
        key=lambda row: (float(row["fp"]), 1.0 - float(row["positive_predictive_value"]), float(row["fn"])),
        reverse=True,
    )
    return {
        "records": len(rows),
        "tp": int(total_tp),
        "fp": int(total_fp),
        "fn": int(total_fn),
        "sensitivity": sensitivity,
        "positive_predictive_value": ppv,
        "f1": f1,
        "false_positives_per_minute": total_fp / total_minutes if total_minutes else 0.0,
        "worst_records_by_fp": [
            {
                "record": row["record"],
                "fp": int(float(row["fp"])),
                "fn": int(float(row["fn"])),
                "sensitivity": float(row["sensitivity"]),
                "positive_predictive_value": float(row["positive_predictive_value"]),
                "f1": float(row["f1"]),
            }
            for row in ranked[:worst_records]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="MIT-BIH R-peak smoke evaluation")
    parser.add_argument("--record", default="100", help="MIT-BIH record id, for example 100")
    parser.add_argument("--records", nargs="*", help="Evaluate multiple MIT-BIH record ids")
    parser.add_argument("--seconds", type=float, default=30.0, help="Duration from record start; 0 = whole record")
    parser.add_argument("--tolerance-ms", type=float, default=150.0, help="Matching tolerance")
    parser.add_argument("--refractory-ms", type=float, default=220.0, help="Detector refractory period")
    parser.add_argument("--local-dir", default=None, help="Read MIT-BIH records from a local wfdb.dl_database directory")
    parser.add_argument("--all-local", action="store_true", help="Evaluate all .hea records under --local-dir")
    parser.add_argument("--out-csv", default="results/mitdb_qrs_results.csv", help="CSV results path")
    parser.add_argument("--out-json", default="results/mitdb_qrs_results.json", help="JSON results path")
    parser.add_argument("--summary-json", default="results/mitdb_qrs_summary.json", help="Aggregate summary JSON path")
    parser.add_argument("--worst-records", type=int, default=8, help="Number of high-FP records to include in summary")
    args = parser.parse_args()

    if args.all_local:
        if not args.local_dir:
            raise SystemExit("--all-local requires --local-dir")
        records = _local_records(args.local_dir)
    else:
        records = args.records or [args.record]
    rows = []
    for record in records:
        signal, fs, annotations = _load_wfdb_record(record, args.local_dir)
        n = signal.size if args.seconds == 0 else int(args.seconds * fs)
        signal_window = signal[:n]
        reference = annotations[annotations < n]
        detected = detect_r_peaks(signal_window, fs, refractory_ms=args.refractory_ms)
        metrics = score_r_peaks(detected, reference, int(args.tolerance_ms * fs / 1000.0))
        markers = delineate_pqrst(signal_window, fs, detected)
        features = extract_features(signal_window, fs, markers)
        assessment = assess_rhythm(features)
        analysed_seconds = float(signal_window.size / fs) if fs else 0.0
        row = {
            "record": record,
            "fs": fs,
            "seconds": args.seconds,
            "analysed_seconds": analysed_seconds,
            "refractory_ms": args.refractory_ms,
            "detected_r_peaks": int(detected.size),
            "reference_annotations": int(reference.size),
            **metrics,
            "false_positives_per_minute": float(metrics["fp"] / (analysed_seconds / 60.0)) if analysed_seconds else 0.0,
            "mean_hr_bpm": float(features.mean_hr_bpm) if features.mean_hr_bpm is not None else None,
            "signal_quality": float(features.signal_quality),
            "rhythm_label": assessment.label,
            "reasons": "; ".join(assessment.reasons),
        }
        rows.append(row)

        print(f"record={record} fs={fs:g}Hz seconds={args.seconds:g}")
        print(f"detected_r_peaks={detected.size} reference_annotations={reference.size}")
        for key in ("tp", "fp", "fn", "sensitivity", "positive_predictive_value", "f1", "mean_abs_timing_error_samples", "median_abs_timing_error_samples", "timing_jitter_samples"):
            print(f"{key}={row[key]:.4f}")
        print(f"mean_hr_bpm={features.mean_hr_bpm:.2f}" if features.mean_hr_bpm else "mean_hr_bpm=NA")
        print(f"signal_quality={features.signal_quality:.3f}")
        print(f"rhythm_label={assessment.label}")
        print("reasons=" + "; ".join(assessment.reasons))

    out_csv = Path(args.out_csv)
    out_json = Path(args.out_json)
    summary_json = Path(args.summary_json)
    summary = aggregate_rows(rows, args.worst_records)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with out_json.open("w") as f:
        json.dump(rows, f, indent=2)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    with summary_json.open("w") as f:
        json.dump(summary, f, indent=2)
    print(
        "aggregate: "
        f"records={summary['records']} "
        f"Se={summary['sensitivity']:.4f} "
        f"PPV={summary['positive_predictive_value']:.4f} "
        f"F1={summary['f1']:.4f} "
        f"FP/min={summary['false_positives_per_minute']:.3f}"
    )
    print("worst_records_by_fp=" + ", ".join(
        f"{row['record']}(FP={row['fp']}, PPV={row['positive_predictive_value']:.3f})"
        for row in summary["worst_records_by_fp"]
    ))
    print(f"saved_csv={out_csv}")
    print(f"saved_json={out_json}")
    print(f"saved_summary_json={summary_json}")


if __name__ == "__main__":
    main()
