"""QTDB-style waveform fiducial parsing and matching.

This module supports the QT Database (QTDB) fiducial evaluation. It parses the
WFDB waveform annotation files used by QTDB and matches the predicted P/Q/R/S/T
landmarks produced by ``ecg_monitor.detection`` against the reference markers.

QTDB annotation format (as produced by ``ecgpuwave`` and the manual ``.q1c``
review files) uses a triplet structure per wave::

    (   <peak-symbol>   )

where ``(`` is the wave onset, ``)`` is the wave offset, and the peak symbol is
one of:

* ``p``  -> P-wave peak
* a beat annotation symbol (``N``, ``V``, ``A`` ...) -> QRS peak (R landmark)
* ``t``  -> T-wave peak

Important honesty note
----------------------
QTDB does **not** annotate the Q and S wave peaks as distinct landmarks. It only
annotates the QRS *onset* (the ``(`` before the beat symbol) and the QRS
*offset* (the ``)`` after it). Our detector produces Q and S as local minima
inside the QRS complex, which are different landmarks. Therefore:

* P, R (QRS peak) and T are matched directly against annotated peaks.
* Q and S are compared only against the QRS onset / offset as an explicitly
  labelled *approximate boundary* metric, never as true Q/S peak accuracy.

This mapping is documented so no marker is silently faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# WFDB beat annotation symbols. Any of these, when used as a QTDB "peak"
# symbol, marks the QRS peak (our R landmark).
BEAT_SYMBOLS = frozenset("NLRBAaJSVrFejnEQ?/f")

# Symbols that are not waveform peaks or boundaries and should be counted as
# unmapped (documented, not faked).
_NON_PEAK = frozenset("(!)")


@dataclass(frozen=True)
class ReferenceFiducials:
    """Reference landmarks extracted from a QTDB annotation file."""

    p_peaks: np.ndarray
    qrs_peaks: np.ndarray
    t_peaks: np.ndarray
    qrs_onsets: np.ndarray
    qrs_offsets: np.ndarray
    n_annotations: int
    n_unmapped: int

    @property
    def unmapped_rate(self) -> float:
        return self.n_unmapped / self.n_annotations if self.n_annotations else 0.0


def parse_waveform_annotations(samples, symbols) -> ReferenceFiducials:
    """Parse QTDB/ecgpuwave-style annotations into reference fiducials.

    Parameters
    ----------
    samples:
        Sequence of integer sample indices (``annotation.sample``).
    symbols:
        Sequence of single-character annotation symbols
        (``annotation.symbol``) aligned with ``samples``.

    Returns
    -------
    ReferenceFiducials
        Extracted P/QRS/T peaks plus QRS onsets and offsets.
    """
    samples = list(samples)
    symbols = list(symbols)
    if len(samples) != len(symbols):
        raise ValueError("samples and symbols must have the same length")

    p_peaks: list[int] = []
    qrs_peaks: list[int] = []
    t_peaks: list[int] = []
    qrs_onsets: list[int] = []
    qrs_offsets: list[int] = []

    pending_onset: int | None = None
    last_peak_type: str | None = None
    n_unmapped = 0

    for sample, symbol in zip(samples, symbols):
        sample = int(sample)
        if symbol == "(":
            pending_onset = sample
        elif symbol == ")":
            # Offset for the most recently seen peak.
            if last_peak_type == "qrs":
                qrs_offsets.append(sample)
            last_peak_type = None
            pending_onset = None
        elif symbol == "p":
            p_peaks.append(sample)
            last_peak_type = "p"
            pending_onset = None
        elif symbol == "t":
            t_peaks.append(sample)
            last_peak_type = "t"
            pending_onset = None
        elif symbol in BEAT_SYMBOLS:
            qrs_peaks.append(sample)
            if pending_onset is not None:
                qrs_onsets.append(pending_onset)
            last_peak_type = "qrs"
            pending_onset = None
        else:
            # Unknown / non-fiducial symbol; counted and reported, never faked.
            n_unmapped += 1

    return ReferenceFiducials(
        p_peaks=np.asarray(p_peaks, dtype=int),
        qrs_peaks=np.asarray(qrs_peaks, dtype=int),
        t_peaks=np.asarray(t_peaks, dtype=int),
        qrs_onsets=np.asarray(qrs_onsets, dtype=int),
        qrs_offsets=np.asarray(qrs_offsets, dtype=int),
        n_annotations=len(samples),
        n_unmapped=n_unmapped,
    )


@dataclass(frozen=True)
class MatchResult:
    """One-to-one matching of predicted markers against reference markers."""

    matched: int
    false_positive: int  # predicted markers with no reference match
    missing: int  # reference markers with no predicted match
    signed_errors_samples: np.ndarray = field(default_factory=lambda: np.asarray([], dtype=float))

    @property
    def coverage(self) -> float:
        """Fraction of reference markers that were matched (recall)."""
        denom = self.matched + self.missing
        return self.matched / denom if denom else 0.0

    def abs_errors_samples(self) -> np.ndarray:
        return np.abs(self.signed_errors_samples)


def match_markers(
    predicted,
    reference,
    tolerance_samples: float,
) -> MatchResult:
    """Greedy one-to-one nearest-neighbour matching within a tolerance.

    Each predicted marker is matched to the nearest unused reference marker if
    it lies within ``tolerance_samples``. Returns matched/false-positive/missing
    counts and signed timing errors (predicted - reference) in samples.
    """
    predicted = np.asarray(sorted(int(x) for x in predicted), dtype=int)
    reference = np.asarray(sorted(int(x) for x in reference), dtype=int)

    if reference.size == 0:
        return MatchResult(matched=0, false_positive=int(predicted.size), missing=0)
    if predicted.size == 0:
        return MatchResult(matched=0, false_positive=0, missing=int(reference.size))

    used = np.zeros(reference.size, dtype=bool)
    matched = 0
    errors: list[int] = []
    for peak in predicted:
        distances = np.abs(reference - peak)
        # Prefer the nearest unused reference marker.
        order = np.argsort(distances)
        chosen = None
        for idx in order:
            if distances[idx] > tolerance_samples:
                break
            if not used[idx]:
                chosen = int(idx)
                break
        if chosen is not None:
            used[chosen] = True
            matched += 1
            errors.append(int(peak - reference[chosen]))
    false_positive = int(predicted.size - matched)
    missing = int(reference.size - matched)
    return MatchResult(
        matched=matched,
        false_positive=false_positive,
        missing=missing,
        signed_errors_samples=np.asarray(errors, dtype=float),
    )


def timing_error_stats(errors_samples: np.ndarray, sampling_rate: float) -> dict:
    """Summarise absolute timing errors in samples and milliseconds."""
    errors_samples = np.asarray(errors_samples, dtype=float)
    abs_samples = np.abs(errors_samples)
    if abs_samples.size == 0:
        return {
            "n": 0,
            "mae_samples": None,
            "median_ae_samples": None,
            "std_samples": None,
            "mae_ms": None,
            "median_ae_ms": None,
            "std_ms": None,
        }
    to_ms = 1000.0 / sampling_rate
    return {
        "n": int(abs_samples.size),
        "mae_samples": float(np.mean(abs_samples)),
        "median_ae_samples": float(np.median(abs_samples)),
        "std_samples": float(np.std(errors_samples)),
        "mae_ms": float(np.mean(abs_samples) * to_ms),
        "median_ae_ms": float(np.median(abs_samples) * to_ms),
        "std_ms": float(np.std(errors_samples) * to_ms),
    }
