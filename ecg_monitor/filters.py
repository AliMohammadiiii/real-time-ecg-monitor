from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FilteredECG:
    raw: np.ndarray
    display: np.ndarray
    qrs: np.ndarray
    sampling_rate: float


def _as_float_signal(signal: np.ndarray | list[float]) -> np.ndarray:
    values = np.asarray(signal, dtype=float)
    if values.ndim != 1:
        raise ValueError("ECG signal must be one-dimensional")
    if values.size == 0:
        raise ValueError("ECG signal must not be empty")
    return values


def _biquad_filter(signal: np.ndarray, b: tuple[float, float, float], a: tuple[float, float, float]) -> np.ndarray:
    """Apply a causal biquad (direct-form) filter.

    Uses SciPy's vectorised ``lfilter`` when available (orders of magnitude
    faster, which keeps the live GUI and dataset evaluations responsive) and
    falls back to an equivalent pure-Python loop when SciPy is absent. Both paths
    implement the same difference equation, so results are numerically identical.
    """
    signal = np.asarray(signal, dtype=float)
    try:
        from scipy.signal import lfilter

        return lfilter(np.asarray(b, dtype=float), np.asarray(a, dtype=float), signal)
    except Exception:
        y = np.zeros_like(signal, dtype=float)
        x1 = x2 = y1 = y2 = 0.0
        b0, b1, b2 = b
        _, a1, a2 = a
        for i, x0 in enumerate(signal):
            y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            y[i] = y0
            x2, x1 = x1, x0
            y2, y1 = y1, y0
        return y


def _lowpass(signal: np.ndarray, sampling_rate: float, cutoff_hz: float, q: float = 0.707) -> np.ndarray:
    omega = 2.0 * np.pi * cutoff_hz / sampling_rate
    alpha = np.sin(omega) / (2.0 * q)
    cos_w = np.cos(omega)
    b0 = (1.0 - cos_w) / 2.0
    b1 = 1.0 - cos_w
    b2 = (1.0 - cos_w) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w
    a2 = 1.0 - alpha
    return _biquad_filter(signal, (b0 / a0, b1 / a0, b2 / a0), (1.0, a1 / a0, a2 / a0))


def _highpass(signal: np.ndarray, sampling_rate: float, cutoff_hz: float, q: float = 0.707) -> np.ndarray:
    omega = 2.0 * np.pi * cutoff_hz / sampling_rate
    alpha = np.sin(omega) / (2.0 * q)
    cos_w = np.cos(omega)
    b0 = (1.0 + cos_w) / 2.0
    b1 = -(1.0 + cos_w)
    b2 = (1.0 + cos_w) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w
    a2 = 1.0 - alpha
    return _biquad_filter(signal, (b0 / a0, b1 / a0, b2 / a0), (1.0, a1 / a0, a2 / a0))


def notch_filter(signal: np.ndarray | list[float], sampling_rate: float, notch_hz: float = 50.0, q: float = 30.0) -> np.ndarray:
    values = _as_float_signal(signal)
    if notch_hz <= 0 or notch_hz >= sampling_rate / 2.0:
        return values.copy()
    omega = 2.0 * np.pi * notch_hz / sampling_rate
    alpha = np.sin(omega) / (2.0 * q)
    cos_w = np.cos(omega)
    b0 = 1.0
    b1 = -2.0 * cos_w
    b2 = 1.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w
    a2 = 1.0 - alpha
    return _biquad_filter(values, (b0 / a0, b1 / a0, b2 / a0), (1.0, a1 / a0, a2 / a0))


def bandpass_filter(
    signal: np.ndarray | list[float],
    sampling_rate: float,
    low_hz: float,
    high_hz: float,
    passes: int = 1,
) -> np.ndarray:
    values = _as_float_signal(signal)
    if not 0 < low_hz < high_hz < sampling_rate / 2.0:
        raise ValueError("Expected 0 < low_hz < high_hz < Nyquist frequency")
    filtered = values.copy()
    for _ in range(passes):
        filtered = _highpass(filtered, sampling_rate, low_hz)
        filtered = _lowpass(filtered, sampling_rate, high_hz)
    return filtered


def moving_average(signal: np.ndarray | list[float], window_samples: int) -> np.ndarray:
    values = _as_float_signal(signal)
    if window_samples <= 1:
        return values.copy()
    kernel = np.ones(int(window_samples), dtype=float) / float(window_samples)
    return np.convolve(values, kernel, mode="same")


def preprocess_ecg(
    signal: np.ndarray | list[float],
    sampling_rate: float,
    powerline_hz: float = 50.0,
) -> FilteredECG:
    """Prepare ECG for display and QRS detection.

    Display filtering preserves broad ECG morphology. The QRS path deliberately
    emphasizes the 5-15 Hz band used by Pan-Tompkins-style detectors.
    """
    raw = _as_float_signal(signal)
    centered = raw - np.median(raw)
    display = bandpass_filter(centered, sampling_rate, 0.5, 40.0, passes=1)
    display = notch_filter(display, sampling_rate, powerline_hz)
    qrs = bandpass_filter(centered, sampling_rate, 5.0, 15.0, passes=2)
    return FilteredECG(raw=raw, display=display, qrs=qrs, sampling_rate=sampling_rate)
