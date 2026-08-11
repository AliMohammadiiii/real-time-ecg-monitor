"""Manipulate a real AD8232 recording so it exhibits a chosen arrhythmia.

The point is educational: we keep the *real* beat morphology (a median beat
template extracted from a clean recording) and only change the **rhythm** — the
timing and, for ventricular beats, the QRS width — so the monitor's rule-based
detector reports an elevated arrhythmia risk and names the type. The output is a
valid Arduino/AD8232 packet log (``S,<seq>,<micros>,<adc>,<lo+>,<lo->``) so it
replays in the same live GUI and renders in the same report snapshot.

This is a synthetic manipulation for demonstration/validation only — it is NOT
recorded from a patient with this arrhythmia and is non-diagnostic.

Types
-----
    pvc    Premature ventricular contractions (early + wide + compensatory pause)
    af     Atrial-fibrillation-like (irregularly irregular RR, no clear P)
    tachy  Sinus tachycardia (fast, regular)
    brady  Sinus bradycardia (slow, regular)

Example
-------
    python3 scripts/make_arrhythmia_dataset.py --type pvc \
        --out data/real_ad8232/derived_pvc_ad8232_log.csv
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ecg_monitor.detection import detect_r_peaks  # noqa: E402
from scripts.report_snapshot_common import DEFAULT_LOG, best_window_start, load_log  # noqa: E402

ADC_MIN, ADC_MAX = 0, 1023


def _beat_template(seg: np.ndarray, fs: float) -> tuple[np.ndarray, int, float, int]:
    """Return (template, r_offset, base_level, median_rr) from a clean segment."""
    r = detect_r_peaks(seg, fs, analysis_allowed=True)
    if r.size < 4:
        raise SystemExit("Could not find enough clean beats to build a template.")
    med_rr = int(round(float(np.median(np.diff(r)))))
    pre = int(0.42 * med_rr)
    post = int(0.58 * med_rr)
    beats = [seg[rp - pre: rp + post] for rp in r if rp - pre >= 0 and rp + post < seg.size]
    beats = [b for b in beats if b.size == pre + post]
    template = np.median(np.stack(beats), axis=0)
    base = float(np.median(seg))
    return template, pre, base, med_rr


def _pvc_deviation(length: int, r_off: int, fs: float, amp: float) -> np.ndarray:
    """Synthesize a wide ventricular beat deviation.

    Broad R with distinct deep Q and S troughs near ±60–80 ms so the delineator
    measures a wide (>120 ms) QRS, no P wave, and a discordant (opposite) T.
    """
    x = np.arange(length)

    def g(center_s, width_s):
        return np.exp(-0.5 * ((x - (r_off + center_s * fs)) / (width_s * fs)) ** 2)

    # Sharp R so the QRS detector still fires on it, but Q and S troughs placed
    # far apart (~ -58 ms and +75 ms) so the measured QRS duration is wide.
    dev = 1.30 * amp * g(0.0, 0.016)       # tall, sharp R (detectable)
    dev += -0.55 * amp * g(-0.058, 0.012)  # deep Q trough (~ -58 ms)
    dev += -0.85 * amp * g(0.075, 0.014)   # deep S trough (~ +75 ms)
    dev += -0.32 * amp * g(0.22, 0.10)     # discordant T wave
    return dev


def _place(out: np.ndarray, dev: np.ndarray, r_time: int, r_off: int) -> None:
    start = r_time - r_off
    lo = max(0, start)
    hi = min(out.size, start + dev.size)
    if hi <= lo:
        return
    out[lo:hi] += dev[lo - start: hi - start]


def build(kind: str, seg: np.ndarray, fs: float, duration_s: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    template, r_off, base, med_rr = _beat_template(seg, fs)
    normal_dev = template - base
    tmpl_len = template.size
    r_amp = float(normal_dev[r_off])

    n = int(duration_s * fs)
    out = np.full(n, base, dtype=float)
    out += 6.0 * np.sin(2.0 * np.pi * np.arange(n) / fs / 4.0)  # gentle baseline wander

    # Build the sequence of R times and per-beat morphology.
    r_time = r_off + int(0.2 * fs)
    beat_idx = 0
    while r_time < n - (tmpl_len - r_off):
        is_pvc = False
        if kind == "pvc":
            # Ventricular bigeminy: every other beat is an early, wide PVC
            # followed by a compensatory pause — reliably high risk.
            is_pvc = (beat_idx % 2 == 1)
            if beat_idx == 0:
                rr = med_rr
            elif is_pvc:
                rr = int(0.55 * med_rr)          # premature
            else:
                rr = int(1.45 * med_rr)          # compensatory pause after PVC
        elif kind == "af":
            rr = int(med_rr * float(rng.uniform(0.55, 1.35)))  # irregularly irregular
        elif kind == "tachy":
            rr = int(med_rr * 0.46)              # ~2.2x faster
        elif kind == "brady":
            rr = int(med_rr * 1.65)              # slow
        else:
            raise SystemExit(f"Unknown --type {kind!r}")

        if beat_idx > 0:
            r_time += rr

        if r_time >= n - (tmpl_len - r_off):
            break

        if is_pvc:
            _place(out, _pvc_deviation(tmpl_len, r_off, fs, r_amp), r_time, r_off)
        else:
            dev = normal_dev.copy()
            if kind == "af":  # atrial fibrillation: suppress the P wave
                p_hi = max(0, r_off - int(0.06 * fs))
                dev[:p_hi] *= 0.15
                dev[:p_hi] += rng.normal(0.0, 0.04 * abs(r_amp), size=p_hi)  # fibrillatory baseline
            _place(out, dev, r_time, r_off)
        beat_idx += 1

    out += rng.normal(0.0, 2.2, size=n)  # mild sensor noise
    return np.clip(np.round(out), ADC_MIN, ADC_MAX)


def write_log(adc: np.ndarray, fs: float, path: Path, source_name: str, kind: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dt_us = int(round(1e6 / fs))
    with path.open("w") as f:
        for i, v in enumerate(adc):
            f.write(f"S,{i},{i * dt_us},{int(v)},0,0\n")
    meta = {
        "subject_id": f"derived_{kind}",
        "condition": kind,
        "notes": f"synthetic {kind} rhythm built from real beat morphology of {source_name} (educational, non-diagnostic)",
        "baud": 115200,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "log_file": path.name,
        "packet_format": "S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>",
        "valid_samples": int(adc.size),
        "estimated_sampling_rate_hz": fs,
        "device": "Derived from Arduino + AD8232 recording (educational, non-diagnostic)",
    }
    path.with_name(path.stem.replace("_ad8232_log", "") + "_metadata.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--type", dest="kind", choices=["pvc", "af", "tachy", "brady"], default="pvc")
    p.add_argument("--source", default=str(DEFAULT_LOG), help="Clean real recording to borrow beat morphology from")
    p.add_argument("--out", default=None, help="Output CSV path (default: data/real_ad8232/derived_<type>_ad8232_log.csv)")
    p.add_argument("--fs", type=float, default=250.0)
    p.add_argument("--duration-seconds", type=float, default=24.0)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)

    signal = load_log(args.source, fs=args.fs)
    start = best_window_start(signal, window_seconds=12.0)
    clean = signal.adc[start:start + int(12.0 * args.fs)]

    adc = build(args.kind, clean, args.fs, args.duration_seconds, args.seed)
    out = Path(args.out) if args.out else ROOT / "data" / "real_ad8232" / f"derived_{args.kind}_ad8232_log.csv"
    write_log(adc, args.fs, out, signal.name, args.kind)
    print(f"Wrote {out}  ({adc.size} samples, {adc.size / args.fs:.1f}s, type={args.kind})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
