"""NSTDB signal-quality (SQI) noise stress test.

Evaluates how the project's Signal Quality Index (SQI) and rule-based warning
gating behave as noise increases, using the MIT-BIH Noise Stress Test Database
(NSTDB) on PhysioNet.

NSTDB record naming
-------------------
NSTDB adds calibrated noise (baseline wander + muscle artifact + electrode
motion) to clean MIT-BIH records 118 and 119 at fixed signal-to-noise ratios::

    118e24  ->  24 dB SNR (cleanest)
    118e18  ->  18 dB
    118e12  ->  12 dB
    118e06  ->   6 dB
    118e00  ->   0 dB
    118e_6  ->  -6 dB SNR (noisiest)

So a record ladder such as ``118e24 118e12 118e00 118e_6`` is a monotonically
increasing-noise sequence, and we expect SQI to fall and warning suppression to
rise along it.

The script slices each record into fixed windows, computes an SQI level and
detector behaviour per window, aggregates per record, and compares the cleanest
against the noisiest record.

Example
-------
    python3 scripts/evaluate_nstdb_sqi.py --max-records 1 --seconds 60
    python3 scripts/evaluate_nstdb_sqi.py --records 118e24 118e06 118e_6
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

from ecg_monitor import assess_signal_quality, detect_r_peaks
from ecg_monitor.filters import moving_average

SQI_LEVELS = ("unreliable", "poor", "usable_for_rate_qrs", "usable_for_pqrst")

# Default increasing-noise ladder for subject 118.
DEFAULT_RECORDS = ["118e24", "118e18", "118e12", "118e06", "118e00", "118e_6"]


class DatasetUnavailable(RuntimeError):
    pass


def snr_from_record(record: str) -> float | None:
    """Parse the SNR (dB) encoded in an NSTDB record name, e.g. 118e_6 -> -6."""
    if "e" not in record:
        return None
    suffix = record.split("e", 1)[1]
    if not suffix:
        return None
    negative = suffix.startswith("_")
    digits = suffix.lstrip("_")
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def baseline_wander_score(signal: np.ndarray, sampling_rate: float) -> float:
    """Relative low-frequency (<~1 Hz) energy: higher means more baseline drift."""
    values = np.asarray(signal, dtype=float)
    if values.size < 3 or float(np.std(values)) < 1e-9:
        return 0.0
    window = max(1, int(sampling_rate))  # ~1 s moving average isolates baseline
    baseline = moving_average(values - np.median(values), window)
    return float(min(1.0, np.std(baseline) / (np.std(values) + 1e-9)))


def high_frequency_noise_score(signal: np.ndarray) -> float:
    """Relative high-frequency roughness: higher means more HF noise."""
    values = np.asarray(signal, dtype=float)
    if values.size < 3:
        return 0.0
    centered = values - np.median(values)
    amplitude = np.percentile(centered, 95) - np.percentile(centered, 5) + 1e-12
    roughness = np.percentile(np.abs(np.diff(centered)), 95)
    return float(min(1.0, roughness / amplitude))


def rr_plausibility_score(r_peaks: np.ndarray, sampling_rate: float) -> float:
    """Fraction of RR intervals that fall in a physiologically plausible range."""
    r_peaks = np.asarray(r_peaks, dtype=float)
    if r_peaks.size < 3:
        return 0.0
    rr = np.diff(r_peaks) / sampling_rate
    plausible = (rr >= 0.3) & (rr <= 2.0)  # 30-200 bpm
    return float(np.mean(plausible))


def flatline_fraction(signal: np.ndarray, sampling_rate: float, window_s: float = 0.5) -> float:
    """Fraction of short sub-windows that are effectively flat (near-zero variance)."""
    values = np.asarray(signal, dtype=float)
    step = max(1, int(window_s * sampling_rate))
    if values.size < step:
        return 1.0 if float(np.var(values)) < 1e-8 else 0.0
    flat = 0
    total = 0
    for start in range(0, values.size - step + 1, step):
        total += 1
        if float(np.var(values[start:start + step])) < 1e-8:
            flat += 1
    return flat / total if total else 0.0


def evaluate_window(window: np.ndarray, sampling_rate: float) -> dict:
    """Compute SQI level and detector behaviour for one analysis window."""
    r_peaks = detect_r_peaks(window, sampling_rate)
    sqi = assess_signal_quality(window, r_peaks=r_peaks)
    return {
        "sqi_score": sqi.score,
        "sqi_level": sqi.level,
        "warning_allowed": sqi.warning_allowed,
        "morphology_allowed": sqi.morphology_allowed,
        "rate_allowed": sqi.rate_allowed,
        "qrs_count": int(r_peaks.size),
        "baseline_wander_score": baseline_wander_score(window, sampling_rate),
        "hf_noise_score": high_frequency_noise_score(window),
        "rr_plausibility_score": rr_plausibility_score(r_peaks, sampling_rate),
        "flatline_fraction": flatline_fraction(window, sampling_rate),
    }


def _load_nstdb_record(record: str, lead: int, seconds: float, start_seconds: float, local_dir: str | None = None):
    try:
        import wfdb
    except ImportError as exc:  # pragma: no cover
        raise DatasetUnavailable(
            "wfdb is required for NSTDB evaluation. Install with: "
            "pip install -r requirements.txt"
        ) from exc
    try:
        if local_dir:
            signals, fields = wfdb.rdsamp(str(Path(local_dir) / record))
        else:
            signals, fields = wfdb.rdsamp(record, pn_dir="nstdb")
    except Exception as exc:
        raise DatasetUnavailable(
            f"Could not download NSTDB record {record!r} (needs internet access to "
            f"PhysioNet). Underlying error: {exc}"
        ) from exc
    fs = float(fields["fs"])
    if lead >= signals.shape[1]:
        lead = 0
    signal = signals[:, lead]
    start = int(max(0.0, start_seconds) * fs)
    start = min(start, max(0, signal.size - 1))
    signal = signal[start:]
    if seconds and seconds > 0:
        signal = signal[: int(seconds * fs)]
    return signal, fs, start / fs


def evaluate_record(record: str, seconds: float, lead: int, window_seconds: float, start_seconds: float, local_dir: str | None = None) -> dict:
    signal, fs, actual_start_s = _load_nstdb_record(record, lead, seconds, start_seconds, local_dir)
    step = max(1, int(window_seconds * fs))
    windows = []
    for start in range(0, signal.size - step + 1, step):
        windows.append(evaluate_window(signal[start:start + step], fs))
    if not windows:
        windows.append(evaluate_window(signal, fs))

    level_counts = {lvl: 0 for lvl in SQI_LEVELS}
    for w in windows:
        level_counts[w["sqi_level"]] = level_counts.get(w["sqi_level"], 0) + 1
    n = len(windows)
    suppressed = sum(1 for w in windows if not w["warning_allowed"])
    unreliable = sum(1 for w in windows if w["sqi_level"] == "unreliable")

    row = {
        "record": record,
        "snr_db": snr_from_record(record),
        "fs": fs,
        "start_seconds": float(actual_start_s),
        "seconds": float(signal.size / fs),
        "n_windows": n,
        "window_seconds": window_seconds,
        "mean_sqi_score": float(np.mean([w["sqi_score"] for w in windows])),
        "pct_windows_suppressed": suppressed / n,
        "pct_windows_unreliable": unreliable / n,
        "level_unreliable": level_counts["unreliable"],
        "level_poor": level_counts["poor"],
        "level_usable_for_rate_qrs": level_counts["usable_for_rate_qrs"],
        "level_usable_for_pqrst": level_counts["usable_for_pqrst"],
        "total_qrs_detected": int(sum(w["qrs_count"] for w in windows)),
        "mean_baseline_wander_score": float(np.mean([w["baseline_wander_score"] for w in windows])),
        "mean_hf_noise_score": float(np.mean([w["hf_noise_score"] for w in windows])),
        "mean_rr_plausibility_score": float(np.mean([w["rr_plausibility_score"] for w in windows])),
        "mean_flatline_fraction": float(np.mean([w["flatline_fraction"] for w in windows])),
        "warnings_allowed_windows": n - suppressed,
        "warnings_suppressed_windows": suppressed,
    }
    return row


def _degradation_summary(rows: list[dict]) -> dict:
    ordered = [r for r in rows if r["snr_db"] is not None]
    ordered.sort(key=lambda r: r["snr_db"], reverse=True)  # cleanest first
    summary: dict = {"ordered_by_snr": [r["record"] for r in ordered]}
    if len(ordered) >= 2:
        cleanest, noisiest = ordered[0], ordered[-1]
        summary["clean_vs_noisy"] = {
            "clean_record": cleanest["record"],
            "noisy_record": noisiest["record"],
            "clean_mean_sqi": cleanest["mean_sqi_score"],
            "noisy_mean_sqi": noisiest["mean_sqi_score"],
            "sqi_decreased_with_noise": noisiest["mean_sqi_score"] <= cleanest["mean_sqi_score"],
            "clean_pct_suppressed": cleanest["pct_windows_suppressed"],
            "noisy_pct_suppressed": noisiest["pct_windows_suppressed"],
            "suppression_increased_with_noise": noisiest["pct_windows_suppressed"] >= cleanest["pct_windows_suppressed"],
        }
        scores = [r["mean_sqi_score"] for r in ordered]
        # Non-increasing along the cleanest->noisiest order (allow small tolerance).
        summary["sqi_monotonic_non_increasing"] = all(
            scores[i] + 1e-6 >= scores[i + 1] for i in range(len(scores) - 1)
        )
    return summary


def _maybe_plot(rows: list[dict], path: Path) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # matplotlib optional
        return f"plot skipped: matplotlib unavailable ({exc})"
    ordered = [r for r in rows if r["snr_db"] is not None]
    ordered.sort(key=lambda r: r["snr_db"], reverse=True)
    if not ordered:
        return "plot skipped: no SNR-labelled records"
    snr = [r["snr_db"] for r in ordered]
    sqi = [r["mean_sqi_score"] for r in ordered]
    supp = [r["pct_windows_suppressed"] for r in ordered]
    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.plot(snr, sqi, "o-", color="tab:blue", label="mean SQI score")
    ax1.set_xlabel("SNR (dB) — higher is cleaner")
    ax1.set_ylabel("mean SQI score", color="tab:blue")
    ax1.invert_xaxis()  # noisiest on the right
    ax2 = ax1.twinx()
    ax2.plot(snr, supp, "s--", color="tab:red", label="% windows suppressed")
    ax2.set_ylabel("fraction of windows suppressed", color="tab:red")
    fig.suptitle("NSTDB SQI degradation vs noise (educational, non-diagnostic)")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return str(path)


def _print_summary(rows: list[dict], degradation: dict) -> None:
    for r in rows:
        snr = f"{r['snr_db']}dB" if r["snr_db"] is not None else "NA"
        print(f"\n== {r['record']} (SNR={snr}) fs={r['fs']:g} windows={r['n_windows']} ==")
        print(f"  mean_SQI={r['mean_sqi_score']:.3f}  "
              f"suppressed={r['pct_windows_suppressed']:.2%}  "
              f"unreliable={r['pct_windows_unreliable']:.2%}")
        print(f"  levels: unreliable={r['level_unreliable']} poor={r['level_poor']} "
              f"rate_qrs={r['level_usable_for_rate_qrs']} pqrst={r['level_usable_for_pqrst']}")
        print(f"  baseline_wander={r['mean_baseline_wander_score']:.3f} "
              f"hf_noise={r['mean_hf_noise_score']:.3f} "
              f"rr_plausible={r['mean_rr_plausibility_score']:.3f} "
              f"qrs_total={r['total_qrs_detected']}")
    print("\n== degradation summary ==")
    print(json.dumps(degradation, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", nargs="*", help="Explicit NSTDB record names, e.g. 118e24 118e06 118e_6")
    parser.add_argument("--max-records", type=int, default=None, help="Cap number of records from the default ladder")
    parser.add_argument("--seconds", type=float, default=60.0, help="Seconds per record to analyse (0 = to end)")
    parser.add_argument(
        "--start-seconds",
        type=float,
        default=300.0,
        help="Offset into the record where analysis begins. Defaults to 300 s "
             "because NSTDB only adds calibrated noise after the first 5 minutes.",
    )
    parser.add_argument("--lead", type=int, default=0, help="Signal lead index")
    parser.add_argument("--window-seconds", type=float, default=10.0, help="Analysis window length in seconds")
    parser.add_argument(
        "--noise-levels",
        nargs="*",
        help="SNR suffixes to build records from a base subject (e.g. 24 12 00 _6 with --subject 118)",
    )
    parser.add_argument("--subject", default="118", help="Base NSTDB subject for --noise-levels (118 or 119)")
    parser.add_argument(
        "--local-dir",
        default=None,
        help="Read records from a local directory instead of streaming from PhysioNet. "
             "Download once with: python3 -c \"import wfdb; wfdb.dl_database('nstdb', 'DIR')\"",
    )
    parser.add_argument("--output", default="results/nstdb_sqi_results.csv", help="CSV output path")
    parser.add_argument("--json-output", default="results/nstdb_sqi_results.json", help="JSON output path")
    parser.add_argument("--plot-output", default=None, help="Optional PNG plot path")
    args = parser.parse_args(argv)

    if args.records:
        records = args.records
    elif args.noise_levels:
        records = [f"{args.subject}e{lvl}" for lvl in args.noise_levels]
    else:
        records = DEFAULT_RECORDS
    if args.max_records is not None:
        records = records[: args.max_records]

    rows: list[dict] = []
    failures: list[str] = []
    for record in records:
        try:
            rows.append(evaluate_record(record, args.seconds, args.lead, args.window_seconds, args.start_seconds, args.local_dir))
        except DatasetUnavailable as exc:
            failures.append(f"{record}: {exc}")
            print(f"[skip] {record}: {exc}", file=sys.stderr)

    if not rows:
        print(
            "\nNo NSTDB records could be evaluated. This usually means wfdb is not "
            "installed or PhysioNet is unreachable.\n"
            "To run this evaluation after installing deps / restoring internet:\n"
            "  python3 scripts/evaluate_nstdb_sqi.py --max-records 1 --seconds 60",
            file=sys.stderr,
        )
        return 2

    degradation = _degradation_summary(rows)
    _print_summary(rows, degradation)

    out_csv = Path(args.output)
    out_json = Path(args.json_output)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with out_json.open("w") as f:
        json.dump({"records": rows, "degradation": degradation}, f, indent=2)
    print(f"\nsaved_csv={out_csv}")
    print(f"saved_json={out_json}")
    if args.plot_output:
        note = _maybe_plot(rows, Path(args.plot_output))
        print(f"plot={note}")
    if failures:
        print(f"skipped_records={len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
