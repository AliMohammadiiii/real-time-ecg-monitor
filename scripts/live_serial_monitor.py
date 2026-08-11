from __future__ import annotations

import argparse
from collections import deque
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from ecg_monitor import assess_rhythm, assess_signal_quality, delineate_pqrst, detect_r_peaks, extract_features
from ecg_monitor.serial_reader import SerialPacketTracker


def _read_available(ser, tracker: SerialPacketTracker, samples: deque, max_reads: int = 500) -> None:
    reads = 0
    while reads < max_reads:
        waiting = getattr(ser, "in_waiting", 0)
        if waiting <= 0 and reads > 0:
            break
        line = ser.readline().decode(errors="replace")
        if not line:
            break
        sample = tracker.update_line(line)
        if sample is not None:
            samples.append(sample)
        reads += 1


def _analyze(samples: deque, tracker: SerialPacketTracker):
    stats = tracker.snapshot()
    if not samples:
        return stats, None, None, None, None
    adc = np.asarray([s.adc_value for s in samples], dtype=float)
    fs = stats.sample_rate_estimate or 250.0
    lead_off = any(s.lead_off for s in samples)
    r_peaks = detect_r_peaks(adc, fs, analysis_allowed=not lead_off)
    sqi = assess_signal_quality(
        adc,
        r_peaks=r_peaks,
        lead_off=lead_off,
        adc_min=0,
        adc_max=1023,
        packet_loss_rate=stats.packet_loss_rate,
        timing_jitter_ratio=(stats.timing_jitter_us or 0.0) / (stats.mean_interval_us or 1.0),
    )
    markers = delineate_pqrst(adc, fs, r_peaks, sqi.level)
    features = extract_features(adc, fs, markers)
    warning = assess_rhythm(features)
    return stats, adc, markers, features, sqi, warning


def _print_status(stats, markers, features, sqi, warning) -> None:
    hr = "NA" if features is None or features.mean_hr_bpm is None else f"{features.mean_hr_bpm:.1f}"
    qrs_ms = "NA"
    if features is not None and features.qrs_durations_s.size:
        qrs_ms = f"{float(np.median(features.qrs_durations_s)) * 1000:.1f}"
    print(
        " | ".join(
            [
                f"samples={stats.valid_samples}",
                f"fs={(stats.sample_rate_estimate or 0):.2f}Hz",
                f"loss={stats.packet_loss_rate:.4f}",
                f"jitter={(stats.timing_jitter_us or 0):.2f}us",
                f"beats={0 if markers is None else len(markers)}",
                f"HR={hr}",
                f"QRS={qrs_ms}ms",
                f"SQI={sqi.level if sqi else 'NA'}",
                f"warning={warning.label if warning else 'NA'}",
                f"reasons={'; '.join(warning.reasons) if warning else 'NA'}",
            ]
        ),
        flush=True,
    )


def run_no_plot(args) -> None:
    import serial

    tracker = SerialPacketTracker()
    max_samples = int(args.window * args.nominal_fs)
    samples: deque = deque(maxlen=max_samples)
    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        time.sleep(args.reset_wait)
        start = time.time()
        last_print = 0.0
        while args.duration <= 0 or time.time() - start < args.duration:
            _read_available(ser, tracker, samples)
            now = time.time()
            if now - last_print >= args.print_interval:
                stats, adc, markers, features, sqi, warning = _analyze(samples, tracker)
                if adc is not None:
                    _print_status(stats, markers, features, sqi, warning)
                last_print = now


def run_plot(args) -> None:
    import serial
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    tracker = SerialPacketTracker()
    max_samples = int(args.window * args.nominal_fs)
    samples: deque = deque(maxlen=max_samples)
    ser = serial.Serial(args.port, args.baud, timeout=0.05)
    time.sleep(args.reset_wait)

    fig, ax = plt.subplots(figsize=(12, 5))
    (line,) = ax.plot([], [], lw=1.2, color="#1f4e79", label="ECG ADC")
    scatter = ax.scatter([], [], s=35, color="#d62728", label="R")
    fid_scatter = ax.scatter([], [], s=22, color="#2ca02c", label="P/Q/S/T")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("ADC")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right")
    last_console = {"time": 0.0}

    def update(_frame):
        _read_available(ser, tracker, samples)
        stats, adc, markers, features, sqi, warning = _analyze(samples, tracker)
        if adc is None:
            return line, scatter, fid_scatter
        fs = stats.sample_rate_estimate or args.nominal_fs
        t = np.arange(adc.size) / fs
        line.set_data(t, adc)
        ax.set_xlim(max(0, t[-1] - args.window), max(args.window, t[-1]))
        margin = max(20.0, float(np.ptp(adc)) * 0.15)
        ax.set_ylim(float(np.min(adc)) - margin, float(np.max(adc)) + margin)

        r_x, r_y = [], []
        f_x, f_y = [], []
        for marker in markers[-20:]:
            if 0 <= marker.r < adc.size:
                r_x.append(marker.r / fs)
                r_y.append(adc[marker.r])
            for idx in (marker.p, marker.q, marker.s, marker.t):
                if idx is not None and 0 <= int(idx) < adc.size:
                    f_x.append(int(idx) / fs)
                    f_y.append(adc[int(idx)])
        scatter.set_offsets(np.c_[r_x, r_y] if r_x else np.empty((0, 2)))
        fid_scatter.set_offsets(np.c_[f_x, f_y] if f_x else np.empty((0, 2)))

        hr = "NA" if features.mean_hr_bpm is None else f"{features.mean_hr_bpm:.1f}"
        ax.set_title(
            f"Live ECG simulator | HR={hr} bpm | SQI={sqi.level} ({sqi.score:.2f}) | "
            f"{warning.label}: {'; '.join(warning.reasons)}"
        )
        now = time.time()
        if now - last_console["time"] >= args.print_interval:
            _print_status(stats, markers, features, sqi, warning)
            last_console["time"] = now
        return line, scatter, fid_scatter

    try:
        FuncAnimation(fig, update, interval=args.update_ms, blit=False, cache_frame_data=False)
        plt.show()
    finally:
        ser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Live serial ECG monitor with plot and e2e pipeline output")
    parser.add_argument("--port", default="/dev/cu.usbmodem1401")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--window", type=float, default=8.0, help="Plot/analysis window in seconds")
    parser.add_argument("--nominal-fs", type=float, default=250.0)
    parser.add_argument("--duration", type=float, default=0.0, help="Seconds to run; 0 means until window closed/Ctrl+C")
    parser.add_argument("--update-ms", type=int, default=200)
    parser.add_argument("--print-interval", type=float, default=1.0)
    parser.add_argument("--reset-wait", type=float, default=2.0, help="Seconds to wait after opening serial")
    parser.add_argument("--no-plot", action="store_true", help="Run console-only e2e monitor")
    args = parser.parse_args()

    if args.no_plot:
        run_no_plot(args)
    else:
        run_plot(args)


if __name__ == "__main__":
    main()
