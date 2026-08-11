"""Evaluate a recorded AD8232 / Arduino ECG packet log.

Reads a raw CSV log produced by ``scripts/record_ad8232_log.py`` (packet format
``S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>,<checksum>``; checksum is optional
for backward compatibility) and computes acquisition-quality
and signal-analysis metrics: duration, estimated sampling rate, packet loss,
malformed-packet count, timing jitter, lead-off periods, ADC clipping rate,
flatline periods, an SQI timeline, R-peak count, mean HR, and a warning
timeline. Results are saved as CSV + JSON, with optional plots.

Example
-------
    python3 scripts/evaluate_realtime_log.py data/real_ad8232/20260101_120000_ad8232_log.csv
    python3 scripts/evaluate_realtime_log.py tests/fixtures/demo_ad8232_log.csv \
        --ecg-plot results/real_ad8232_ecg_plot.png \
        --sqi-plot results/real_ad8232_sqi_timeline.png
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

from ecg_monitor import assess_rhythm, assess_signal_quality, delineate_pqrst, detect_r_peaks, extract_features
from ecg_monitor.serial_reader import SerialPacketTracker

ADC_MIN = 0
ADC_MAX = 1023


def parse_log(path: Path):
    """Parse a packet log, returning (samples, stats, malformed_count)."""
    tracker = SerialPacketTracker()
    samples = []
    with Path(path).open() as f:
        for line in f:
            if not line.strip():
                continue
            sample = tracker.update_line(line)
            if sample is not None:
                samples.append(sample)
    return samples, tracker.snapshot(), tracker.snapshot().malformed_packets


def find_boolean_periods(flags: np.ndarray, timestamps_s: np.ndarray) -> list[dict]:
    """Return contiguous True runs in ``flags`` as start/end/duration periods."""
    flags = np.asarray(flags, dtype=bool)
    periods: list[dict] = []
    if flags.size == 0:
        return periods
    in_run = False
    start_idx = 0
    for i, flag in enumerate(flags):
        if flag and not in_run:
            in_run = True
            start_idx = i
        elif not flag and in_run:
            in_run = False
            periods.append({
                "start_index": int(start_idx),
                "end_index": int(i - 1),
                "start_s": float(timestamps_s[start_idx]),
                "end_s": float(timestamps_s[i - 1]),
                "duration_s": float(timestamps_s[i - 1] - timestamps_s[start_idx]),
            })
    if in_run:
        periods.append({
            "start_index": int(start_idx),
            "end_index": int(flags.size - 1),
            "start_s": float(timestamps_s[start_idx]),
            "end_s": float(timestamps_s[-1]),
            "duration_s": float(timestamps_s[-1] - timestamps_s[start_idx]),
        })
    return periods


def flatline_periods(adc: np.ndarray, fs: float, window_s: float = 0.5) -> list[dict]:
    """Find contiguous near-zero-variance windows (electrode / cable dropout)."""
    step = max(1, int(window_s * fs))
    flags = np.zeros(adc.size, dtype=bool)
    for start in range(0, adc.size, step):
        segment = adc[start:start + step]
        if segment.size and float(np.var(segment)) < 1e-6:
            flags[start:start + segment.size] = True
    timestamps = np.arange(adc.size) / fs
    return find_boolean_periods(flags, timestamps)


def jitter_stats(intervals_us: list[int]) -> dict:
    """Timing-jitter statistics from inter-sample interval measurements."""
    if not intervals_us:
        return {"mean_interval_us": None, "std_jitter_us": None, "jitter_ratio": None}
    arr = np.asarray(intervals_us, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr))
    return {
        "mean_interval_us": mean,
        "std_jitter_us": std,
        "jitter_ratio": std / mean if mean > 0 else None,
    }


def sqi_timeline(adc: np.ndarray, lead_off_flags: np.ndarray, fs: float, window_s: float = 5.0) -> list[dict]:
    """Compute SQI level and a rule-based warning per window over time."""
    step = max(1, int(window_s * fs))
    timeline: list[dict] = []
    for start in range(0, adc.size, step):
        segment = adc[start:start + step].astype(float)
        if segment.size < step // 2:
            break
        lead_off = bool(np.mean(lead_off_flags[start:start + step]) > 0.1)
        r_peaks = detect_r_peaks(segment, fs, analysis_allowed=not lead_off)
        sqi = assess_signal_quality(
            segment, r_peaks=r_peaks, lead_off=lead_off, adc_min=ADC_MIN, adc_max=ADC_MAX,
        )
        markers = delineate_pqrst(segment, fs, r_peaks, sqi.level)
        features = extract_features(segment, fs, markers)
        assessment = assess_rhythm(features)
        timeline.append({
            "t_start_s": float(start / fs),
            "sqi_level": sqi.level,
            "sqi_score": float(sqi.score),
            "warning_allowed": bool(sqi.warning_allowed),
            "lead_off": lead_off,
            "r_peaks": int(r_peaks.size),
            "mean_hr_bpm": float(features.mean_hr_bpm) if features.mean_hr_bpm is not None else None,
            "rhythm_label": assessment.label,
        })
    return timeline


def evaluate_log(path: Path, window_s: float = 5.0) -> dict:
    samples, stats, malformed = parse_log(path)
    if not samples:
        raise SystemExit(
            f"No valid packets found in {path}. If this is meant to be a real "
            "recording, check the acquisition step; the packet format must be "
            "'S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>'."
        )

    adc = np.asarray([s.adc_value for s in samples], dtype=float)
    lead_off_flags = np.asarray([s.lead_off for s in samples], dtype=bool)
    timestamps_us = np.asarray([s.timestamp_us for s in samples], dtype=float)
    fs = stats.sample_rate_estimate or 250.0
    duration_s = float((timestamps_us[-1] - timestamps_us[0]) / 1e6) if timestamps_us.size >= 2 else 0.0

    intervals = np.diff(timestamps_us)
    intervals = intervals[intervals > 0].astype(int).tolist()
    jitter = jitter_stats(intervals)

    ts_s = (timestamps_us - timestamps_us[0]) / 1e6
    lead_off_period_list = find_boolean_periods(lead_off_flags, ts_s)
    flatline_period_list = flatline_periods(adc, fs)
    clipping_rate = float(np.mean((adc <= ADC_MIN + 1) | (adc >= ADC_MAX - 1)))

    # Whole-record analysis. We only hard-gate detection when the record is
    # *mostly* lead-off; brief dropouts are handled per-window in the timeline.
    lead_off_fraction = float(lead_off_flags.mean())
    mostly_lead_off = lead_off_fraction > 0.5
    r_peaks = detect_r_peaks(adc, fs, analysis_allowed=not mostly_lead_off)
    overall_sqi = assess_signal_quality(
        adc, r_peaks=r_peaks, lead_off=mostly_lead_off, adc_min=ADC_MIN, adc_max=ADC_MAX,
        packet_loss_rate=stats.packet_loss_rate,
        timing_jitter_ratio=jitter["jitter_ratio"] or 0.0,
    )
    markers = delineate_pqrst(adc, fs, r_peaks, overall_sqi.level)
    features = extract_features(adc, fs, markers)
    assessment = assess_rhythm(features)
    # Respect the SQI gate: if the SQI does not permit warnings, suppress the
    # rule-based rhythm label rather than reporting a warning on bad signal.
    if not overall_sqi.warning_allowed:
        rhythm_label = "Poor signal / unreliable analysis (warnings suppressed by SQI)"
        rhythm_reasons = f"SQI level {overall_sqi.level}; " + "; ".join(overall_sqi.reasons)
    else:
        rhythm_label = assessment.label
        rhythm_reasons = "; ".join(assessment.reasons)

    timeline = sqi_timeline(adc, lead_off_flags, fs, window_s)

    summary = {
        "log_file": str(path),
        "valid_samples": stats.valid_samples,
        "malformed_packets": malformed,
        "checksum_errors": stats.checksum_errors,
        "dropped_packets": stats.dropped_packets,
        "packet_loss_rate": stats.packet_loss_rate,
        "duration_s": duration_s,
        "estimated_sampling_rate_hz": fs,
        "mean_interval_us": jitter["mean_interval_us"],
        "timing_jitter_std_us": jitter["std_jitter_us"],
        "timing_jitter_ratio": jitter["jitter_ratio"],
        "adc_clipping_rate": clipping_rate,
        "lead_off_sample_count": int(lead_off_flags.sum()),
        "lead_off_fraction": lead_off_fraction,
        "lead_off_period_count": len(lead_off_period_list),
        "flatline_period_count": len(flatline_period_list),
        "overall_sqi_level": overall_sqi.level,
        "overall_sqi_score": float(overall_sqi.score),
        "overall_sqi_reasons": "; ".join(overall_sqi.reasons),
        "r_peak_count": int(r_peaks.size),
        "mean_hr_bpm": float(features.mean_hr_bpm) if features.mean_hr_bpm is not None else None,
        "rhythm_label": rhythm_label,
        "rhythm_reasons": rhythm_reasons,
        "n_windows": len(timeline),
        "windows_warning_suppressed": sum(1 for w in timeline if not w["warning_allowed"]),
    }
    return {"summary": summary, "lead_off_periods": lead_off_period_list,
            "flatline_periods": flatline_period_list, "sqi_timeline": timeline,
            "_adc": adc, "_fs": fs}


def _save_plots(result: dict, ecg_plot: str | None, sqi_plot: str | None) -> list[str]:
    notes: list[str] = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        return [f"plots skipped: matplotlib unavailable ({exc})"]
    adc = result["_adc"]
    fs = result["_fs"]
    t = np.arange(adc.size) / fs
    if ecg_plot:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.plot(t, adc, lw=0.6)
        ax.set_title("Recorded AD8232 ECG (raw ADC) — educational, non-diagnostic")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("ADC (0-1023)")
        for p in result["lead_off_periods"]:
            ax.axvspan(p["start_s"], p["end_s"], color="red", alpha=0.2)
        fig.tight_layout()
        Path(ecg_plot).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(ecg_plot, dpi=120)
        plt.close(fig)
        notes.append(ecg_plot)
    if sqi_plot:
        timeline = result["sqi_timeline"]
        if timeline:
            ts = [w["t_start_s"] for w in timeline]
            scores = [w["sqi_score"] for w in timeline]
            fig, ax = plt.subplots(figsize=(10, 3))
            ax.step(ts, scores, where="post")
            ax.set_ylim(0, 1)
            ax.set_title("SQI timeline — educational, non-diagnostic")
            ax.set_xlabel("time (s)")
            ax.set_ylabel("SQI score")
            fig.tight_layout()
            Path(sqi_plot).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(sqi_plot, dpi=120)
            plt.close(fig)
            notes.append(sqi_plot)
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", help="Path to an AD8232 packet log CSV")
    parser.add_argument("--window-seconds", type=float, default=5.0, help="SQI/warning timeline window length")
    parser.add_argument("--output-csv", default="results/real_ad8232_log_summary.csv", help="CSV summary path")
    parser.add_argument("--output-json", default="results/real_ad8232_log_summary.json", help="JSON summary path")
    parser.add_argument("--ecg-plot", default=None, help="Optional ECG PNG plot path")
    parser.add_argument("--sqi-plot", default=None, help="Optional SQI-timeline PNG plot path")
    args = parser.parse_args(argv)

    result = evaluate_log(Path(args.log), args.window_seconds)
    summary = result["summary"]

    out_csv = Path(args.output_csv)
    out_json = Path(args.output_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key, value in summary.items():
            writer.writerow([key, value])
    with out_json.open("w") as f:
        json.dump({k: v for k, v in result.items() if not k.startswith("_")}, f, indent=2)

    for key, value in summary.items():
        print(f"{key}={value}")
    print(f"saved_csv={out_csv}")
    print(f"saved_json={out_json}")
    if args.ecg_plot or args.sqi_plot:
        for note in _save_plots(result, args.ecg_plot, args.sqi_plot):
            print(f"plot={note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
