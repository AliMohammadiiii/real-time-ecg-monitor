from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .features import ECGFeatures


@dataclass(frozen=True)
class RhythmAssessment:
    label: str
    risk_score: float
    reasons: tuple[str, ...]
    arrhythmia_type: str = "Normal sinus rhythm"


def _classify_type(
    *,
    has_brady: bool,
    has_tachy: bool,
    has_irregular: bool,
    has_premature: bool,
    has_wide: bool,
) -> str:
    """Name the most likely rhythm *type* from the detected findings.

    Educational, rule-based, and non-diagnostic. Ordering reflects which
    finding is most specific / clinically salient when several co-occur.
    """
    if has_premature and has_wide:
        return "Premature ventricular contractions (PVC-like)"
    if has_premature:
        return "Premature beats (PVC/PAC-like)"
    if has_irregular and has_tachy:
        return "Atrial-fibrillation-like (irregular, fast)"
    if has_irregular:
        return "Irregular rhythm (AF-like)"
    if has_wide:
        return "Wide-QRS / conduction abnormality"
    if has_tachy:
        return "Sinus tachycardia"
    if has_brady:
        return "Sinus bradycardia"
    return "Normal sinus rhythm"


def assess_rhythm(features: ECGFeatures) -> RhythmAssessment:
    reasons: list[str] = []
    risk = 0.0

    if features.signal_quality < 0.25:
        return RhythmAssessment(
            label="Poor signal / unreliable analysis",
            risk_score=1.0,
            reasons=("Suppressing rhythm warnings because signal quality is too low",),
            arrhythmia_type="Undetermined (poor signal)",
        )

    has_brady = has_tachy = has_irregular = has_premature = has_wide = False

    if features.mean_hr_bpm is not None:
        if features.mean_hr_bpm < 50.0:
            reasons.append("Possible bradycardia")
            risk += min(0.35, (50.0 - features.mean_hr_bpm) / 80.0 + 0.10)
            has_brady = True
        elif features.mean_hr_bpm < 60.0:
            reasons.append("Low heart-rate status")
            risk += min(0.15, (60.0 - features.mean_hr_bpm) / 100.0)
            has_brady = True
        elif features.mean_hr_bpm > 100.0:
            reasons.append("Possible tachycardia")
            risk += min(0.30, (features.mean_hr_bpm - 100.0) / 120.0)
            has_tachy = True

    if features.rr_cv is not None and features.rr_cv > 0.15:
        reasons.append("Irregular RR intervals")
        risk += min(0.30, features.rr_cv)
        has_irregular = True

    if features.rr_intervals_s.size >= 3:
        median_rr = float(np.median(features.rr_intervals_s))
        short_then_pause = False
        for i in range(features.rr_intervals_s.size - 1):
            if features.rr_intervals_s[i] < 0.75 * median_rr and features.rr_intervals_s[i + 1] > 1.20 * median_rr:
                short_then_pause = True
                break
        if short_then_pause:
            reasons.append("Premature-beat suspicion")
            risk += 0.20
            has_premature = True

    if features.signal_quality >= 0.70 and features.qrs_durations_s.size:
        wide_ratio = float((features.qrs_durations_s > 0.120).mean())
        if wide_ratio > 0.25:
            reasons.append("Wide QRS warning")
            risk += min(0.25, wide_ratio * 0.25)
            has_wide = True

    risk = max(0.0, min(1.0, risk))
    arr_type = _classify_type(
        has_brady=has_brady, has_tachy=has_tachy, has_irregular=has_irregular,
        has_premature=has_premature, has_wide=has_wide,
    )
    if not reasons:
        return RhythmAssessment(
            label="Normal rhythm candidate", risk_score=risk,
            reasons=("No rule-based warning",), arrhythmia_type="Normal sinus rhythm",
        )
    if risk >= 0.60:
        label = "High preliminary rhythm warning"
    elif risk >= 0.30:
        label = "Moderate preliminary rhythm warning"
    else:
        label = "Low preliminary rhythm warning"
    return RhythmAssessment(label=label, risk_score=risk, reasons=tuple(reasons), arrhythmia_type=arr_type)
