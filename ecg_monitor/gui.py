"""Live ECG GUI for the educational monitoring prototype.

The heavy PyQtGraph/PyQt import is done lazily so that importing this module (and
the rest of the package) never fails when GUI dependencies are absent. The data
source and per-window analysis are plain NumPy code and are unit-tested without
any GUI.

Safety: the GUI always shows "Educational prototype — not a medical device.",
and when the SQI is poor/unreliable it shows
"Signal unreliable; rhythm warnings suppressed." instead of a rhythm warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .arrhythmia import assess_rhythm
from .detection import BeatMarkers, delineate_pqrst, detect_r_peaks
from .features import extract_features
from .filters import preprocess_ecg
from .sqi import assess_signal_quality, describe_sqi_level
from .synthetic import synthetic_ecg

SAFETY_TEXT = "Educational prototype — not a medical device."
SUPPRESSED_TEXT = "Signal unreliable; rhythm warnings suppressed."


def pyqtgraph_available() -> bool:
    """Return True if PyQtGraph and a Qt binding can be imported."""
    try:
        import pyqtgraph  # noqa: F401
        from pyqtgraph.Qt import QtWidgets  # noqa: F401
        return True
    except Exception:
        return False


INSTALL_MESSAGE = (
    "PyQtGraph and a Qt binding are required for the live GUI but are not "
    "installed.\nInstall them with, for example:\n"
    "    .venv/bin/python -m pip install pyqtgraph PyQt5\n"
    "The rest of the project (evaluation scripts, tests) works without the GUI."
)


@dataclass
class ChunkResult:
    """One streamed chunk of samples plus link-quality flags."""

    samples: np.ndarray
    lead_off: bool = False
    packet_loss_rate: float = 0.0


@dataclass
class DemoSignalSource:
    """Synthetic ECG source so the GUI runs without an Arduino."""

    fs: float = 250.0
    heart_rate_bpm: float = 72.0
    chunk_seconds: float = 0.2
    noise_std: float = 0.02
    seed: int = 7
    _buffer: np.ndarray = field(default_factory=lambda: np.asarray([]), init=False)
    _pos: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        signal, _ = synthetic_ecg(
            duration_s=60.0, sampling_rate=self.fs,
            heart_rate_bpm=self.heart_rate_bpm, noise_std=self.noise_std, seed=self.seed,
        )
        # Map to a 10-bit ADC-like range so the display matches hardware units.
        self._buffer = np.clip(np.round(512 + signal * 300), 0, 1023).astype(float)

    def read_chunk(self) -> ChunkResult:
        n = max(1, int(self.chunk_seconds * self.fs))
        if self._buffer.size == 0:
            return ChunkResult(samples=np.zeros(n))
        idx = (self._pos + np.arange(n)) % self._buffer.size
        self._pos = int((self._pos + n) % self._buffer.size)
        return ChunkResult(samples=self._buffer[idx].copy(), lead_off=False, packet_loss_rate=0.0)


@dataclass
class DatasetReplaySource:
    """Replay a fixed ECG sample array as if it were a live stream."""

    samples: np.ndarray
    fs: float = 250.0
    chunk_seconds: float = 0.2
    lead_off_flags: np.ndarray | None = None
    name: str = "dataset replay"
    loop: bool = True
    _pos: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.samples = np.asarray(self.samples, dtype=float)
        if self.samples.size == 0:
            self.samples = np.zeros(max(1, int(self.fs)), dtype=float)
        if self.lead_off_flags is not None:
            flags = np.asarray(self.lead_off_flags, dtype=bool)
            if flags.size != self.samples.size:
                flags = np.zeros(self.samples.size, dtype=bool)
            self.lead_off_flags = flags

    def read_chunk(self) -> ChunkResult:
        n = max(1, int(self.chunk_seconds * self.fs))
        if self.loop:
            idx = (self._pos + np.arange(n)) % self.samples.size
            self._pos = int((self._pos + n) % self.samples.size)
            flags = self.lead_off_flags[idx] if self.lead_off_flags is not None else np.zeros(n, dtype=bool)
            return ChunkResult(samples=self.samples[idx].copy(), lead_off=bool(np.mean(flags) > 0.1))
        start = self._pos
        stop = min(self.samples.size, self._pos + n)
        self._pos = stop
        chunk = self.samples[start:stop]
        if chunk.size < n:
            fill = float(chunk[-1]) if chunk.size else float(self.samples[-1])
            chunk = np.pad(chunk, (0, n - chunk.size), mode="constant", constant_values=fill)
        flags = self.lead_off_flags[start:stop] if self.lead_off_flags is not None else np.zeros(stop - start, dtype=bool)
        return ChunkResult(samples=chunk.copy(), lead_off=bool(flags.size and np.mean(flags) > 0.1))

    def current_scenario_info(self) -> dict:
        return {
            "mode": "Dataset replay",
            "scenario": self.name,
            "expected": "Replay waveform; validate markers, SQI, warnings, and latency.",
        }


@dataclass
class LiveAnalysis:
    """Result of analysing the current display window."""

    r_peaks: np.ndarray
    markers: list[BeatMarkers]
    hr_bpm: float | None
    sqi_level: str
    sqi_score: float
    sqi_label: str
    sqi_description: str
    morphology_allowed: bool
    lead_off: bool
    packet_loss_rate: float
    warning_label: str
    warning_suppressed: bool
    ml_advisory: str | None = None
    risk_score: float = 0.0
    risk_reasons: tuple[str, ...] = ()
    arrhythmia_type: str = "Normal sinus rhythm"


def analyze_window(
    buffer: np.ndarray | list[float],
    fs: float,
    lead_off: bool = False,
    packet_loss_rate: float = 0.0,
    ml_model=None,
) -> LiveAnalysis:
    """Analyse one display window: detection, SQI, warnings, optional ML advisory.

    Handles short/empty buffers and poor SQI gracefully (empty detections,
    suppressed warnings).
    """
    values = np.asarray(buffer, dtype=float)
    if values.size < int(0.8 * fs) or float(np.var(values)) < 1e-9:
        return LiveAnalysis(
            r_peaks=np.asarray([], dtype=int), markers=[], hr_bpm=None,
            sqi_level="unreliable", sqi_score=0.0,
            sqi_label=describe_sqi_level("unreliable"),
            sqi_description="Too few samples or flatline; analysis suppressed.",
            morphology_allowed=False,
            lead_off=lead_off,
            packet_loss_rate=packet_loss_rate, warning_label=SUPPRESSED_TEXT,
            warning_suppressed=True, ml_advisory=None,
            risk_score=0.0, risk_reasons=(),
            arrhythmia_type="Undetermined (poor signal)",
        )

    r_peaks = detect_r_peaks(values, fs, analysis_allowed=not lead_off)
    sqi = assess_signal_quality(
        values, r_peaks=r_peaks, lead_off=lead_off,
        adc_min=0, adc_max=1023, packet_loss_rate=packet_loss_rate,
    )
    markers = delineate_pqrst(values, fs, r_peaks, sqi.level)
    features = extract_features(values, fs, markers)
    assessment = assess_rhythm(features)

    if not sqi.warning_allowed:
        warning_label = SUPPRESSED_TEXT
        suppressed = True
    else:
        warning_label = assessment.label
        suppressed = False

    ml_advisory = _ml_advisory(values, fs, markers, sqi, ml_model)

    return LiveAnalysis(
        r_peaks=r_peaks, markers=markers, hr_bpm=features.mean_hr_bpm,
        sqi_level=sqi.level, sqi_score=float(sqi.score),
        sqi_label=sqi.label, sqi_description=sqi.description,
        morphology_allowed=sqi.morphology_allowed, lead_off=lead_off,
        packet_loss_rate=packet_loss_rate, warning_label=warning_label,
        warning_suppressed=suppressed, ml_advisory=ml_advisory,
        risk_score=float(assessment.risk_score),
        risk_reasons=tuple(assessment.reasons),
        arrhythmia_type=assessment.arrhythmia_type,
    )


def display_waveform(values: np.ndarray | list[float], fs: float) -> np.ndarray:
    """Return the filtered waveform used by the GUI display.

    Recording stays raw; this only improves the live view by removing slow
    baseline drift and power-line/high-frequency clutter.
    """
    samples = np.asarray(values, dtype=float)
    if samples.size < 8:
        return samples.copy()
    filtered = preprocess_ecg(samples, fs).display
    if filtered.size >= 5:
        kernel = np.ones(5, dtype=float) / 5.0
        filtered = np.convolve(filtered, kernel, mode="same")
    return filtered


def _ml_advisory(values, fs, markers, sqi, ml_model) -> str | None:
    """Optional exploratory ML advisory; suppressed when SQI is poor."""
    if ml_model is None or not markers or not sqi.warning_allowed:
        return None
    try:
        from .ml_features import feature_matrix_from_markers

        x = feature_matrix_from_markers(values, fs, markers, sqi.level)
        pred = ml_model.predict(x, sqi_level=sqi.level)
        pred = np.asarray(pred, dtype=object)
        if pred.size == 0 or np.all(pred == "suppressed_low_sqi"):
            return None
        warning_like = int(np.sum(pred == "warning_like"))
        return f"exploratory ML advisory: {warning_like}/{pred.size} beats warning-like (non-diagnostic)"
    except Exception:
        return None


def _relative_marker_indices(marker_indices_abs: np.ndarray, buffer_start_abs: int, buffer_size: int) -> np.ndarray:
    """Map absolute sample indices into the current scrolling display buffer."""
    marker_indices_abs = np.asarray(marker_indices_abs, dtype=int)
    if marker_indices_abs.size == 0 or buffer_size <= 0:
        return np.asarray([], dtype=int)
    relative = marker_indices_abs - int(buffer_start_abs)
    return relative[(0 <= relative) & (relative < buffer_size)]


# ---------------------------------------------------------------------------
# Visual theme for the live dashboard (dark "clinical monitor" aesthetic).
# ---------------------------------------------------------------------------
THEME = {
    "bg": "#0b111e",
    "panel": "#131c31",
    "card": "#182238",
    "card_border": "#273450",
    "text": "#e8eef8",
    "muted": "#8a99b5",
    "faint": "#5b6b88",
    "trace": "#39e0a6",
    "grid": "#22314e",
    "accent": "#22d3ee",
    "ok": "#34d399",
    "warn": "#fbbf24",
    "bad": "#f87171",
    "P": "#34d399",
    "Q": "#fbbf24",
    "R": "#f472b6",
    "S": "#fb923c",
    "T": "#a78bfa",
}


_SHORT_ARR_TYPE = {
    "Premature ventricular contractions (PVC-like)": "PVC (ventricular ectopy)",
    "Premature beats (PVC/PAC-like)": "Premature beats",
    "Atrial-fibrillation-like (irregular, fast)": "AF-like (fast)",
    "Irregular rhythm (AF-like)": "Irregular (AF-like)",
    "Wide-QRS / conduction abnormality": "Wide-QRS",
    "Sinus tachycardia": "Tachycardia",
    "Sinus bradycardia": "Bradycardia",
}


def _short_arr_type(t: str) -> str:
    return _SHORT_ARR_TYPE.get(t, t)


def _risk_color(score: float, suppressed: bool) -> str:
    if suppressed:
        return THEME["faint"]
    if score >= 0.60:
        return THEME["bad"]
    if score >= 0.30:
        return THEME["warn"]
    return THEME["ok"]


def _risk_word(score: float, suppressed: bool) -> str:
    if suppressed:
        return "SUPPRESSED"
    if score >= 0.60:
        return "HIGH"
    if score >= 0.30:
        return "MODERATE"
    return "LOW"


def _dashboard_stylesheet() -> str:
    t = THEME
    return f"""
    QWidget#Root {{ background: {t['bg']}; }}
    QLabel {{ color: {t['text']}; font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial; }}
    QFrame#Card {{
        background: {t['card']};
        border: 1px solid {t['card_border']};
        border-radius: 14px;
    }}
    QFrame#Header {{
        background: {t['panel']};
        border: 1px solid {t['card_border']};
        border-radius: 14px;
    }}
    QFrame#Footer {{
        background: {t['panel']};
        border: 1px solid {t['card_border']};
        border-radius: 14px;
    }}
    QLabel#Title {{ font-size: 20px; font-weight: 700; color: {t['text']}; }}
    QLabel#Subtitle {{ font-size: 12px; color: {t['muted']}; }}
    QLabel#Pill {{
        font-size: 12px; font-weight: 700; color: #201400;
        background: {t['warn']}; border-radius: 11px; padding: 5px 12px;
    }}
    QLabel#CardTitle {{ font-size: 11px; font-weight: 700; letter-spacing: 1px; color: {t['muted']}; }}
    QLabel#CardValue {{ font-size: 40px; font-weight: 800; color: {t['text']}; }}
    QLabel#CardUnit {{ font-size: 13px; color: {t['muted']}; }}
    QLabel#CardSub {{ font-size: 12px; color: {t['muted']}; }}
    QLabel#Foot {{ font-size: 12px; color: {t['muted']}; }}
    """


def run_gui(source, fs: float, window_seconds: float = 10.0, ml_model=None, log_output=None) -> int:
    """Launch the live GUI. Returns an exit code; requires PyQtGraph.

    ``source`` must provide ``read_chunk() -> ChunkResult``.

    The dashboard uses a dark clinical-monitor theme with KPI cards (heart
    rate, arrhythmia risk, signal quality, detected beats), a scrolling ECG
    trace with PQRST markers, and an always-visible safety banner.
    """
    if not pyqtgraph_available():
        print(INSTALL_MESSAGE)
        return 1

    import time

    import pyqtgraph as pg
    from pyqtgraph.Qt import QtCore, QtWidgets

    pg.setConfigOptions(antialias=True)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = QtWidgets.QWidget()
    win.setObjectName("Root")
    win.setWindowTitle("Live ECG — educational prototype (not a medical device)")
    win.setStyleSheet(_dashboard_stylesheet())

    root = QtWidgets.QVBoxLayout(win)
    root.setContentsMargins(16, 16, 16, 16)
    root.setSpacing(12)

    # ---- Header -----------------------------------------------------------
    header = QtWidgets.QFrame()
    header.setObjectName("Header")
    hlay = QtWidgets.QHBoxLayout(header)
    hlay.setContentsMargins(18, 12, 18, 12)
    title_box = QtWidgets.QVBoxLayout()
    title_box.setSpacing(2)
    title = QtWidgets.QLabel("ECG Live Monitor")
    title.setObjectName("Title")
    subtitle = QtWidgets.QLabel("Arduino + AD8232  ·  real-time rhythm screening")
    subtitle.setObjectName("Subtitle")
    title_box.addWidget(title)
    title_box.addWidget(subtitle)
    hlay.addLayout(title_box)
    hlay.addStretch(1)
    safety = QtWidgets.QLabel(SAFETY_TEXT)
    safety.setObjectName("Pill")
    hlay.addWidget(safety, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
    root.addWidget(header)

    # ---- KPI cards --------------------------------------------------------
    def make_card(card_title: str):
        frame = QtWidgets.QFrame()
        frame.setObjectName("Card")
        box = QtWidgets.QVBoxLayout(frame)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(2)
        cap = QtWidgets.QLabel(card_title)
        cap.setObjectName("CardTitle")
        box.addWidget(cap)
        return frame, box

    cards = QtWidgets.QHBoxLayout()
    cards.setSpacing(12)

    # Heart-rate card
    hr_card, hr_box = make_card("HEART RATE")
    hr_row = QtWidgets.QHBoxLayout()
    hr_row.setSpacing(6)
    hr_value = QtWidgets.QLabel("--")
    hr_value.setObjectName("CardValue")
    hr_unit = QtWidgets.QLabel("bpm")
    hr_unit.setObjectName("CardUnit")
    hr_row.addWidget(hr_value)
    hr_row.addWidget(hr_unit, alignment=QtCore.Qt.AlignmentFlag.AlignBottom)
    hr_row.addStretch(1)
    hr_box.addLayout(hr_row)
    hr_sub = QtWidgets.QLabel("waiting for beats…")
    hr_sub.setObjectName("CardSub")
    hr_box.addWidget(hr_sub)
    cards.addWidget(hr_card, 1)

    # Arrhythmia-risk card
    risk_card, risk_box = make_card("ARRHYTHMIA RISK")
    risk_row = QtWidgets.QHBoxLayout()
    risk_row.setSpacing(8)
    risk_value = QtWidgets.QLabel("--")
    risk_value.setObjectName("CardValue")
    risk_word = QtWidgets.QLabel("")
    risk_word.setStyleSheet("font-size: 13px; font-weight: 700;")
    risk_row.addWidget(risk_value)
    risk_row.addWidget(risk_word, alignment=QtCore.Qt.AlignmentFlag.AlignBottom)
    risk_row.addStretch(1)
    risk_box.addLayout(risk_row)
    risk_bar = QtWidgets.QProgressBar()
    risk_bar.setRange(0, 100)
    risk_bar.setValue(0)
    risk_bar.setTextVisible(False)
    risk_bar.setFixedHeight(8)
    risk_box.addWidget(risk_bar)
    risk_sub = QtWidgets.QLabel("probability of rhythm anomaly")
    risk_sub.setObjectName("CardSub")
    risk_box.addWidget(risk_sub)
    cards.addWidget(risk_card, 1)

    # Signal-quality card
    sqi_card, sqi_box = make_card("SIGNAL QUALITY")
    sqi_value = QtWidgets.QLabel("--")
    sqi_value.setObjectName("CardValue")
    sqi_box.addWidget(sqi_value)
    sqi_level_lbl = QtWidgets.QLabel("")
    sqi_level_lbl.setObjectName("CardSub")
    sqi_box.addWidget(sqi_level_lbl)
    cards.addWidget(sqi_card, 1)

    # Beats / link card
    beat_card, beat_box = make_card("BEATS · LINK")
    beat_value = QtWidgets.QLabel("--")
    beat_value.setObjectName("CardValue")
    beat_box.addWidget(beat_value)
    beat_sub = QtWidgets.QLabel("lead-off: --  ·  loss: --")
    beat_sub.setObjectName("CardSub")
    beat_box.addWidget(beat_sub)
    cards.addWidget(beat_card, 1)

    root.addLayout(cards)

    # ---- Waveform ---------------------------------------------------------
    plot_frame = QtWidgets.QFrame()
    plot_frame.setObjectName("Card")
    plot_lay = QtWidgets.QVBoxLayout(plot_frame)
    plot_lay.setContentsMargins(10, 10, 10, 6)

    plot = pg.PlotWidget()
    plot.setBackground(THEME["bg"])
    plot.showGrid(x=True, y=True, alpha=0.18)
    plot.setLabel("bottom", "time", units="s", color=THEME["muted"])
    plot.setLabel("left", "filtered ECG", units="ADC dev.", color=THEME["muted"])
    plot.getAxis("bottom").setPen(pg.mkPen(THEME["grid"]))
    plot.getAxis("left").setPen(pg.mkPen(THEME["grid"]))
    plot.getAxis("bottom").setTextPen(pg.mkPen(THEME["muted"]))
    plot.getAxis("left").setTextPen(pg.mkPen(THEME["muted"]))
    legend = plot.addLegend(offset=(-10, 10), labelTextColor=THEME["muted"])
    curve = plot.plot(pen=pg.mkPen(THEME["trace"], width=2.0), name="filtered ECG")
    marker_items = {
        "P": plot.plot([], [], pen=None, symbol="o", symbolSize=8, symbolBrush=pg.mkBrush(THEME["P"]), symbolPen=None, name="P"),
        "Q": plot.plot([], [], pen=None, symbol="o", symbolSize=8, symbolBrush=pg.mkBrush(THEME["Q"]), symbolPen=None, name="Q"),
        "R": plot.plot([], [], pen=None, symbol="o", symbolSize=12, symbolBrush=pg.mkBrush(THEME["R"]), symbolPen=pg.mkPen("#ffffff", width=1), name="R"),
        "S": plot.plot([], [], pen=None, symbol="o", symbolSize=8, symbolBrush=pg.mkBrush(THEME["S"]), symbolPen=None, name="S"),
        "T": plot.plot([], [], pen=None, symbol="o", symbolSize=8, symbolBrush=pg.mkBrush(THEME["T"]), symbolPen=None, name="T"),
    }
    plot_lay.addWidget(plot)
    root.addWidget(plot_frame, 1)

    # ---- Footer -----------------------------------------------------------
    footer = QtWidgets.QFrame()
    footer.setObjectName("Footer")
    flay = QtWidgets.QVBoxLayout(footer)
    flay.setContentsMargins(16, 10, 16, 10)
    flay.setSpacing(3)
    warning = QtWidgets.QLabel("")
    warning.setStyleSheet("font-size: 14px; font-weight: 700;")
    flay.addWidget(warning)
    sqi_detail = QtWidgets.QLabel("")
    sqi_detail.setObjectName("Foot")
    sqi_detail.setWordWrap(True)
    flay.addWidget(sqi_detail)
    ml_label = QtWidgets.QLabel("")
    ml_label.setObjectName("Foot")
    flay.addWidget(ml_label)
    scenario_label = QtWidgets.QLabel("")
    scenario_label.setObjectName("Foot")
    flay.addWidget(scenario_label)
    root.addWidget(footer)

    def style_risk_bar(color: str) -> None:
        risk_bar.setStyleSheet(
            "QProgressBar { background: %s; border: none; border-radius: 4px; }"
            "QProgressBar::chunk { background: %s; border-radius: 4px; }"
            % (THEME["card_border"], color)
        )

    style_risk_bar(THEME["faint"])

    window_len = max(1, int(window_seconds * fs))
    buffer = np.asarray([], dtype=float)
    sample_cursor = 0
    log_file = open(log_output, "w") if log_output else None
    marker_labels = tuple(marker_items.keys())
    state = {
        "last_analysis": 0.0,
        "analysis": None,
        "marker_abs": {label: np.asarray([], dtype=int) for label in marker_labels},
    }
    # Re-run the (heavier) detection/SQI at most a few times per second; the
    # scrolling waveform itself is redrawn every tick so it stays smooth.
    analysis_period_s = 0.4

    def render_markers() -> None:
        buffer_start_abs = sample_cursor - buffer.size
        visible = display_waveform(buffer, fs)
        analysis = state.get("analysis")
        for label in marker_labels:
            if label != "R" and analysis is not None and not analysis.morphology_allowed:
                marker_items[label].setData([], [])
                continue
            idx = _relative_marker_indices(state["marker_abs"][label], buffer_start_abs, buffer.size)
            marker_items[label].setData(idx / fs if idx.size else [], visible[idx] if idx.size else [])

    def update():
        nonlocal buffer, sample_cursor
        chunk = source.read_chunk()
        samples = np.asarray(chunk.samples, dtype=float)
        if samples.size:
            buffer = np.concatenate([buffer, samples])[-window_len:]
            sample_cursor += int(samples.size)
            if log_file is not None:
                for v in samples:
                    log_file.write(f"{v}\n")
        t = np.arange(buffer.size) / fs
        visible = display_waveform(buffer, fs)
        curve.setData(t, visible)  # cheap redraw every tick -> smooth scrolling

        now = time.monotonic()
        if state["analysis"] is not None and now - state["last_analysis"] < analysis_period_s:
            render_markers()
            return  # skip the expensive analysis this tick
        state["last_analysis"] = now
        analysis = analyze_window(buffer, fs, chunk.lead_off, chunk.packet_loss_rate, ml_model)
        state["analysis"] = analysis
        buffer_start_abs = sample_cursor - buffer.size
        marker_indices = {
            "P": [m.p for m in analysis.markers if m.p is not None],
            "Q": [m.q for m in analysis.markers if m.q is not None],
            "R": [m.r for m in analysis.markers],
            "S": [m.s for m in analysis.markers if m.s is not None],
            "T": [m.t for m in analysis.markers if m.t is not None],
        }
        for label, indices in marker_indices.items():
            idx = np.asarray([i for i in indices if 0 <= i < buffer.size], dtype=int)
            state["marker_abs"][label] = buffer_start_abs + idx
        render_markers()

        # --- KPI cards ---
        hr_value.setText(f"{analysis.hr_bpm:.0f}" if analysis.hr_bpm else "--")
        if analysis.hr_bpm:
            hr_sub.setText("normal range 60–100 bpm")
            hr_value.setStyleSheet(
                "font-size: 40px; font-weight: 800; color: %s;"
                % (THEME["text"] if 60 <= analysis.hr_bpm <= 100 else THEME["warn"])
            )
        else:
            hr_sub.setText("waiting for beats…")

        color = _risk_color(analysis.risk_score, analysis.warning_suppressed)
        if analysis.warning_suppressed:
            risk_value.setText("--")
            risk_bar.setValue(0)
        else:
            risk_value.setText(f"{analysis.risk_score * 100:.0f}%")
            risk_bar.setValue(int(round(analysis.risk_score * 100)))
        risk_value.setStyleSheet("font-size: 40px; font-weight: 800; color: %s;" % color)
        risk_word.setText(_risk_word(analysis.risk_score, analysis.warning_suppressed))
        risk_word.setStyleSheet("font-size: 13px; font-weight: 700; color: %s;" % color)
        style_risk_bar(color)
        if analysis.warning_suppressed:
            risk_sub.setText("probability of rhythm anomaly")
            risk_sub.setStyleSheet("font-size: 12px; color: %s;" % THEME["muted"])
        else:
            risk_sub.setText(f"type: {_short_arr_type(analysis.arrhythmia_type)}")
            risk_sub.setStyleSheet("font-size: 12px; font-weight: 600; color: %s;" % color)

        sqi_value.setText(f"{analysis.sqi_score:.2f}")
        sqi_color = (
            THEME["ok"] if analysis.sqi_score >= 0.6
            else THEME["warn"] if analysis.sqi_score >= 0.3
            else THEME["bad"]
        )
        sqi_value.setStyleSheet("font-size: 40px; font-weight: 800; color: %s;" % sqi_color)
        sqi_level_lbl.setText(analysis.sqi_label)

        beat_value.setText(str(len(analysis.markers)))
        lead = "YES" if analysis.lead_off else "no"
        beat_sub.setText(f"lead-off: {lead}  ·  loss: {analysis.packet_loss_rate:.1%}")

        # --- Footer ---
        warn_text = analysis.warning_label
        if not analysis.warning_suppressed and analysis.risk_score >= 0.30:
            warn_text = f"{analysis.warning_label}  ·  {analysis.arrhythmia_type}"
        warning.setText(warn_text)
        warning.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: %s;"
            % (THEME["faint"] if analysis.warning_suppressed else color)
        )
        reasons = ", ".join(analysis.risk_reasons) if analysis.risk_reasons else ""
        sqi_detail.setText(
            f"{analysis.sqi_description}"
            + (f"   —   findings: {reasons}" if reasons and not analysis.warning_suppressed else "")
        )
        ml_label.setText(analysis.ml_advisory or "")
        if hasattr(source, "current_scenario_info"):
            info = source.current_scenario_info()
            scenario_label.setText(
                f"Mode: {info.get('mode', '--')}   ·   Scenario: {info.get('scenario', '--')}   ·   "
                f"Expected: {info.get('expected', '--')}"
            )
        else:
            scenario_label.setText("Mode: Live Arduino   ·   Scenario: hardware stream   ·   Expected: stable SQI and packet flow")

    timer = QtCore.QTimer()
    timer.timeout.connect(update)
    timer.start(int(getattr(source, "chunk_seconds", 0.2) * 1000))

    win.resize(1180, 720)
    win.show()
    try:
        return int(app.exec() if hasattr(app, "exec") else app.exec_())
    finally:
        if log_file is not None:
            log_file.close()
        close_source = getattr(source, "close", None)
        if callable(close_source):
            close_source()
