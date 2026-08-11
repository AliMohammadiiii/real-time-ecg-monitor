from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .filters import moving_average, preprocess_ecg


@dataclass(frozen=True)
class BeatMarkers:
    r: int
    q: int | None
    s: int | None
    p: int | None
    t: int | None
    r_confidence: float = 1.0
    q_confidence: float = 0.0
    s_confidence: float = 0.0
    p_confidence: float = 0.0
    t_confidence: float = 0.0
    qrs_confidence: str = "unavailable"
    p_confidence_level: str = "unavailable"
    t_confidence_level: str = "unavailable"


def _mad(values: np.ndarray) -> float:
    return float(np.median(np.abs(values - np.median(values))) + 1e-12)


def _find_local_maxima(values: np.ndarray, threshold: float, refractory_samples: int) -> list[int]:
    candidates: list[int] = []
    last = -refractory_samples
    for i in range(1, values.size - 1):
        if values[i] < threshold or values[i] < values[i - 1] or values[i] < values[i + 1]:
            continue
        if i - last < refractory_samples:
            if candidates and values[i] > values[candidates[-1]]:
                candidates[-1] = i
                last = i
            continue
        candidates.append(i)
        last = i
    return candidates


def _refine_to_raw_local_extreme(raw: np.ndarray, peak: int, sampling_rate: float) -> int:
    """Move a QRS candidate onto the nearest visible raw ECG extremum."""
    search_radius = max(1, int(0.045 * sampling_rate))
    baseline_radius = max(search_radius + 1, int(0.180 * sampling_rate))
    start = max(0, peak - search_radius)
    stop = min(raw.size, peak + search_radius + 1)
    if stop <= start:
        return int(peak)

    baseline_start = max(0, peak - baseline_radius)
    baseline_stop = min(raw.size, peak + baseline_radius + 1)
    baseline = float(np.median(raw[baseline_start:baseline_stop]))
    local = raw[start:stop] - baseline
    return int(start + np.argmax(np.abs(local)))


def _local_peak_prominence(raw: np.ndarray, peak: int, sampling_rate: float) -> float:
    """Estimate a candidate's local amplitude above the surrounding baseline."""
    peak = int(peak)
    search_radius = max(1, int(0.080 * sampling_rate))
    baseline_radius = max(search_radius + 1, int(0.220 * sampling_rate))
    baseline_start = max(0, peak - baseline_radius)
    baseline_stop = min(raw.size, peak + baseline_radius + 1)
    if baseline_stop <= baseline_start:
        return 0.0
    return abs(float(raw[peak] - np.median(raw[baseline_start:baseline_stop])))


def _suppress_probable_t_wave_detections(
    raw: np.ndarray,
    peaks: list[int],
    sampling_rate: float,
    *,
    max_t_wave_coupling_ms: float = 420.0,
    min_following_pause_ratio: float = 1.35,
    max_relative_prominence: float = 0.75,
) -> list[int]:
    """Remove likely T-wave double detections after an accepted R peak.

    The false-positive pattern seen in several MIT-BIH records is a short
    R-to-candidate interval followed by a longer candidate-to-next-R interval.
    Keeping this as a post-processing pass preserves the main detector while
    making the suppression rule explicit and easy to report.
    """
    if len(peaks) < 3:
        return peaks

    max_coupling = max(1, int(max_t_wave_coupling_ms * sampling_rate / 1000.0))
    keep = np.ones(len(peaks), dtype=bool)
    prominence = np.asarray([_local_peak_prominence(raw, peak, sampling_rate) for peak in peaks], dtype=float)

    for i in range(1, len(peaks) - 1):
        prev_rr = peaks[i] - peaks[i - 1]
        next_rr = peaks[i + 1] - peaks[i]
        if prev_rr <= 0 or next_rr <= 0 or prev_rr > max_coupling:
            continue
        if next_rr < min_following_pause_ratio * prev_rr:
            continue
        previous_prominence = prominence[i - 1] + 1e-12
        relative_prominence = prominence[i] / previous_prominence
        if relative_prominence <= max_relative_prominence:
            keep[i] = False

    return [int(peak) for peak, include in zip(peaks, keep) if include]


def detect_r_peaks(
    signal: np.ndarray | list[float],
    sampling_rate: float,
    refractory_ms: float = 220.0,
    analysis_allowed: bool = True,
) -> np.ndarray:
    """Detect R peaks using a compact Pan-Tompkins-style pipeline."""
    if not analysis_allowed:
        return np.asarray([], dtype=int)
    raw = np.asarray(signal, dtype=float)
    if raw.size < int(0.8 * sampling_rate) or float(np.var(raw)) < 1e-8:
        return np.asarray([], dtype=int)
    filtered = preprocess_ecg(signal, sampling_rate)
    qrs = filtered.qrs
    derivative = np.diff(qrs, prepend=qrs[0])
    integrated = moving_average(derivative * derivative, max(1, int(0.150 * sampling_rate)))
    threshold = float(np.median(integrated) + 1.6 * _mad(integrated))
    refractory = max(1, int(refractory_ms * sampling_rate / 1000.0))
    rough_peaks = _find_local_maxima(integrated, threshold, refractory)

    aligned: list[int] = []
    align_radius = max(1, int(0.080 * sampling_rate))
    display_abs = np.abs(filtered.display)
    for peak in rough_peaks:
        start = max(0, peak - align_radius)
        stop = min(display_abs.size, peak + align_radius + 1)
        if stop <= start:
            continue
        aligned_peak = start + int(np.argmax(display_abs[start:stop]))
        aligned_peak = _refine_to_raw_local_extreme(raw, aligned_peak, sampling_rate)
        if aligned and aligned_peak - aligned[-1] < refractory:
            current_amp = abs(float(raw[aligned_peak] - np.median(raw[start:stop])))
            previous_start = max(0, aligned[-1] - align_radius)
            previous_stop = min(raw.size, aligned[-1] + align_radius + 1)
            previous_amp = abs(float(raw[aligned[-1]] - np.median(raw[previous_start:previous_stop])))
            if current_amp > previous_amp:
                aligned[-1] = aligned_peak
            continue
        aligned.append(aligned_peak)
    aligned = _suppress_probable_t_wave_detections(raw, aligned, sampling_rate)
    return np.asarray(aligned, dtype=int)


