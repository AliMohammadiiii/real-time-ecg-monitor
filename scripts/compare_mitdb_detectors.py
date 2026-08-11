"""Compare educational QRS detectors on MIT-BIH records.

The comparison is intentionally simple and reproducible:

* ``current`` uses the production detector from ``ecg_monitor.detection``.
* ``pan_tompkins_baseline`` is a compact Pan-Tompkins-style baseline with a
  fixed threshold.
* ``hamilton_style`` is a conservative slope/energy detector inspired by
  Hamilton-style QRS detection.

This is a detector-selection experiment, not a medical-device validation.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from ecg_monitor import detect_r_peaks
from ecg_monitor.filters import moving_average, preprocess_ecg
from scripts.evaluate_mitdb import _load_wfdb_record, _local_records, aggregate_rows, score_r_peaks


def _mad(values: np.ndarray) -> float:
    return float(np.median(np.abs(values - np.median(values))) + 1e-12)


def _local_maxima(values: np.ndarray, threshold: float, refractory: int) -> np.ndarray:
    peaks: list[int] = []
    last = -refractory
    for i in range(1, values.size - 1):
        if values[i] < threshold or values[i] < values[i - 1] or values[i] < values[i + 1]:
            continue
        if i - last < refractory:
            if peaks and values[i] > values[peaks[-1]]:
                peaks[-1] = i
                last = i
            continue
        peaks.append(i)
        last = i
    return np.asarray(peaks, dtype=int)


def _align_to_display(signal: np.ndarray, rough: np.ndarray, fs: float) -> np.ndarray:
    if rough.size == 0:
        return rough
    display_abs = np.abs(preprocess_ecg(signal, fs).display)
    radius = max(1, int(0.080 * fs))
    aligned: list[int] = []
    for peak in rough:
        start = max(0, int(peak) - radius)
        stop = min(display_abs.size, int(peak) + radius + 1)
        if stop > start:
            aligned.append(start + int(np.argmax(display_abs[start:stop])))
    return np.asarray(aligned, dtype=int)


def pan_tompkins_baseline(signal: np.ndarray, fs: float) -> np.ndarray:
    filtered = preprocess_ecg(signal, fs).qrs
    derivative = np.diff(filtered, prepend=filtered[0])
    energy = moving_average(derivative * derivative, max(1, int(0.150 * fs)))
    threshold = float(np.percentile(energy, 85))
    rough = _local_maxima(energy, threshold, max(1, int(0.200 * fs)))
    return _align_to_display(signal, rough, fs)


def hamilton_style(signal: np.ndarray, fs: float) -> np.ndarray:
    filtered = preprocess_ecg(signal, fs).qrs
    slope = np.abs(np.diff(filtered, prepend=filtered[0]))
    energy = moving_average(slope, max(1, int(0.080 * fs)))
    threshold = float(np.median(energy) + 2.8 * _mad(energy))
    rough = _local_maxima(energy, threshold, max(1, int(0.240 * fs)))
    return _align_to_display(signal, rough, fs)


DETECTORS = {
    "pan_tompkins_baseline": pan_tompkins_baseline,
    "current": detect_r_peaks,
    "hamilton_style": hamilton_style,
}


def evaluate_detector(name: str, records: list[str], seconds: float, tolerance_ms: float, local_dir: str | None) -> tuple[list[dict], dict]:
    detector = DETECTORS[name]
    rows: list[dict] = []
    for record in records:
        signal, fs, annotations = _load_wfdb_record(record, local_dir)
        n = signal.size if seconds == 0 else int(seconds * fs)
        window = np.asarray(signal[:n], dtype=float)
        reference = annotations[annotations < n]
        start_time = time.perf_counter()
        detected = detector(window, fs)
        runtime_s = time.perf_counter() - start_time
        metrics = score_r_peaks(np.asarray(detected, dtype=int), reference, int(tolerance_ms * fs / 1000.0))
        analysed_seconds = float(window.size / fs) if fs else 0.0
        rows.append({
            "detector": name,
            "record": record,
            "fs": fs,
            "seconds": seconds,
            "analysed_seconds": analysed_seconds,
            "detected_r_peaks": int(len(detected)),
            "reference_annotations": int(reference.size),
            **metrics,
            "false_positives_per_minute": float(metrics["fp"] / (analysed_seconds / 60.0)) if analysed_seconds else 0.0,
            "runtime_ms": runtime_s * 1000.0,
            "runtime_ms_per_minute_ecg": runtime_s * 1000.0 / (analysed_seconds / 60.0) if analysed_seconds else None,
        })
    summary = aggregate_rows(rows, worst_records=8)
    summary["detector"] = name
    summary["mean_runtime_ms_per_record"] = float(np.mean([row["runtime_ms"] for row in rows])) if rows else 0.0
    summary["mean_runtime_ms_per_minute_ecg"] = float(np.mean([row["runtime_ms_per_minute_ecg"] for row in rows])) if rows else 0.0
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", nargs="*", help="MIT-BIH record ids")
    parser.add_argument("--all-local", action="store_true", help="Evaluate all local .hea records")
    parser.add_argument("--local-dir", default="data/physionet/mitdb")
    parser.add_argument("--seconds", type=float, default=60.0, help="Duration; 0 = full record")
    parser.add_argument("--tolerance-ms", type=float, default=150.0)
    parser.add_argument("--detectors", nargs="*", choices=sorted(DETECTORS), default=list(DETECTORS))
    parser.add_argument("--out-csv", default="results/mitdb_detector_comparison.csv")
    parser.add_argument("--out-json", default="results/mitdb_detector_comparison.json")
    args = parser.parse_args(argv)

    if args.all_local:
        records = _local_records(args.local_dir)
    else:
        records = args.records or ["100", "101", "106", "113", "117", "207", "208"]

    all_rows: list[dict] = []
    summaries: list[dict] = []
    for name in args.detectors:
        rows, summary = evaluate_detector(name, records, args.seconds, args.tolerance_ms, args.local_dir)
        all_rows.extend(rows)
        summaries.append(summary)
        print(
            f"{name}: Se={summary['sensitivity']:.4f} "
            f"PPV={summary['positive_predictive_value']:.4f} "
            f"F1={summary['f1']:.4f} "
            f"runtime={summary['mean_runtime_ms_per_minute_ecg']:.2f}ms/min"
        )

    out_csv = Path(args.out_csv)
    out_json = Path(args.out_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    with out_json.open("w") as f:
        json.dump({"summaries": summaries, "rows": all_rows}, f, indent=2)
    print(f"saved_csv={out_csv}")
    print(f"saved_json={out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
