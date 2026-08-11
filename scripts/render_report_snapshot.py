"""Render a publication-quality snapshot of the live ECG dashboard as a PNG.

This produces the exact same "clinical monitor" look as the live GUI, but as a
static high-resolution image rendered with matplotlib — so it drops straight
into a report without needing to screenshot a running window. It uses real
AD8232 data and the project's real analysis pipeline (R-peak detection, SQI,
PQRST delineation, rule-based rhythm assessment), showing the clean, healthy
segment with its arrhythmia probability.

Example
-------
    python3 scripts/render_report_snapshot.py --out output/ecg_dashboard_report.png
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

from ecg_monitor.gui import THEME, display_waveform  # noqa: E402
from scripts.report_snapshot_common import (  # noqa: E402
    DEFAULT_LOG,
    analyze_at,
    best_window_start,
    load_log,
    worst_window_start,
)


def _risk_color(score: float, suppressed: bool) -> str:
    if suppressed:
        return THEME["faint"]
    if score >= 0.60:
        return THEME["bad"]
    if score >= 0.30:
        return THEME["warn"]
    return THEME["ok"]


_SHORT_TYPE = {
    "Premature ventricular contractions (PVC-like)": "PVC (ventricular ectopy)",
    "Premature beats (PVC/PAC-like)": "Premature beats",
    "Atrial-fibrillation-like (irregular, fast)": "AF-like (fast)",
    "Irregular rhythm (AF-like)": "Irregular (AF-like)",
    "Wide-QRS / conduction abnormality": "Wide-QRS",
    "Sinus tachycardia": "Tachycardia",
    "Sinus bradycardia": "Bradycardia",
    "Normal sinus rhythm": "Normal sinus rhythm",
}


def _short_type(t: str) -> str:
    return _SHORT_TYPE.get(t, t)


def _risk_word(score: float, suppressed: bool) -> str:
    if suppressed:
        return "SUPPRESSED"
    if score >= 0.60:
        return "HIGH"
    if score >= 0.30:
        return "MODERATE"
    return "LOW"


def _card(fig, x, y, w, h):
    """Draw a rounded card panel in figure coordinates; return its box."""
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0,rounding_size=0.012",
        transform=fig.transFigure, mutation_aspect=fig.get_figwidth() / fig.get_figheight(),
        facecolor=THEME["card"], edgecolor=THEME["card_border"], linewidth=1.2, zorder=1,
    )
    fig.patches.append(box)
    return x, y, w, h


def _txt(fig, x, y, s, *, size, color, weight="normal", ha="left", va="baseline", family=None):
    fig.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va,
             fontfamily=family, zorder=3)


def render(log: str | Path, out: Path, fs: float = 250.0, window_seconds: float = 10.0,
           start_seconds: float | None = None, select: str = "clean") -> Path:
    signal = load_log(log, fs=fs)
    if start_seconds is not None:
        start = int(start_seconds * fs)
    elif select == "risk":
        start = worst_window_start(signal, window_seconds)
    else:
        start = best_window_start(signal, window_seconds)
    seg, lead_off, a = analyze_at(signal, start, window_seconds)
    visible = display_waveform(seg, fs)
    t = np.arange(visible.size) / fs

    suppressed = a.warning_suppressed
    risk_col = _risk_color(a.risk_score, suppressed)

    # --- figure ---------------------------------------------------------
    fig = plt.figure(figsize=(13.2, 7.9), dpi=200)
    fig.patch.set_facecolor(THEME["bg"])

    # Header
    _txt(fig, 0.035, 0.945, "ECG Live Monitor", size=25, color=THEME["text"], weight="bold")
    _txt(fig, 0.035, 0.915, "Arduino + AD8232   ·   real-time rhythm screening", size=12, color=THEME["muted"])
    # safety pill
    pill = FancyBboxPatch((0.618, 0.917), 0.347, 0.047, boxstyle="round,pad=0,rounding_size=0.02",
                          transform=fig.transFigure, mutation_aspect=fig.get_figwidth() / fig.get_figheight(),
                          facecolor=THEME["warn"], edgecolor="none", zorder=2)
    fig.patches.append(pill)
    _txt(fig, 0.7915, 0.9405, "Educational prototype — not a medical device.", size=11,
         color="#201400", weight="bold", ha="center", va="center")

    # --- KPI cards ------------------------------------------------------
    cy, ch = 0.665, 0.205
    gap = 0.018
    cw = (0.93 - 3 * gap) / 4.0
    x0 = 0.035
    xs = [x0 + i * (cw + gap) for i in range(4)]

    def card_title(cx, s):
        _txt(fig, cx + 0.016, cy + ch - 0.036, s, size=11, color=THEME["muted"], weight="bold")

    # HR
    _card(fig, xs[0], cy, cw, ch)
    card_title(xs[0], "HEART RATE")
    hr_txt = f"{a.hr_bpm:.0f}" if a.hr_bpm else "--"
    hr_col = THEME["text"] if (a.hr_bpm and 60 <= a.hr_bpm <= 100) else THEME["warn"]
    _txt(fig, xs[0] + 0.016, cy + 0.072, hr_txt, size=44, color=hr_col, weight="bold")
    _txt(fig, xs[0] + 0.016 + 0.115, cy + 0.078, "bpm", size=13, color=THEME["muted"])
    _txt(fig, xs[0] + 0.016, cy + 0.03, "normal range 60–100 bpm", size=10.5, color=THEME["muted"])

    # Arrhythmia risk
    _card(fig, xs[1], cy, cw, ch)
    card_title(xs[1], "ARRHYTHMIA RISK")
    risk_txt = "--" if suppressed else f"{a.risk_score * 100:.0f}%"
    _txt(fig, xs[1] + 0.016, cy + 0.088, risk_txt, size=44, color=risk_col, weight="bold")
    _txt(fig, xs[1] + 0.016 + 0.11, cy + 0.096, _risk_word(a.risk_score, suppressed), size=13,
         color=risk_col, weight="bold")
    # risk bar
    bar_x, bar_w, bar_y, bar_h = xs[1] + 0.016, cw - 0.032, cy + 0.055, 0.011
    fig.patches.append(Rectangle((bar_x, bar_y), bar_w, bar_h, transform=fig.transFigure,
                                 facecolor=THEME["card_border"], edgecolor="none", zorder=2))
    frac = 0.0 if suppressed else max(0.0, min(1.0, a.risk_score))
    fig.patches.append(Rectangle((bar_x, bar_y), bar_w * frac, bar_h, transform=fig.transFigure,
                                 facecolor=risk_col, edgecolor="none", zorder=3))
    if suppressed:
        _txt(fig, xs[1] + 0.016, cy + 0.03, "probability of rhythm anomaly", size=10.5, color=THEME["muted"])
    else:
        _txt(fig, xs[1] + 0.016, cy + 0.03, f"type: {_short_type(a.arrhythmia_type)}", size=10.5, color=risk_col, weight="bold")

    # SQI
    _card(fig, xs[2], cy, cw, ch)
    card_title(xs[2], "SIGNAL QUALITY")
    sqi_col = THEME["ok"] if a.sqi_score >= 0.6 else THEME["warn"] if a.sqi_score >= 0.3 else THEME["bad"]
    _txt(fig, xs[2] + 0.016, cy + 0.072, f"{a.sqi_score:.2f}", size=44, color=sqi_col, weight="bold")
    _txt(fig, xs[2] + 0.016, cy + 0.03, a.sqi_label, size=10.5, color=THEME["muted"])

    # Beats / link
    _card(fig, xs[3], cy, cw, ch)
    card_title(xs[3], "BEATS · LINK")
    _txt(fig, xs[3] + 0.016, cy + 0.072, str(len(a.markers)), size=44, color=THEME["accent"], weight="bold")
    _txt(fig, xs[3] + 0.016, cy + 0.03,
         f"lead-off: {'YES' if a.lead_off else 'no'}   ·   loss: {a.packet_loss_rate:.1%}",
         size=10.5, color=THEME["muted"])

    # --- waveform -------------------------------------------------------
    ax = fig.add_axes([0.045, 0.135, 0.91, 0.44])
    ax.set_facecolor(THEME["bg"])
    ax.plot(t, visible, color=THEME["trace"], linewidth=1.7, zorder=2)
    ax.grid(True, color=THEME["grid"], linewidth=0.7, alpha=0.7)
    for spine in ax.spines.values():
        spine.set_color(THEME["card_border"])
    ax.tick_params(colors=THEME["muted"], labelsize=9)
    ax.set_xlabel("time (s)", color=THEME["muted"], fontsize=10)
    ax.set_ylabel("filtered ECG (ADC deviation)", color=THEME["muted"], fontsize=10)
    ax.set_xlim(t[0], t[-1])

    marker_specs = [("P", "p", 38), ("Q", "q", 34), ("R", "r", 70), ("S", "s", 34), ("T", "t", 38)]
    for label, attr, sz in marker_specs:
        if label != "R" and not a.morphology_allowed:
            continue
        idx = [getattr(m, attr) for m in a.markers if getattr(m, attr) is not None]
        idx = [int(i) for i in idx if 0 <= int(i) < visible.size]
        if not idx:
            continue
        ax.scatter(np.asarray(idx) / fs, visible[idx], s=sz, color=THEME[label],
                   edgecolors="white" if label == "R" else "none",
                   linewidths=0.8 if label == "R" else 0, zorder=4, label=label)
    leg = ax.legend(loc="upper right", ncol=5, fontsize=9, frameon=True, handletextpad=0.2, columnspacing=0.9)
    leg.get_frame().set_facecolor(THEME["card"])
    leg.get_frame().set_edgecolor(THEME["card_border"])
    for txt in leg.get_texts():
        txt.set_color(THEME["muted"])

    # --- footer ---------------------------------------------------------
    warn_col = THEME["faint"] if suppressed else risk_col
    warn_text = a.warning_label
    if not suppressed and a.risk_score >= 0.30:
        warn_text = f"{a.warning_label}   ·   {a.arrhythmia_type}"
    _txt(fig, 0.045, 0.088, warn_text, size=14, color=warn_col, weight="bold")
    reasons = ", ".join(a.risk_reasons) if a.risk_reasons and not suppressed else ""
    detail = a.sqi_description + (f"   —   findings: {reasons}" if reasons else "")
    _txt(fig, 0.045, 0.056, detail, size=10.5, color=THEME["muted"])
    _txt(fig, 0.045, 0.026,
         f"Mode: Replay · real AD8232 recording   ·   Source: {signal.name}   ·   "
         f"Window: {start / fs:.0f}–{start / fs + window_seconds:.0f}s   ·   fs = {fs:.0f} Hz",
         size=10.5, color=THEME["muted"])

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, facecolor=THEME["bg"])
    plt.close(fig)
    print(f"Saved {out}  (HR={hr_txt} bpm, risk={risk_txt}, SQI={a.sqi_score:.2f}, beats={len(a.markers)})")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="AD8232 packet log to render")
    parser.add_argument("--out", default="output/ecg_dashboard_report.png", help="Output PNG path")
    parser.add_argument("--fs", type=float, default=250.0)
    parser.add_argument("--window-seconds", type=float, default=10.0)
    parser.add_argument("--start-seconds", type=float, default=None,
                        help="Force window start (s); default auto-selects a window.")
    parser.add_argument("--select", choices=["clean", "risk"], default="clean",
                        help="Auto-select the cleanest window ('clean') or the one that best shows the arrhythmia ('risk').")
    args = parser.parse_args(argv)
    render(args.log, Path(args.out), fs=args.fs, window_seconds=args.window_seconds,
           start_seconds=args.start_seconds, select=args.select)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
