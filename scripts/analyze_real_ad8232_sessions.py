"""Compare the two final real AD8232 live recordings.

The analysis is educational and non-diagnostic. PQRST/interval reporting uses
only automatically selected clean windows so motion and device-placement
artifacts do not dominate the final figures.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from ecg_monitor import assess_rhythm, assess_signal_quality, delineate_pqrst, detect_r_peaks, extract_features, preprocess_ecg
from scripts.evaluate_realtime_log import evaluate_log, parse_log


DEFAULT_SESSIONS = [
    {
        "subject_id": "F23",
        "label": "Female 23",
        "sex_age": "خانم ۲۳ ساله",
        "log": "data/real_ad8232/20260704_190653_ad8232_live_log.csv",
        "metadata": "data/real_ad8232/20260704_190653_live_metadata.json",
    },
    {
        "subject_id": "M24",
        "label": "Male 24",
        "sex_age": "آقای ۲۴ ساله",
        "log": "data/real_ad8232/20260704_191215_ad8232_live_log.csv",
        "metadata": "data/real_ad8232/20260704_191215_live_metadata.json",
    },
]


def _pct(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{100.0 * float(value):.2f}%"


def _num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def _load_metadata(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _segment_summary(session: dict, adc: np.ndarray, lead_off: np.ndarray, ts_s: np.ndarray, fs: float, start: int, stop: int, condition: str) -> dict:
    segment = adc[start:stop]
    lead = lead_off[start:stop]
    seg_ts = ts_s[start:stop]
    duration = float(seg_ts[-1] - seg_ts[0]) if seg_ts.size >= 2 else 0.0
    r_peaks = detect_r_peaks(segment, fs, analysis_allowed=not bool(np.mean(lead) > 0.5))
    sqi = assess_signal_quality(segment, r_peaks=r_peaks, lead_off=bool(np.mean(lead) > 0.1), adc_min=0, adc_max=1023)
    markers = delineate_pqrst(segment, fs, r_peaks, sqi.level)
    features = extract_features(segment, fs, markers)
    rhythm = assess_rhythm(features)
    rr_s = np.diff(r_peaks.astype(float)) / fs if r_peaks.size >= 2 else np.asarray([], dtype=float)
    rmssd = float(np.sqrt(np.mean(np.diff(rr_s) ** 2)) * 1000.0) if rr_s.size >= 2 else None
    sdnn = float(np.std(rr_s) * 1000.0) if rr_s.size else None
    pr_like = [
        (marker.r - marker.p) / fs
        for marker in markers
        if marker.p is not None and marker.r > marker.p and marker.p_confidence >= 0.20
    ]
    qrs_durations = features.qrs_durations_s
    qt_intervals = features.qt_intervals_s
    # QTc is approximate because Q/T are tentative single-lead peak markers.
    rr_median = float(np.median(rr_s)) if rr_s.size else None
    qtc_intervals = qt_intervals / np.sqrt(rr_median) if rr_median and qt_intervals.size else np.asarray([], dtype=float)
    n_markers = max(1, len(markers))
    p_visible = sum(1 for marker in markers if marker.p is not None)
    q_visible = sum(1 for marker in markers if marker.q is not None)
    s_visible = sum(1 for marker in markers if marker.s is not None)
    t_visible = sum(1 for marker in markers if marker.t is not None)
    return {
        "subject_id": session["subject_id"],
        "subject_label": session["label"],
        "sex_age": session["sex_age"],
        "condition": condition,
        "start_s": float(seg_ts[0]) if seg_ts.size else 0.0,
        "end_s": float(seg_ts[-1]) if seg_ts.size else 0.0,
        "duration_s": duration,
        "start_index": int(start),
        "end_index": int(stop),
        "sample_count": int(segment.size),
        "r_peak_count": int(r_peaks.size),
        "mean_hr_bpm": float(features.mean_hr_bpm) if features.mean_hr_bpm is not None else None,
        "median_rr_s": float(np.median(rr_s)) if rr_s.size else None,
        "rr_cv": float(features.rr_cv) if features.rr_cv is not None else None,
        "sdnn_ms": sdnn,
        "rmssd_ms": rmssd,
        "mean_p_to_r_ms": float(np.mean(pr_like) * 1000.0) if pr_like else None,
        "mean_qrs_ms": float(np.mean(qrs_durations) * 1000.0) if qrs_durations.size else None,
        "mean_qt_ms": float(np.mean(qt_intervals) * 1000.0) if qt_intervals.size else None,
        "mean_qtc_bazett_ms": float(np.mean(qtc_intervals) * 1000.0) if qtc_intervals.size else None,
        "p_visible_rate": p_visible / n_markers,
        "q_visible_rate": q_visible / n_markers,
        "s_visible_rate": s_visible / n_markers,
        "t_visible_rate": t_visible / n_markers,
        "sqi_level": sqi.level,
        "sqi_score": float(sqi.score),
        "sqi_reasons": "; ".join(sqi.reasons),
        "warning_allowed": bool(sqi.warning_allowed),
        "rhythm_label": rhythm.label if sqi.warning_allowed else "Suppressed by SQI",
        "rhythm_reasons": "; ".join(rhythm.reasons) if sqi.warning_allowed else f"SQI level {sqi.level}",
        "adc_mean": float(np.mean(segment)) if segment.size else None,
        "adc_std": float(np.std(segment)) if segment.size else None,
        "adc_min": int(np.min(segment)) if segment.size else None,
        "adc_max": int(np.max(segment)) if segment.size else None,
        "adc_clipping_rate": float(np.mean((segment <= 1) | (segment >= 1022))) if segment.size else None,
        "lead_off_fraction": float(np.mean(lead)) if lead.size else None,
    }


def _clean_segment_score(segment: dict) -> float:
    if segment["sqi_level"] != "usable_for_pqrst":
        return -1.0
    if segment["r_peak_count"] < 6:
        return -1.0
    if (segment["lead_off_fraction"] or 0.0) > 0.0:
        return -1.0
    clipping = segment["adc_clipping_rate"] or 0.0
    rr_cv = segment["rr_cv"] if segment["rr_cv"] is not None else 1.0
    marker_score = np.mean([
        segment["p_visible_rate"],
        segment["q_visible_rate"],
        segment["s_visible_rate"],
        segment["t_visible_rate"],
    ])
    return float(segment["sqi_score"] + 0.35 * marker_score - 4.0 * clipping - 0.6 * rr_cv)


def _select_clean_segments(
    session: dict,
    adc: np.ndarray,
    lead_off: np.ndarray,
    ts_s: np.ndarray,
    fs: float,
    *,
    window_s: float = 6.0,
    stride_s: float = 1.0,
    limit: int = 2,
) -> list[dict]:
    window = int(window_s * fs)
    stride = int(stride_s * fs)
    candidates: list[dict] = []
    for start in range(0, max(1, adc.size - window + 1), max(1, stride)):
        stop = min(adc.size, start + window)
        if stop - start < int(0.8 * window):
            continue
        seg = _segment_summary(session, adc, lead_off, ts_s, fs, start, stop, "clean candidate")
        score = _clean_segment_score(seg)
        if score >= 0.40 and (seg["adc_clipping_rate"] or 0.0) <= 0.02:
            seg["clean_score"] = score
            candidates.append(seg)

    candidates.sort(key=lambda item: item["clean_score"], reverse=True)
    selected: list[dict] = []
    for candidate in candidates:
        overlaps = False
        for existing in selected:
            overlap = min(candidate["end_index"], existing["end_index"]) - max(candidate["start_index"], existing["start_index"])
            if overlap > 0:
                overlap_ratio = overlap / max(1, candidate["end_index"] - candidate["start_index"])
                if overlap_ratio > 0.25:
                    overlaps = True
                    break
        if overlaps:
            continue
        candidate = dict(candidate)
        candidate["condition"] = f"بازه سالم {len(selected) + 1}"
        selected.append(candidate)
        if len(selected) >= limit:
            break

    if not selected:
        midpoint = max(0, adc.size // 2 - window // 2)
        fallback = _segment_summary(session, adc, lead_off, ts_s, fs, midpoint, min(adc.size, midpoint + window), "بهترین بازه موجود")
        fallback["clean_score"] = _clean_segment_score(fallback)
        selected.append(fallback)
    return selected


def _load_session_arrays(log_path: Path):
    samples, stats, _malformed = parse_log(log_path)
    if not samples:
        raise SystemExit(f"No valid samples found in {log_path}")
    adc = np.asarray([s.adc_value for s in samples], dtype=float)
    lead_off = np.asarray([s.lead_off for s in samples], dtype=bool)
    ts_us = np.asarray([s.timestamp_us for s in samples], dtype=float)
    ts_s = (ts_us - ts_us[0]) / 1_000_000.0
    fs = stats.sample_rate_estimate or 250.0
    return samples, stats, adc, lead_off, ts_s, fs


def _session_summary(session: dict, log_path: Path, meta_path: Path | None) -> tuple[dict, list[dict]]:
    result = evaluate_log(log_path)
    summary = result["summary"]
    metadata = _load_metadata(meta_path)
    _samples, stats, adc, lead_off, ts_s, fs = _load_session_arrays(log_path)
    segments = _select_clean_segments(session, adc, lead_off, ts_s, fs)
    row = {
        "subject_id": session["subject_id"],
        "subject_label": session["label"],
        "sex_age": session["sex_age"],
        "log_file": str(log_path),
        "metadata_file": str(meta_path) if meta_path else None,
        "started_utc": metadata.get("started_utc"),
        "finished_utc": metadata.get("finished_utc"),
        "duration_s": summary["duration_s"],
        "valid_samples": summary["valid_samples"],
        "malformed_packets": summary["malformed_packets"],
        "checksum_errors": summary["checksum_errors"],
        "dropped_packets": summary["dropped_packets"],
        "packet_loss_rate": summary["packet_loss_rate"],
        "estimated_sampling_rate_hz": summary["estimated_sampling_rate_hz"],
        "timing_jitter_ratio": summary["timing_jitter_ratio"],
        "adc_clipping_rate": summary["adc_clipping_rate"],
        "lead_off_sample_count": summary["lead_off_sample_count"],
        "overall_sqi_level": summary["overall_sqi_level"],
        "overall_sqi_score": summary["overall_sqi_score"],
        "r_peak_count": summary["r_peak_count"],
        "mean_hr_bpm": summary["mean_hr_bpm"],
        "rhythm_label": summary["rhythm_label"],
        "rhythm_reasons": summary["rhythm_reasons"],
        "n_windows": summary["n_windows"],
        "windows_warning_suppressed": summary["windows_warning_suppressed"],
    }
    row["_full_result"] = result
    row["_adc"] = adc
    row["_ts_s"] = ts_s
    row["_fs"] = fs
    row["_stats"] = stats
    return row, segments


def _matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _plot_session_snippets(segments: list[dict], rows_by_subject: dict[str, dict], out_dir: Path) -> Path:
    plt = _matplotlib()
    fig, axes = plt.subplots(len(segments), 1, figsize=(12, max(4.0, 2.8 * len(segments))), sharex=False)
    if len(segments) == 1:
        axes = [axes]
    for ax, segment in zip(axes, segments):
        row = rows_by_subject[segment["subject_id"]]
        adc = row["_adc"]
        fs = row["_fs"]
        start = int(segment["start_index"])
        stop = int(segment["end_index"])
        visible = preprocess_ecg(adc[start:stop], fs).display
        t = np.arange(visible.size) / fs
        ax.plot(t, visible, lw=0.8, color="#0072B2")
        ax.set_title(f"{segment['subject_id']} {segment['condition']} | clean filtered ECG")
        ax.set_ylabel("ADC deviation")
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel("time within snippet (s)")
    fig.tight_layout()
    path = out_dir / "real_subject_filtered_snippets.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_hr_sqi(rows: list[dict], out_dir: Path) -> Path:
    plt = _matplotlib()
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    for row in rows:
        timeline = row["_full_result"].get("sqi_timeline", [])
        ts = [w["t_start_s"] for w in timeline]
        hr = [w["mean_hr_bpm"] if w["mean_hr_bpm"] is not None else np.nan for w in timeline]
        sqi = [w["sqi_score"] for w in timeline]
        axes[0].plot(ts, hr, marker="o", ms=3, label=row["subject_id"])
        axes[1].plot(ts, sqi, marker="o", ms=3, label=row["subject_id"])
    axes[0].set_ylabel("HR bpm")
    axes[0].set_title("Windowed heart-rate timeline")
    axes[1].set_ylabel("SQI")
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylim(0, 1)
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.legend()
    fig.tight_layout()
    path = out_dir / "real_subject_hr_sqi_timeline.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_condition_bars(segments: list[dict], out_dir: Path) -> Path:
    plt = _matplotlib()
    labels = [f"{s['subject_id']}\n{s['condition'].split('/')[0].strip()}" for s in segments]
    x = np.arange(len(labels))
    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.bar(x - 0.18, [s["mean_hr_bpm"] or 0 for s in segments], width=0.36, color="#4c78a8", label="Mean HR")
    ax1.set_ylabel("HR bpm")
    ax2 = ax1.twinx()
    ax2.bar(x + 0.18, [s["sqi_score"] for s in segments], width=0.36, color="#59a14f", label="SQI")
    ax2.set_ylabel("SQI")
    ax2.set_ylim(0, 1)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_title("Clean-window HR and SQI")
    ax1.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = out_dir / "real_subject_condition_hr_sqi.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_acquisition_quality(rows: list[dict], out_dir: Path) -> Path:
    plt = _matplotlib()
    labels = [r["subject_id"] for r in rows]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(8, 4))
    width = 0.22
    ax.bar(x - width, [100 * r["packet_loss_rate"] for r in rows], width, label="packet loss %", color="#e15759")
    ax.bar(x, [100 * r["adc_clipping_rate"] for r in rows], width, label="ADC clipping %", color="#f28e2b")
    ax.bar(x + width, [100 * (r["timing_jitter_ratio"] or 0) for r in rows], width, label="jitter ratio %", color="#4c78a8")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("percent")
    ax.set_title("Acquisition quality indicators")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = out_dir / "real_subject_acquisition_quality.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_gui_marker_snapshots(segments: list[dict], rows_by_subject: dict[str, dict], out_dir: Path) -> Path:
    """Plot GUI-like clean snapshots with filtered ECG and P/Q/R/S/T markers."""
    plt = _matplotlib()
    colors = {"p": "#2ca02c", "q": "#ffbf00", "r": "#d62728", "s": "#ff7f0e", "t": "#9467bd"}
    fig, axes = plt.subplots(len(segments), 1, figsize=(12, max(4.0, 3.0 * len(segments))), sharex=False)
    if len(segments) == 1:
        axes = [axes]
    for ax, clean_segment in zip(axes, segments):
        row = rows_by_subject[clean_segment["subject_id"]]
        adc = row["_adc"]
        fs = row["_fs"]
        start = int(clean_segment["start_index"])
        stop = int(clean_segment["end_index"])
        segment = adc[start:stop]
        filtered = preprocess_ecg(segment, fs).display
        r_peaks = detect_r_peaks(segment, fs)
        sqi = assess_signal_quality(segment, r_peaks=r_peaks, adc_min=0, adc_max=1023)
        markers = delineate_pqrst(segment, fs, r_peaks, sqi.level)
        features = extract_features(segment, fs, markers)
        t = np.arange(segment.size) / fs
        ax.plot(t, filtered, lw=1.0, color="#0072B2", label="filtered ECG")
        for key, label in [("p", "P"), ("q", "Q"), ("r", "R"), ("s", "S"), ("t", "T")]:
            idx = []
            for marker in markers:
                value = getattr(marker, key)
                if value is not None and 0 <= int(value) < filtered.size:
                    idx.append(int(value))
            if idx:
                size = 46 if key == "r" else 28
                ax.scatter(np.asarray(idx) / fs, filtered[idx], s=size, color=colors[key], label=label, zorder=3)
        hr = "--" if features.mean_hr_bpm is None else f"{features.mean_hr_bpm:.1f}"
        ax.set_title(
            f"{clean_segment['subject_id']} {clean_segment['condition']} | HR={hr} bpm | "
            f"SQI={sqi.level} ({sqi.score:.2f})"
        )
        ax.set_ylabel("filtered ECG")
        ax.grid(alpha=0.25)
        ax.legend(ncol=6, loc="upper right")
    axes[-1].set_xlabel("time within clean snapshot (s)")
    fig.tight_layout()
    path = out_dir / "real_subject_gui_marker_snapshots.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _write_markdown(path: Path, rows: list[dict], segments: list[dict], figures: list[Path]) -> None:
    lines = [
        "# گزارش نهایی مقایسه دو رکورد واقعی AD8232",
        "",
        "این گزارش آموزشی و غیرتشخیصی است و برای تشخیص پزشکی یا تصمیم درمانی استفاده نمی‌شود.",
        "",
        "روش تحلیل: تکه‌های دارای جابه‌جایی دستگاه، clipping زیاد، SQI پایین یا RR ناپایدار از تحلیل تصویری حذف شدند. جدول‌های زیر فقط بر اساس سالم‌ترین بازه‌های ۶ ثانیه‌ای منتخب هر رکورد هستند.",
        "",
        "## خلاصه کل رکوردها",
        "",
        "| فرد | مدت | نمونه معتبر | نرخ نمونه‌برداری | packet loss | checksum error | clipping | SQI | HR میانگین | هشدار غیرتشخیصی |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['sex_age']} ({r['subject_id']}) | {_num(r['duration_s'], 2)}s | {r['valid_samples']} | "
            f"{_num(r['estimated_sampling_rate_hz'], 3)}Hz | {_pct(r['packet_loss_rate'])} | {r['checksum_errors']} | "
            f"{_pct(r['adc_clipping_rate'])} | {r['overall_sqi_level']} ({_num(r['overall_sqi_score'], 2)}) | "
            f"{_num(r['mean_hr_bpm'], 2)} | {r['rhythm_label']} |"
        )
    lines += [
        "",
        "## تحلیل بازه‌های سالم منتخب",
        "",
        "| فرد | بازه سالم | زمان | HR | RR CV | SDNN | RMSSD | P-R peak | QRS | QT | QTc | P/Q/S/T visibility | SQI | خروجی rule-based |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for s in segments:
        visibility = (
            f"P {_pct(s['p_visible_rate'])}, Q {_pct(s['q_visible_rate'])}, "
            f"S {_pct(s['s_visible_rate'])}, T {_pct(s['t_visible_rate'])}"
        )
        lines.append(
            f"| {s['sex_age']} ({s['subject_id']}) | {s['condition']} | {_num(s['start_s'], 1)}-{_num(s['end_s'], 1)}s | "
            f"{_num(s['mean_hr_bpm'], 2)} | {_num(s['rr_cv'], 3)} | {_num(s['sdnn_ms'], 1)}ms | {_num(s['rmssd_ms'], 1)}ms | "
            f"{_num(s['mean_p_to_r_ms'], 1)}ms | {_num(s['mean_qrs_ms'], 1)}ms | {_num(s['mean_qt_ms'], 1)}ms | "
            f"{_num(s['mean_qtc_bazett_ms'], 1)}ms | {visibility} | {s['sqi_level']} ({_num(s['sqi_score'], 2)}) | {s['rhythm_label']} |"
        )
    lines += [
        "",
        "## تفسیر مهندسی",
        "",
        "- هر دو رکورد از نظر acquisition سالم هستند: packet loss و checksum error صفر است و lead-off ثبت نشده است.",
        "- رکورد خانم ۲۳ ساله حدود ۱۳۰٫۶ ثانیه و رکورد آقای ۲۴ ساله حدود ۲۴۶٫۳ ثانیه طول دارد؛ هر دو با نرخ تقریباً دقیق ۲۵۰Hz ثبت شده‌اند.",
        "- SQI کل هر دو رکورد در سطح قابل استفاده برای PQRST قرار گرفت، اما برای شکل‌ها و تحلیل PQRST فقط سالم‌ترین پنجره‌ها استفاده شد.",
        "- شاخص‌های P-R peak، QRS، QT و QTc تقریبی هستند، چون markerها از ECG تک‌لید و الگوریتم آموزشی استخراج شده‌اند، نه از annotation پزشکی.",
        "- خروجی rhythm همچنان غیرتشخیصی و rule-based است. اگر warning دیده شود، به معنی تشخیص آریتمی نیست؛ فقط رفتار الگوریتم روی RR و markerهای همان بازه را نشان می‌دهد.",
        "- بخش‌های خراب ناشی از جابه‌جایی دستگاه از نمودارهای PQRST حذف شده‌اند.",
        "",
        "## نمودارها",
        "",
    ]
    for fig in figures:
        lines.append(f"![{fig.stem}]({fig.name})")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _html_table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _write_html(path: Path, rows: list[dict], segments: list[dict], figures: list[Path]) -> None:
    session_rows = [
        [
            f"{r['sex_age']} ({r['subject_id']})",
            f"{_num(r['duration_s'], 2)} s",
            r["valid_samples"],
            _pct(r["packet_loss_rate"]),
            r["checksum_errors"],
            f"{r['overall_sqi_level']} ({_num(r['overall_sqi_score'], 2)})",
            f"{_num(r['mean_hr_bpm'], 2)} bpm",
            r["rhythm_label"],
        ]
        for r in rows
    ]
    segment_rows = [
        [
            f"{s['sex_age']} ({s['subject_id']})",
            s["condition"],
            f"{_num(s['start_s'], 1)}-{_num(s['end_s'], 1)} s",
            f"{_num(s['mean_hr_bpm'], 2)} bpm",
            _num(s["rr_cv"], 3),
            f"{_num(s['sdnn_ms'], 1)} ms",
            f"{_num(s['rmssd_ms'], 1)} ms",
            f"{_num(s['mean_p_to_r_ms'], 1)} ms",
            f"{_num(s['mean_qrs_ms'], 1)} ms",
            f"{_num(s['mean_qt_ms'], 1)} ms",
            f"{_num(s['mean_qtc_bazett_ms'], 1)} ms",
            f"{s['sqi_level']} ({_num(s['sqi_score'], 2)})",
            _pct(s["adc_clipping_rate"]),
            s["rhythm_label"],
        ]
        for s in segments
    ]
    figure_html = "\n".join(
        f"<figure><img src='{html.escape(fig.name)}' alt='{html.escape(fig.stem)}'><figcaption>{html.escape(fig.stem)}</figcaption></figure>"
        for fig in figures
    )
    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2933; }
    .scope { color: #9a3412; font-weight: 700; }
    table { border-collapse: collapse; width: 100%; margin: 14px 0 28px; font-size: 14px; }
    th, td { border: 1px solid #cbd5df; padding: 7px 9px; text-align: left; }
    th { background: #eef2f6; }
    img { max-width: 100%; border: 1px solid #d8dee6; }
    figcaption { color: #52616f; font-size: 13px; margin-top: 6px; }
    """
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Real AD8232 Comparison Report</title>"
        f"<style>{css}</style></head><body>"
        "<h1>Real AD8232 Comparison Report</h1>"
        "<p class='scope'>Educational prototype; not a medical device; not for diagnosis.</p>"
        "<p>Only clean 6-second windows selected by SQI, clipping, lead-off and RR-stability checks are used for the PQRST analysis.</p>"
        "<h2>Whole-record summary</h2>"
        + _html_table(["Subject", "Duration", "Valid samples", "Packet loss", "Checksum errors", "SQI", "Mean HR", "Rule-based output"], session_rows)
        + "<h2>Clean-window PQRST summary</h2>"
        + _html_table(["Subject", "Clean window", "Range", "Mean HR", "RR CV", "SDNN", "RMSSD", "P-R peak", "QRS", "QT", "QTc", "SQI", "Clipping", "Rule-based output"], segment_rows)
        + "<h2>Figures</h2>"
        + figure_html
        + "</body></html>"
    )
    path.write_text(doc, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="results/real_ad8232_comparison")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    segments: list[dict] = []
    for session in DEFAULT_SESSIONS:
        row, segs = _session_summary(session, Path(session["log"]), Path(session["metadata"]))
        rows.append(row)
        segments.extend(segs)

    public_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
    (out_dir / "real_ad8232_session_comparison.json").write_text(
        json.dumps({"sessions": public_rows, "clean_segments": segments}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_csv(
        out_dir / "real_ad8232_session_comparison.csv",
        public_rows,
        [k for k in public_rows[0].keys()],
    )
    _write_csv(
        out_dir / "real_ad8232_condition_comparison.csv",
        segments,
        [k for k in segments[0].keys()],
    )
    rows_by_subject = {row["subject_id"]: row for row in rows}
    figures = [
        _plot_session_snippets(segments, rows_by_subject, out_dir),
        _plot_gui_marker_snapshots(segments, rows_by_subject, out_dir),
        _plot_hr_sqi(rows, out_dir),
        _plot_condition_bars(segments, out_dir),
        _plot_acquisition_quality(rows, out_dir),
    ]
    _write_markdown(out_dir / "real_ad8232_comparison_report.md", public_rows, segments, figures)
    _write_html(out_dir / "real_ad8232_comparison_report.html", public_rows, segments, figures)
    print(f"saved_dir={out_dir}")
    for figure in figures:
        print(f"plot={figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
