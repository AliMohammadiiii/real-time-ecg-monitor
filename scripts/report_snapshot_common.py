"""Shared helpers for report-quality ECG snapshots (educational, non-diagnostic).

Loads a real AD8232 packet log, then picks the *cleanest* display window so a
screenshot or rendered figure shows the system working on a good-quality,
healthy-looking segment. Used by both the live launcher
(``report_live_demo.py``) and the static renderer (``render_report_snapshot.py``)
so the two always agree on which window they show.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ecg_monitor.gui import LiveAnalysis, analyze_window  # noqa: E402
from scripts.evaluate_realtime_log import parse_log  # noqa: E402

# The real human recording that shows a clean, normal-rhythm segment.
DEFAULT_LOG = ROOT / "data" / "real_ad8232" / "20260704_190653_ad8232_live_log.csv"


@dataclass
class LoadedSignal:
    adc: np.ndarray
    lead_off: np.ndarray
    fs: float
    name: str


def load_log(path: str | Path, fs: float = 250.0) -> LoadedSignal:
    """Parse an AD8232 packet log into ADC and lead-off arrays."""
    path = Path(path)
    samples, _stats, _mal = parse_log(path)
    adc = np.asarray([s.adc_value for s in samples], dtype=float)
    lead_off = np.asarray([1 if s.lead_off else 0 for s in samples], dtype=int)
    if adc.size == 0:
        raise SystemExit(f"No valid samples parsed from {path}")
    return LoadedSignal(adc=adc, lead_off=lead_off, fs=fs, name=path.name)


def best_window_start(
    signal: LoadedSignal,
    window_seconds: float = 10.0,
    step_seconds: float = 1.0,
    prefer_hr_bpm: float = 75.0,
) -> int:
    """Return the start index of the cleanest window.

    Scores windows by signal quality first, then closeness of the estimated
    heart rate to a healthy resting value, so the chosen segment looks good in
    a report screenshot.
    """
    fs = signal.fs
    win = max(1, int(window_seconds * fs))
    step = max(1, int(step_seconds * fs))
    if signal.adc.size <= win:
        return 0
    best_key: tuple[float, float] | None = None
    best_start = 0
    for start in range(0, signal.adc.size - win, step):
        seg = signal.adc[start:start + win]
        lo = bool(signal.lead_off[start:start + win].mean() > 0.1)
        a = analyze_window(seg, fs, lead_off=lo)
        hr_pen = -abs((a.hr_bpm if a.hr_bpm else 200.0) - prefer_hr_bpm)
        key = (round(a.sqi_score, 3), hr_pen)
        if best_key is None or key > best_key:
            best_key = key
            best_start = start
    return best_start


def worst_window_start(
    signal: LoadedSignal,
    window_seconds: float = 10.0,
    step_seconds: float = 0.5,
) -> int:
    """Return the start index of the window that best *shows* an arrhythmia.

    Scores by rule-based risk first (so premature/irregular/wide findings are all
    captured in the frame), then by signal quality as a tie-break so the chosen
    segment is still clean enough to read.
    """
    fs = signal.fs
    win = max(1, int(window_seconds * fs))
    step = max(1, int(step_seconds * fs))
    if signal.adc.size <= win:
        return 0
    best_key: tuple[float, float] | None = None
    best_start = 0
    for start in range(0, signal.adc.size - win, step):
        seg = signal.adc[start:start + win]
        lo = bool(signal.lead_off[start:start + win].mean() > 0.1)
        a = analyze_window(seg, fs, lead_off=lo)
        if a.warning_suppressed:
            continue
        key = (round(a.risk_score, 3), round(a.sqi_score, 3))
        if best_key is None or key > best_key:
            best_key = key
            best_start = start
    return best_start


def analyze_at(signal: LoadedSignal, start: int, window_seconds: float = 10.0) -> tuple[np.ndarray, np.ndarray, LiveAnalysis]:
    """Return (adc_segment, lead_off_segment, analysis) for a window."""
    win = max(1, int(window_seconds * signal.fs))
    seg = signal.adc[start:start + win]
    lo = signal.lead_off[start:start + win]
    analysis = analyze_window(seg, signal.fs, lead_off=bool(lo.mean() > 0.1))
    return seg, lo, analysis