def _confidence(signal: np.ndarray, baseline_slice: slice, peak_index: int | None) -> float:
    if peak_index is None:
        return 0.0
    baseline = signal[baseline_slice]
    if baseline.size < 3:
        noise = _mad(signal)
    else:
        noise = _mad(baseline)
    local_amp = abs(float(signal[peak_index] - np.median(baseline if baseline.size else signal)))
    return float(max(0.0, min(1.0, local_amp / (local_amp + 3.0 * noise))))


def confidence_level(score: float) -> str:
    if score >= 0.70:
        return "high"
    if score >= 0.40:
        return "medium"
    if score >= 0.20:
        return "low"
    return "unavailable"


def _adjacent_rr_samples(prev_r: int | None, r: int, next_r: int | None, sampling_rate: float) -> int:
    intervals = []
    if prev_r is not None and r > prev_r:
        intervals.append(r - prev_r)
    if next_r is not None and next_r > r:
        intervals.append(next_r - r)
    if intervals:
        return int(np.median(intervals))
    return int(0.80 * sampling_rate)


def delineate_pqrst(
    signal: np.ndarray | list[float],
    sampling_rate: float,
    r_peaks: np.ndarray | None = None,
    sqi_level: str = "usable_for_pqrst",
) -> list[BeatMarkers]:
    filtered = preprocess_ecg(signal, sampling_rate)
    display = filtered.display
    r_locations = detect_r_peaks(signal, sampling_rate) if r_peaks is None else np.asarray(r_peaks, dtype=int)
    markers: list[BeatMarkers] = []
    n = display.size

    for beat_index, r in enumerate(r_locations):
        prev_r = int(r_locations[beat_index - 1]) if beat_index > 0 else None
        next_index = beat_index + 1
        next_r = int(r_locations[next_index]) if next_index < len(r_locations) else None
        rr_samples = _adjacent_rr_samples(prev_r, int(r), next_r, sampling_rate)
        q_start = max(0, r - int(0.070 * sampling_rate))
        q_stop = max(q_start + 1, r - int(0.010 * sampling_rate))
        s_start = min(n - 1, r + int(0.010 * sampling_rate))
        s_stop = min(n, r + int(0.090 * sampling_rate))
        p_search_back = int(min(0.280 * sampling_rate, 0.45 * rr_samples))
        p_guard = int(max(0.075 * sampling_rate, 0.10 * rr_samples))
        t_guard = int(max(0.105 * sampling_rate, 0.14 * rr_samples))
        t_search_forward = int(min(0.460 * sampling_rate, 0.58 * rr_samples))
        p_start = max(0, r - p_search_back)
        p_stop = max(p_start + 1, r - p_guard)
        t_start = min(n - 1, r + t_guard)
        t_stop = min(n, r + t_search_forward)

        if prev_r is not None:
            p_start = max(p_start, prev_r + int(0.120 * sampling_rate))
        if next_r is not None:
            t_stop = min(t_stop, next_r - int(0.080 * sampling_rate))

        q = q_start + int(np.argmin(display[q_start:q_stop])) if q_stop > q_start else None
        s = s_start + int(np.argmin(display[s_start:s_stop])) if s_stop > s_start else None
        q_conf = _confidence(display, slice(q_start, q_stop), q)
        s_conf = _confidence(display, slice(s_start, s_stop), s)
        rr_long_enough_for_p = rr_samples >= int(0.45 * sampling_rate)
        allow_pt = sqi_level == "usable_for_pqrst" and p_stop > p_start and t_stop > t_start
        allow_p = allow_pt and rr_long_enough_for_p
        p = p_start + int(np.argmax(display[p_start:p_stop])) if allow_p else None
        t = t_start + int(np.argmax(display[t_start:t_stop])) if allow_pt else None
        p_conf = _confidence(display, slice(p_start, p_stop), p)
        t_conf = _confidence(display, slice(t_start, t_stop), t)
        if p_conf < 0.20:
            p = None
        if t_conf < 0.20:
            t = None

        markers.append(
            BeatMarkers(
                r=int(r),
                q=q,
                s=s,
                p=p,
                t=t,
                r_confidence=1.0,
                q_confidence=q_conf,
                s_confidence=s_conf,
                p_confidence=p_conf if p is not None else 0.0,
                t_confidence=t_conf if t is not None else 0.0,
                qrs_confidence=confidence_level(min(q_conf, s_conf)),
                p_confidence_level=confidence_level(p_conf if p is not None else 0.0),
                t_confidence_level=confidence_level(t_conf if t is not None else 0.0),
            )
        )
    return markers
