from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .detection import BeatMarkers


@dataclass(frozen=True)
class ECGFeatures:
    mean_hr_bpm: float | None
    rr_intervals_s: np.ndarray
    rr_cv: float | None
    qrs_durations_s: np.ndarray
    qt_intervals_s: np.ndarray
    signal_quality: float


def estimate_signal_quality(signal: np.ndarray | list[float]) -> float:
    values = np.asarray(signal, dtype=float)
    if values.size < 3:
        return 0.0
    centered = values - np.median(values)
    noise = np.median(np.abs(np.diff(centered))) + 1e-12
    amplitude = np.percentile(centered, 95) - np.percentile(centered, 5)
    return float(max(0.0, min(1.0, amplitude / (amplitude + 8.0 * noise))))


def extract_features(
    signal: np.ndarray | list[float],
    sampling_rate: float,
    markers: list[BeatMarkers],
) -> ECGFeatures:
    r_peaks = np.asarray([m.r for m in markers], dtype=float)
    rr = np.diff(r_peaks) / sampling_rate if r_peaks.size >= 2 else np.asarray([], dtype=float)
    mean_hr = float(60.0 / np.mean(rr)) if rr.size else None
    rr_cv = float(np.std(rr) / np.mean(rr)) if rr.size and np.mean(rr) > 0 else None

    qrs_durations = []
    qt_intervals = []
    for marker in markers:
        if marker.q is not None and marker.s is not None and marker.s > marker.q:
            qrs_durations.append((marker.s - marker.q) / sampling_rate)
        if marker.q is not None and marker.t is not None and marker.t > marker.q and marker.t_confidence >= 0.35:
            qt_intervals.append((marker.t - marker.q) / sampling_rate)

    return ECGFeatures(
        mean_hr_bpm=mean_hr,
        rr_intervals_s=rr,
        rr_cv=rr_cv,
        qrs_durations_s=np.asarray(qrs_durations, dtype=float),
        qt_intervals_s=np.asarray(qt_intervals, dtype=float),
        signal_quality=estimate_signal_quality(signal),
    )
