from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .detection import BeatMarkers
from .features import ECGFeatures


SQI_LEVELS = {
    "unreliable": 0.0,
    "poor": 0.33,
    "usable_for_rate_qrs": 0.66,
    "usable_for_pqrst": 1.0,
}


@dataclass(frozen=True)
class BeatFeatureRow:
    values: tuple[float, ...]
    names: tuple[str, ...]


FEATURE_NAMES = (
    "rr_prev_s",
    "rr_next_s",
    "rr_ratio_to_median",
    "instant_hr_bpm",
    "local_median_hr_bpm",
    "rr_cv",
    "qrs_duration_s",
    "r_amplitude",
    "qrs_energy",
    "sqi_numeric",
    "p_visible",
    "t_visible",
)


def beat_feature_row(
    signal: np.ndarray | list[float],
    sampling_rate: float,
    markers: list[BeatMarkers],
    beat_index: int,
    sqi_level: str = "usable_for_pqrst",
) -> BeatFeatureRow:
    """Build one handcrafted feature row for exploratory ML only."""
    values = np.asarray(signal, dtype=float)
    marker = markers[beat_index]
    r_locations = np.asarray([m.r for m in markers], dtype=float)
    rr = np.diff(r_locations) / sampling_rate if r_locations.size >= 2 else np.asarray([], dtype=float)
    rr_prev = float(rr[beat_index - 1]) if beat_index > 0 and rr.size else 0.0
    rr_next = float(rr[beat_index]) if beat_index < rr.size else 0.0
    median_rr = float(np.median(rr)) if rr.size else 0.0
    rr_ratio = rr_prev / median_rr if median_rr > 0 and rr_prev > 0 else 0.0
    instant_hr = 60.0 / rr_prev if rr_prev > 0 else 0.0
    local_hr = 60.0 / median_rr if median_rr > 0 else 0.0
    rr_cv = float(np.std(rr) / np.mean(rr)) if rr.size and np.mean(rr) > 0 else 0.0
    qrs_duration = (marker.s - marker.q) / sampling_rate if marker.q is not None and marker.s is not None and marker.s > marker.q else 0.0
    start = max(0, marker.r - int(0.06 * sampling_rate))
    stop = min(values.size, marker.r + int(0.08 * sampling_rate))
    segment = values[start:stop] - np.median(values[start:stop]) if stop > start else np.asarray([0.0])
    r_amp = float(values[marker.r] - np.median(values)) if 0 <= marker.r < values.size else 0.0
    qrs_energy = float(np.mean(segment * segment))
    row = (
        rr_prev,
        rr_next,
        rr_ratio,
        instant_hr,
        local_hr,
        rr_cv,
        qrs_duration,
        r_amp,
        qrs_energy,
        SQI_LEVELS.get(sqi_level, 0.0),
        1.0 if marker.p is not None and marker.p_confidence >= 0.40 else 0.0,
        1.0 if marker.t is not None and marker.t_confidence >= 0.40 else 0.0,
    )
    return BeatFeatureRow(values=tuple(float(x) for x in row), names=FEATURE_NAMES)


def feature_matrix_from_markers(
    signal: np.ndarray | list[float],
    sampling_rate: float,
    markers: list[BeatMarkers],
    sqi_level: str = "usable_for_pqrst",
) -> np.ndarray:
    if not markers:
        return np.empty((0, len(FEATURE_NAMES)), dtype=float)
    return np.asarray(
        [beat_feature_row(signal, sampling_rate, markers, i, sqi_level).values for i in range(len(markers))],
        dtype=float,
    )


def feature_vector_from_ecg_features(features: ECGFeatures, sqi_level: str = "usable_for_pqrst") -> np.ndarray:
    rr_prev = float(features.rr_intervals_s[-1]) if features.rr_intervals_s.size else 0.0
    rr_next = 0.0
    median_rr = float(np.median(features.rr_intervals_s)) if features.rr_intervals_s.size else 0.0
    rr_ratio = rr_prev / median_rr if median_rr > 0 and rr_prev > 0 else 0.0
    instant_hr = 60.0 / rr_prev if rr_prev > 0 else 0.0
    local_hr = float(features.mean_hr_bpm or 0.0)
    qrs_duration = float(np.median(features.qrs_durations_s)) if features.qrs_durations_s.size else 0.0
    return np.asarray(
        [
            rr_prev,
            rr_next,
            rr_ratio,
            instant_hr,
            local_hr,
            float(features.rr_cv or 0.0),
            qrs_duration,
            0.0,
            0.0,
            SQI_LEVELS.get(sqi_level, 0.0),
            0.0,
            0.0,
        ],
        dtype=float,
    )
