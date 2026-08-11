"""Evaluate ECG monitor behaviour on labelled scenarios.

Two sources are supported:

* ``--source synthetic``: deterministic labelled waveforms with exact P/Q/R/S/T
  ground truth. This gives the cleanest percentage metrics.
* ``--source serial``: commands ``arduino/ecg_scenario_player`` over Arduino
  serial and evaluates the received stream end-to-end.

This is an educational validation suite, not a medical-device validation.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from ecg_monitor import assess_rhythm, assess_signal_quality, delineate_pqrst, detect_r_peaks, extract_features
from ecg_monitor.serial_reader import SerialPacketTracker


@dataclass(frozen=True)
class Scenario:
    key: str
    command: str
    expected_hr_bpm: float | None
    expected_reasons: tuple[str, ...]
    pqrst_expected: bool = True
    irregular_rr_s: tuple[float, ...] = ()
    bpm: float = 75.0
    p_amp: float = 34.0
    q_amp: float = -42.0
    r_amp: float = 260.0
    s_amp: float = -70.0
    t_amp: float = 82.0
    qrs_width_scale: float = 1.0
    noise_std: float = 3.0
    lead_off: bool = False


SCENARIOS = [
    Scenario("normal_75", "0", 75.0, ()),
    Scenario("brady_45", "1", 45.0, ("bradycardia",), bpm=45.0),
    Scenario("tachy_125", "2", 125.0, ("tachycardia",), bpm=125.0, p_amp=28.0, t_amp=72.0),
    Scenario(
        "irregular_rr", "3", None, ("irregular",),
        irregular_rr_s=(0.45, 1.45, 0.55, 1.35, 0.65, 1.55),
    ),
    Scenario("wide_qrs", "4", 75.0, ("wide",), qrs_width_scale=2.8, r_amp=230.0, s_amp=-60.0),
    Scenario("noisy", "5", 75.0, (), pqrst_expected=False, noise_std=12.0),
    Scenario("lead_off", "6", None, ("unreliable",), pqrst_expected=False, lead_off=True, p_amp=0, q_amp=0, r_amp=0, s_amp=0, t_amp=0),
]

MARKERS = ("p", "q", "r", "s", "t")


def _bump(x: np.ndarray, center: float, width: float) -> np.ndarray:
    return np.exp(-0.5 * ((x - center) / width) ** 2)


def synthetic_scenario(scenario: Scenario, duration_s: float, fs: float, seed: int = 7) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]:
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    values = np.full(n, 512.0)
    t = np.arange(n) / fs
    values += 10.0 * np.sin(2.0 * np.pi * t / 4.0)
    truth = {name: [] for name in MARKERS}
    lead_off = np.full(n, scenario.lead_off, dtype=bool)
    if scenario.lead_off:
        values += rng.normal(0.0, 1.0, size=n)
        return np.clip(values, 0, 1023), {k: np.asarray(v, dtype=int) for k, v in truth.items()}, lead_off

    beat_start = int(0.4 * fs)
    irregular_idx = 0
    while beat_start < n - int(0.4 * fs):
        if scenario.irregular_rr_s:
            rr_s = scenario.irregular_rr_s[irregular_idx % len(scenario.irregular_rr_s)]
            irregular_idx += 1
            rr = int(round(rr_s * fs))
            r_center = beat_start
            centers = {
                "p": r_center - int(round(0.18 * fs)),
                "q": r_center - int(round(0.035 * fs * scenario.qrs_width_scale)),
                "r": r_center,
                "s": r_center + int(round(0.045 * fs * scenario.qrs_width_scale)),
                "t": r_center + int(round(min(0.32 * fs, 0.45 * rr))),
            }
        else:
            rr_s = 60.0 / scenario.bpm
            rr = int(round(rr_s * fs))
            r_center = beat_start + int(round(0.36 * rr))
            centers = {
                "p": beat_start + int(round(0.18 * rr)),
                "q": r_center - int(round(0.030 * rr * scenario.qrs_width_scale)),
                "r": r_center,
                "s": r_center + int(round(0.030 * rr * scenario.qrs_width_scale)),
                "t": beat_start + int(round(0.58 * rr)),
            }
        x = np.arange(n)
        values += scenario.p_amp * _bump(x, centers["p"], max(1.0, 0.030 * rr))
        values += scenario.q_amp * _bump(x, centers["q"], max(1.0, 0.010 * rr * scenario.qrs_width_scale))
        values += scenario.r_amp * _bump(x, centers["r"], max(1.0, 0.008 * rr * scenario.qrs_width_scale))
        values += scenario.s_amp * _bump(x, centers["s"], max(1.0, 0.012 * rr * scenario.qrs_width_scale))
        values += scenario.t_amp * _bump(x, centers["t"], max(1.0, 0.052 * rr))
        for key, center in centers.items():
            if 0 <= center < n:
                truth[key].append(center)
        beat_start += rr

    values += rng.normal(0.0, scenario.noise_std, size=n)
    return np.clip(values, 0, 1023), {k: np.asarray(v, dtype=int) for k, v in truth.items()}, lead_off


def _capture_serial_scenario(port: str, baud: int, scenario: Scenario, duration_s: float, warmup_s: float) -> tuple[np.ndarray, np.ndarray, dict]:
    try:
        import serial
    except ImportError as exc:
        raise SystemExit("pyserial is required for --source serial. Install with: pip install -r requirements.txt") from exc

    tracker = SerialPacketTracker()
    adc: list[float] = []
    lead_off: list[bool] = []
    with serial.Serial(port, baud, timeout=0.2) as ser:
        # Opening an Arduino Uno serial port resets the board; wait until the
        # sketch is running before sending the scenario command.
        time.sleep(2.0)
        if hasattr(ser, "reset_input_buffer"):
            ser.reset_input_buffer()
        ser.write(scenario.command.encode("ascii"))
        ser.write(b"\n")
        ser.flush()
        time.sleep(0.2)
        if hasattr(ser, "reset_input_buffer"):
            ser.reset_input_buffer()
        start = time.monotonic()
        while time.monotonic() - start < duration_s + warmup_s:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").strip()
            if not line or line.startswith("#"):
                continue
            sample = tracker.update_line(line)
            if sample is None:
                continue
            if time.monotonic() - start >= warmup_s:
                adc.append(float(sample.adc_value))
                lead_off.append(sample.lead_off)
    stats = tracker.snapshot()
    meta = {
        "valid_samples": stats.valid_samples,
        "packet_loss_rate": stats.packet_loss_rate,
        "estimated_sampling_rate_hz": stats.sample_rate_estimate,
        "malformed_packets": stats.malformed_packets,
    }
    return np.asarray(adc, dtype=float), np.asarray(lead_off, dtype=bool), meta


def _marker_arrays(markers) -> dict[str, np.ndarray]:
    return {
        "p": np.asarray([m.p for m in markers if m.p is not None], dtype=int),
        "q": np.asarray([m.q for m in markers if m.q is not None], dtype=int),
        "r": np.asarray([m.r for m in markers], dtype=int),
        "s": np.asarray([m.s for m in markers if m.s is not None], dtype=int),
        "t": np.asarray([m.t for m in markers if m.t is not None], dtype=int),
    }


def _match_rate(pred: np.ndarray, ref: np.ndarray, tolerance_samples: int) -> tuple[int, int, int, float, float]:
    used = np.zeros(ref.size, dtype=bool)
    errors = []
    for p in pred:
        if ref.size == 0:
            break
        nearest = int(np.argmin(np.abs(ref - p)))
        if not used[nearest] and abs(int(ref[nearest]) - int(p)) <= tolerance_samples:
            used[nearest] = True
            errors.append(abs(int(ref[nearest]) - int(p)))
    matched = len(errors)
    missing = int(ref.size - matched)
    fp = int(pred.size - matched)
    coverage = matched / ref.size if ref.size else 1.0
    mae = float(np.mean(errors)) if errors else None
    return matched, missing, fp, coverage, mae


def _reason_pass(label: str, reasons: str, expected: tuple[str, ...]) -> bool:
    lower = f"{label}; {reasons}".lower()
    if not expected:
        return "normal rhythm candidate" in lower or "no rule-based warning" in lower
    return all(token in lower for token in expected)


def evaluate_signal(scenario: Scenario, adc: np.ndarray, lead_off_flags: np.ndarray, fs: float, truth: dict[str, np.ndarray] | None, tolerance_ms: float) -> dict:
    mostly_lead_off = bool(lead_off_flags.size and np.mean(lead_off_flags) > 0.5)
    r_peaks = detect_r_peaks(adc, fs, analysis_allowed=not mostly_lead_off)
    sqi = assess_signal_quality(adc, r_peaks=r_peaks, lead_off=mostly_lead_off, adc_min=0, adc_max=1023)
    markers = delineate_pqrst(adc, fs, r_peaks, sqi.level)
    features = extract_features(adc, fs, markers)
    assessment = assess_rhythm(features)
    marker_pred = _marker_arrays(markers)
    if not sqi.warning_allowed:
        rhythm_label = "Poor signal / unreliable analysis (warnings suppressed by SQI)"
        reasons = f"SQI level {sqi.level}; " + "; ".join(sqi.reasons)
    else:
        rhythm_label = assessment.label
        reasons = "; ".join(assessment.reasons)
    hr = features.mean_hr_bpm
    hr_error = abs(hr - scenario.expected_hr_bpm) if hr is not None and scenario.expected_hr_bpm is not None else None
    hr_pass = True if scenario.expected_hr_bpm is None else bool(hr_error is not None and hr_error <= 5.0)
    rhythm_pass = _reason_pass(rhythm_label, reasons, scenario.expected_reasons)

    row = {
        "scenario": scenario.key,
        "samples": int(adc.size),
        "detected_beats": int(marker_pred["r"].size),
        "mean_hr_bpm": float(hr) if hr is not None else None,
        "expected_hr_bpm": scenario.expected_hr_bpm,
        "hr_abs_error_bpm": float(hr_error) if hr_error is not None else None,
        "hr_pass": hr_pass,
        "sqi_level": sqi.level,
        "sqi_score": float(sqi.score),
        "rhythm_label": rhythm_label,
        "rhythm_reasons": reasons,
        "rhythm_pass": rhythm_pass,
        "pqrst_expected": scenario.pqrst_expected,
        "marker_completeness": None,
        "overall_pass": None,
    }

    if truth is not None:
        tolerance_samples = max(1, int(round(tolerance_ms * fs / 1000.0)))
        coverages = []
        maes = []
        scored_markers = MARKERS if scenario.pqrst_expected else ("r",)
        for key in MARKERS:
            matched, missing, fp, coverage, mae = _match_rate(marker_pred[key], truth[key], tolerance_samples)
            row[f"{key}_matched"] = matched
            row[f"{key}_missing"] = missing
            row[f"{key}_false_positive"] = fp
            row[f"{key}_coverage"] = coverage
            row[f"{key}_mae_ms"] = (mae / fs * 1000.0) if mae is not None else None
            if key in scored_markers:
                coverages.append(coverage)
            if mae is not None:
                maes.append(mae / fs * 1000.0)
        row["marker_completeness"] = float(np.mean(coverages)) if coverages else None
        row["pqrst_mae_ms"] = float(np.mean(maes)) if maes else None
    else:
        beat_count = max(1, int(marker_pred["r"].size))
        present = [
            len(marker_pred[key]) / beat_count for key in MARKERS
            if scenario.pqrst_expected or key == "r"
        ]
        row["marker_completeness"] = float(np.mean(present)) if present else 0.0
        errors = []
        for peak in marker_pred["r"]:
            local = adc[max(0, peak - 5):min(adc.size, peak + 6)]
            if local.size:
                errors.append(float(np.max(local) - adc[peak]))
        row["r_local_peak_error_max_adc"] = max(errors) if errors else None

    marker_ok = True
    if scenario.pqrst_expected:
        marker_ok = bool(row["marker_completeness"] is not None and row["marker_completeness"] >= 0.90)
    elif not scenario.lead_off:
        marker_ok = bool(row["marker_completeness"] is not None and row["marker_completeness"] >= 0.90)
    else:
        marker_ok = sqi.level == "unreliable" or marker_pred["r"].size == 0
    row["overall_pass"] = bool(hr_pass and rhythm_pass and marker_ok)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["synthetic", "serial"], default="synthetic")
    parser.add_argument("--port", default=None)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--fs", type=float, default=250.0)
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--warmup", type=float, default=2.0)
    parser.add_argument("--tolerance-ms", type=float, default=80.0)
    parser.add_argument("--output-csv", default="results/scenario_suite_results.csv")
    parser.add_argument("--output-json", default="results/scenario_suite_results.json")
    args = parser.parse_args(argv)

    rows = []
    for i, scenario in enumerate(SCENARIOS):
        if args.source == "synthetic":
            adc, truth, lead_off = synthetic_scenario(scenario, args.duration, args.fs, seed=11 + i)
            row = evaluate_signal(scenario, adc, lead_off, args.fs, truth, args.tolerance_ms)
            row["source"] = "synthetic"
        else:
            if not args.port:
                raise SystemExit("--port is required with --source serial")
            adc, lead_off, meta = _capture_serial_scenario(args.port, args.baud, scenario, args.duration, args.warmup)
            fs = float(meta.get("estimated_sampling_rate_hz") or args.fs)
            row = evaluate_signal(scenario, adc, lead_off, fs, truth=None, tolerance_ms=args.tolerance_ms)
            row.update(meta)
            row["source"] = "serial"
        rows.append(row)
        status = "PASS" if row["overall_pass"] else "FAIL"
        print(
            f"{status} {scenario.key}: HR={row['mean_hr_bpm']} expected={row['expected_hr_bpm']} "
            f"SQI={row['sqi_level']} marker={row['marker_completeness']} "
            f"rhythm={row['rhythm_label']} reasons={row['rhythm_reasons']}"
        )

    pass_rate = sum(1 for row in rows if row["overall_pass"]) / len(rows)
    summary = {
        "source": args.source,
        "n_scenarios": len(rows),
        "scenario_pass_rate": pass_rate,
        "hr_pass_rate": sum(1 for row in rows if row["hr_pass"]) / len(rows),
        "rhythm_pass_rate": sum(1 for row in rows if row["rhythm_pass"]) / len(rows),
        "mean_marker_completeness": float(np.mean([row["marker_completeness"] for row in rows if row["marker_completeness"] is not None])),
    }

    out_csv = Path(args.output_csv)
    out_json = Path(args.output_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    with out_json.open("w") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2)

    print("summary=" + json.dumps(summary, indent=2))
    print(f"saved_csv={out_csv}")
    print(f"saved_json={out_json}")
    return 0 if pass_rate >= 0.80 else 1


if __name__ == "__main__":
    raise SystemExit(main())
