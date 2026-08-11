from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .features import estimate_signal_quality

SQI_LEVEL_LABELS = {
    "unreliable": "0 - Unreliable",
    "poor": "1 - Poor",
    "usable_for_rate_qrs": "2 - Usable for HR/QRS",
    "usable_for_pqrst": "3 - Usable for tentative PQRST",
}

SQI_LEVEL_DESCRIPTIONS = {
    "unreliable": "Analysis suppressed because lead-off, flatline, clipping, packet loss, or timing instability was detected.",
    "poor": "Waveform is visible but not reliable enough for rhythm warnings or morphology.",
    "usable_for_rate_qrs": "R-peak and heart-rate analysis are usable; P/T morphology is not considered reliable.",
    "usable_for_pqrst": "Signal is clean enough for tentative P/Q/R/S/T markers with confidence labels.",
}


@dataclass(frozen=True)
class SignalQualityAssessment:
    score: float
    level: str
    reasons: tuple[str, ...]
    rate_allowed: bool
    morphology_allowed: bool
    warning_allowed: bool

    @property
    def label(self) -> str:
        return describe_sqi_level(self.level)

    @property
    def description(self) -> str:
        return SQI_LEVEL_DESCRIPTIONS.get(self.level, "Unknown SQI level.")


def describe_sqi_level(level: str) -> str:
    return SQI_LEVEL_LABELS.get(level, f"Unknown SQI level: {level}")


def assess_signal_quality(
    signal: np.ndarray | list[float],
    r_peaks: np.ndarray | None = None,
    lead_off: bool = False,
    adc_min: int | None = None,
    adc_max: int | None = None,
    packet_loss_rate: float = 0.0,
    timing_jitter_ratio: float = 0.0,
) -> SignalQualityAssessment:
    values = np.asarray(signal, dtype=float)
    reasons: list[str] = []
    if values.size < 3:
        return SignalQualityAssessment(0.0, "unreliable", ("too few samples",), False, False, False)

    if lead_off:
        reasons.append("lead-off active")

    if float(np.var(values)) < 1e-8:
        reasons.append("flatline or near-zero variance")

    if adc_min is not None and adc_max is not None:
        clipped = np.mean((values <= adc_min + 2) | (values >= adc_max - 2))
        if clipped > 0.05:
            reasons.append("ADC saturation or clipping")

    if packet_loss_rate >= 0.05:
        reasons.append("severe packet loss")
    elif packet_loss_rate >= 0.01:
        reasons.append("packet loss warning")

    if timing_jitter_ratio >= 0.30:
        reasons.append("impossible or unstable sample timing")
    elif timing_jitter_ratio >= 0.10:
        reasons.append("timing jitter warning")

    if r_peaks is not None and len(r_peaks) >= 3:
        rr = np.diff(np.asarray(r_peaks, dtype=float))
        median_rr = float(np.median(rr))
        if median_rr <= 0:
            reasons.append("invalid RR sequence")

    # A clean ECG still contains sharp QRS slopes, so the roughness proxy should
    # not dominate the simpler amplitude/noise SQI by itself.
    morphology_score = estimate_signal_quality(values)
    spectral_score = _spectral_quality_score(values)
    baseline_wander = _baseline_wander_score(values)
    base_score = max(0.0, min(1.0, 0.75 * morphology_score + 0.25 * spectral_score))
    baseline_penalty = max(0.0, baseline_wander - 0.25)
    base_score *= max(0.0, 1.0 - 0.80 * baseline_penalty)
    hard_reasons = (
        "lead-off active",
        "flatline or near-zero variance",
        "ADC saturation or clipping",
        "severe packet loss",
        "impossible or unstable sample timing",
    )
    if any(reason in reasons for reason in hard_reasons):
        score = min(base_score, 0.10)
    elif reasons:
        score = min(base_score, 0.45)
    else:
        score = base_score

    if score < 0.25:
        level = "unreliable"
        rate_allowed = False
        morphology_allowed = False
        warning_allowed = False
    elif score < 0.45:
        level = "poor"
        rate_allowed = True
        morphology_allowed = False
        warning_allowed = False
    elif score < 0.70:
        level = "usable_for_rate_qrs"
        rate_allowed = True
        morphology_allowed = False
        warning_allowed = True
    else:
        level = "usable_for_pqrst"
        rate_allowed = True
        morphology_allowed = True
        warning_allowed = True

    if not reasons:
        reasons.append("basic SQI checks passed")
    return SignalQualityAssessment(float(score), level, tuple(reasons), rate_allowed, morphology_allowed, warning_allowed)


def _spectral_quality_score(values: np.ndarray) -> float:
    """Lightweight noise proxy based on high-frequency sample-to-sample activity."""
    centered = values - np.median(values)
    amplitude = np.percentile(centered, 95) - np.percentile(centered, 5) + 1e-12
    roughness = np.percentile(np.abs(np.diff(centered)), 95)
    return float(max(0.0, min(1.0, amplitude / (amplitude + 1.5 * roughness))))


def _baseline_wander_score(values: np.ndarray) -> float:
    """Relative slow baseline motion; higher values reduce morphology confidence."""
    centered = values - np.median(values)
    if centered.size < 3:
        return 0.0
    window = max(3, min(centered.size, int(centered.size / 10)))
    if window % 2 == 0:
        window += 1
    kernel = np.ones(window, dtype=float) / float(window)
    baseline = np.convolve(centered, kernel, mode="same")
    total = float(np.std(centered))
    if total < 1e-9:
        return 0.0
    return float(max(0.0, min(1.0, np.std(baseline) / total)))
