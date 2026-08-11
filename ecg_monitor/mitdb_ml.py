"""MIT-BIH patient-wise data preparation for the exploratory ML module.

This builds beat-level feature tables from MIT-BIH Arrhythmia Database records
using a **patient-wise** DS1/DS2 split (the standard de Chazal split), so that
no beats from a test patient ever appear in training.

Scope and honesty
-----------------
The ML path is secondary, exploratory, and non-diagnostic. Beat labels come from
the MIT-BIH cardiologist annotations, so this is a beat-type classification
experiment, not a validated arrhythmia diagnosis. Results must be reported as an
"exploratory ML advisory".

Label schemes
-------------
* ``binary``  : ``normal_like`` vs ``warning_like``.
* ``aami``    : the five AAMI classes ``N / S / V / F / Q``.

AAMI symbol mapping (documented):

* N : ``N L R e j``
* S : ``A a J S``
* V : ``V E``
* F : ``F``
* Q : ``/ f Q``

Binary mapping: the N group -> ``normal_like``; the S, V, F groups ->
``warning_like``. The Q group (paced / fusion-with-paced / unclassifiable) is
**skipped** in binary mode because a paced/unknown beat is not a rhythm warning;
it is kept as its own class only in AAMI mode. Non-beat annotations (``+ ~ | "``
etc.) are always skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .detection import delineate_pqrst
from .ml_features import FEATURE_NAMES, feature_matrix_from_markers
from .sqi import assess_signal_quality

# Standard de Chazal patient-wise split.
DS1 = [101, 106, 108, 109, 112, 114, 115, 116, 118, 119, 122, 124,
       201, 203, 205, 207, 208, 209, 215, 220, 223, 230]
DS2 = [100, 103, 105, 111, 113, 117, 121, 123, 200, 202, 210, 212,
       213, 214, 219, 221, 222, 228, 231, 232, 233, 234]

AAMI_GROUPS = {
    "N": set("NLRej"),
    "S": set("AaJS"),
    "V": set("VE"),
    "F": set("F"),
    "Q": set(["/", "f", "Q"]),
}

# All symbols that denote an actual heartbeat (used to pick R-peak locations).
BEAT_SYMBOLS = set().union(*AAMI_GROUPS.values())


class DatasetUnavailable(RuntimeError):
    pass


def aami_class(symbol: str) -> str | None:
    for cls, members in AAMI_GROUPS.items():
        if symbol in members:
            return cls
    return None


def map_label(symbol: str, scheme: str) -> str | None:
    """Map a MIT-BIH annotation symbol to a class label, or None to skip."""
    cls = aami_class(symbol)
    if cls is None:
        return None
    if scheme == "aami":
        return cls
    if scheme == "binary":
        if cls == "N":
            return "normal_like"
        if cls in ("S", "V", "F"):
            return "warning_like"
        return None  # Q group skipped in binary mode
    raise ValueError(f"Unknown label scheme {scheme!r}")


@dataclass
class RecordDataset:
    features: np.ndarray
    labels: np.ndarray
    record: str
    skipped: dict = field(default_factory=dict)


def _load_wfdb(record: str, lead: int, seconds: float, local_dir: str | None):
    import wfdb
    from pathlib import Path

    if local_dir:
        signals, fields = wfdb.rdsamp(str(Path(local_dir) / record))
        ann = wfdb.rdann(str(Path(local_dir) / record), "atr")
    else:
        signals, fields = wfdb.rdsamp(record, pn_dir="mitdb")
        ann = wfdb.rdann(record, "atr", pn_dir="mitdb")
    fs = float(fields["fs"])
    if lead >= signals.shape[1]:
        lead = 0
    signal = signals[:, lead]
    if seconds and seconds > 0:
        signal = signal[: int(seconds * fs)]
    return signal, fs, np.asarray(ann.sample, dtype=int), list(ann.symbol)


def build_record_dataset(
    record: str,
    scheme: str = "binary",
    seconds: float = 60.0,
    lead: int = 0,
    local_dir: str | None = None,
) -> RecordDataset:
    """Build a beat-level feature table + labels for one MIT-BIH record."""
    try:
        import wfdb  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise DatasetUnavailable(
            "wfdb is required for MIT-BIH ML. Install with: pip install -r requirements.txt"
        ) from exc
    try:
        signal, fs, samples, symbols = _load_wfdb(record, lead, seconds, local_dir)
    except DatasetUnavailable:
        raise
    except Exception as exc:
        raise DatasetUnavailable(
            f"Could not load MIT-BIH record {record!r} (needs internet access to "
            f"PhysioNet, or use --local-dir). Underlying error: {exc}"
        ) from exc

    n = signal.size
    # Keep only real beats within the window; these become the R-peaks.
    beats = [(s, sym) for s, sym in zip(samples, symbols) if s < n and sym in BEAT_SYMBOLS]
    skipped = {"non_beat_or_out_of_window": int(len(samples) - len(beats)), "unlabelled_class": 0}
    if not beats:
        return RecordDataset(np.empty((0, len(FEATURE_NAMES))), np.empty((0,), dtype=object), record, skipped)

    r_peaks = np.asarray([s for s, _ in beats], dtype=int)
    beat_symbols = [sym for _, sym in beats]

    # One SQI level for the analysed segment (documented simplification).
    sqi = assess_signal_quality(signal, r_peaks=r_peaks)
    markers = delineate_pqrst(signal, fs, r_peaks, sqi.level)
    # Features are computed over the FULL beat sequence so RR neighbours stay
    # physiological; rows whose label is None are dropped afterwards.
    x_all = feature_matrix_from_markers(signal, fs, markers, sqi.level)

    rows = []
    labels = []
    for i, sym in enumerate(beat_symbols):
        label = map_label(sym, scheme)
        if label is None:
            skipped["unlabelled_class"] += 1
            continue
        if i < x_all.shape[0]:
            rows.append(x_all[i])
            labels.append(label)
    features = np.asarray(rows, dtype=float) if rows else np.empty((0, len(FEATURE_NAMES)))
    return RecordDataset(features, np.asarray(labels, dtype=object), record, skipped)


def build_dataset(
    records,
    scheme: str = "binary",
    seconds: float = 60.0,
    lead: int = 0,
    local_dir: str | None = None,
):
    """Concatenate per-record datasets. Returns (X, y, groups, skipped, per_record)."""
    xs, ys, groups = [], [], []
    total_skipped = {"non_beat_or_out_of_window": 0, "unlabelled_class": 0, "records_failed": 0}
    per_record = {}
    failures = []
    for record in records:
        try:
            ds = build_record_dataset(str(record), scheme, seconds, lead, local_dir)
        except DatasetUnavailable as exc:
            total_skipped["records_failed"] += 1
            failures.append(f"{record}: {exc}")
            continue
        if ds.features.shape[0]:
            xs.append(ds.features)
            ys.append(ds.labels)
            groups.extend([str(record)] * ds.features.shape[0])
        per_record[str(record)] = {
            "n_beats": int(ds.features.shape[0]),
            "skipped": ds.skipped,
        }
        for k in ("non_beat_or_out_of_window", "unlabelled_class"):
            total_skipped[k] += ds.skipped.get(k, 0)
    if not xs:
        if failures:
            raise DatasetUnavailable("; ".join(failures[:3]))
        x = np.empty((0, len(FEATURE_NAMES)))
        y = np.empty((0,), dtype=object)
        return x, y, [], total_skipped, per_record
    x = np.vstack(xs)
    y = np.concatenate(ys)
    return x, y, groups, total_skipped, per_record
