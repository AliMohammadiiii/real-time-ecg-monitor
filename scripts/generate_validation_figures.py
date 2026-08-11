"""Generate thesis/report figures for the ECG prototype."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from ecg_monitor import assess_signal_quality, delineate_pqrst, detect_r_peaks, preprocess_ecg
from ecg_monitor.synthetic import synthetic_ecg


def _matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def plot_pqrst(output: Path, fs: float = 250.0) -> None:
    plt = _matplotlib()
    signal, _ = synthetic_ecg(6.0, fs, heart_rate_bpm=72.0, noise_std=0.005)
    markers = delineate_pqrst(signal, fs)
    start = int(1.0 * fs)
    stop = int(4.5 * fs)
    t = np.arange(start, stop) / fs
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(t, signal[start:stop], lw=1.0, color="#1f77b4")
    colors = {"p": "#2ca02c", "q": "#ffbf00", "r": "#d62728", "s": "#ff7f0e", "t": "#9467bd"}
    for label in ("p", "q", "r", "s", "t"):
        idx = [getattr(m, label) for m in markers if getattr(m, label) is not None and start <= getattr(m, label) < stop]
        if idx:
            ax.scatter(np.asarray(idx) / fs, signal[idx], s=28 if label != "r" else 45, color=colors[label], label=label.upper(), zorder=3)
    ax.set_title("ECG waveform with tentative P/Q/R/S/T markers")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("amplitude")
    ax.legend(ncol=5, loc="upper right")
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_filter_branches(output: Path, fs: float = 250.0) -> None:
    plt = _matplotlib()
    signal, _ = synthetic_ecg(6.0, fs, heart_rate_bpm=72.0, noise_std=0.035)
    filtered = preprocess_ecg(signal, fs)
    start = int(1.0 * fs)
    stop = int(4.5 * fs)
    t = np.arange(start, stop) / fs
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(t, filtered.raw[start:stop], lw=0.7, label="Raw ECG", color="#73808c")
    ax.plot(t, filtered.display[start:stop], lw=0.9, label="Morphology branch", color="#1f77b4")
    ax.plot(t, filtered.qrs[start:stop], lw=0.9, label="QRS branch", color="#d62728")
    ax.set_title("Raw ECG vs morphology and QRS filtering branches")
    ax.set_xlabel("time (s)")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_sqi_timeline(output: Path, fs: float = 250.0) -> None:
    plt = _matplotlib()
    clean, _ = synthetic_ecg(8.0, fs, heart_rate_bpm=75.0, noise_std=0.008, seed=10)
    noisy, _ = synthetic_ecg(8.0, fs, heart_rate_bpm=75.0, noise_std=0.12, seed=11)
    flat = np.full(int(4.0 * fs), 0.0)
    recovered, _ = synthetic_ecg(8.0, fs, heart_rate_bpm=75.0, noise_std=0.015, seed=12)
    signal = np.concatenate([clean, noisy, flat, recovered])
    window = int(2.0 * fs)
    xs = []
    scores = []
    levels = []
    for start in range(0, signal.size - window + 1, window):
        segment = signal[start:start + window]
        r_peaks = detect_r_peaks(segment, fs)
        sqi = assess_signal_quality(segment, r_peaks=r_peaks)
        xs.append(start / fs)
        scores.append(sqi.score)
        levels.append(sqi.level)
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.step(xs, scores, where="post", color="#1f77b4")
    for x, level in zip(xs, levels):
        ax.text(x + 0.05, 0.05, level.replace("usable_for_", ""), rotation=90, fontsize=7, va="bottom")
    ax.set_ylim(0, 1)
    ax.set_title("SQI timeline: clean to noisy to flatline to recovered")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("SQI score")
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_mitdb_f1(input_csv: Path, output: Path) -> None:
    if not input_csv.exists():
        return
    plt = _matplotlib()
    rows = list(csv.DictReader(input_csv.open()))
    rows.sort(key=lambda r: float(r["f1"]))
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar([r["record"] for r in rows], [100 * float(r["f1"]) for r in rows], color="#4c78a8")
    ax.set_ylim(0, 105)
    ax.set_title("MIT-BIH per-record QRS F1")
    ax.set_xlabel("record")
    ax.set_ylabel("F1 (%)")
    ax.tick_params(axis="x", labelrotation=90)
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_qtdb_errors(input_json: Path, output: Path) -> None:
    if not input_json.exists():
        return
    plt = _matplotlib()
    data = json.load(input_json.open())
    records = data.get("records", [])
    values = []
    labels = []
    for marker in ("p", "r", "t"):
        vals = [r.get(f"{marker}_mae_ms") for r in records if r.get(f"{marker}_mae_ms") is not None]
        if vals:
            values.append(vals)
            labels.append(marker.upper())
    if not values:
        return
    fig, ax = plt.subplots(figsize=(7, 3.5))
    try:
        ax.boxplot(values, tick_labels=labels, showmeans=True)
    except TypeError:
        ax.boxplot(values, labels=labels, showmeans=True)
    ax.set_title("QTDB P/R/T timing MAE distribution")
    ax.set_ylabel("MAE (ms)")
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_detector_comparison(input_json: Path, output: Path) -> None:
    if not input_json.exists():
        return
    plt = _matplotlib()
    data = json.load(input_json.open())
    summaries = data.get("summaries", [])
    if not summaries:
        return
    labels = [s.get("detector", "unknown").replace("_", "\n") for s in summaries]
    x = np.arange(len(labels))
    width = 0.24
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.bar(x - width, [100 * float(s.get("sensitivity", 0)) for s in summaries], width, label="Sensitivity", color="#4c78a8")
    ax.bar(x, [100 * float(s.get("positive_predictive_value", 0)) for s in summaries], width, label="PPV", color="#59a14f")
    ax.bar(x + width, [100 * float(s.get("f1", 0)) for s in summaries], width, label="F1", color="#e15759")
    ax.set_ylim(85, 101)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("score (%)")
    ax.set_title("MIT-BIH detector comparison, 48 records, first 60 s")
    ax.legend(ncol=3, loc="lower right")
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_duration_sweep(input_json: Path, output: Path) -> None:
    if not input_json.exists():
        return
    plt = _matplotlib()
    rows = json.load(input_json.open())
    if not rows:
        return
    labels = [r.get("duration_label", str(r.get("seconds"))) for r in rows]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(x, [100 * float(r.get("sensitivity", 0)) for r in rows], marker="o", label="Sensitivity", color="#4c78a8")
    ax.plot(x, [100 * float(r.get("positive_predictive_value", 0)) for r in rows], marker="o", label="PPV", color="#59a14f")
    ax.plot(x, [100 * float(r.get("f1", 0)) for r in rows], marker="o", label="F1", color="#e15759")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(94, 100)
    ax.set_ylabel("score (%)")
    ax.set_title("MIT-BIH duration sweep")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(ncol=3, loc="lower right")
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_nstdb_sqi(input_json: Path, output: Path) -> None:
    if not input_json.exists():
        return
    plt = _matplotlib()
    data = json.load(input_json.open())
    records = data.get("records", data if isinstance(data, list) else [])
    if not records:
        return
    records = sorted(records, key=lambda r: float(r.get("snr_db", 0)), reverse=True)
    labels = [str(r.get("record")) for r in records]
    x = np.arange(len(labels))
    pqrst = [
        float(r.get("usable_for_pqrst_windows", r.get("pqrst_usable_windows", r.get("level_usable_for_pqrst", 0))))
        / max(float(r.get("n_windows", 1)), 1.0)
        for r in records
    ]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(x, [float(r.get("mean_sqi_score", 0)) for r in records], marker="o", color="#4c78a8", label="Mean SQI")
    ax.plot(x, pqrst, marker="s", color="#f28e2b", label="PQRST-usable window ratio")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylim(0, 1)
    ax.set_ylabel("score / ratio")
    ax.set_title("NSTDB SQI stress test")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_realtime_acquisition(input_json: Path, output: Path) -> None:
    if not input_json.exists():
        return
    plt = _matplotlib()
    data = json.load(input_json.open())
    summary = data.get("summary", {})
    timeline = data.get("sqi_timeline", [])
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.6))
    metrics = [
        ("valid\nsamples", summary.get("valid_samples", 0)),
        ("dropped", summary.get("dropped_packets", 0)),
        ("malformed", summary.get("malformed_packets", 0)),
        ("checksum\nerrors", summary.get("checksum_errors", 0)),
    ]
    ax1.bar([m[0] for m in metrics], [float(m[1]) for m in metrics], color=["#4c78a8", "#f28e2b", "#e15759", "#b07aa1"])
    ax1.set_title("AD8232 log packet quality")
    ax1.set_ylabel("count")
    if timeline:
        xs = [float(w.get("t_start_s", 0)) for w in timeline]
        ys = [float(w.get("sqi_score", 0)) for w in timeline]
        colors = ["#e15759" if not w.get("warning_allowed", True) else "#59a14f" for w in timeline]
        ax2.bar(xs, ys, width=4.0, align="edge", color=colors, alpha=0.75)
        ax2.set_ylim(0, 1)
        ax2.set_xlabel("time (s)")
        ax2.set_ylabel("SQI")
    ax2.set_title("SQI timeline; red = warnings suppressed")
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def plot_ml_confusion_matrix(input_json: Path, output: Path) -> None:
    if not input_json.exists():
        return
    plt = _matplotlib()
    data = json.load(input_json.open())
    labels = data.get("labels", [])
    matrix = np.asarray(data.get("confusion_matrix", []), dtype=float)
    if matrix.size == 0:
        return
    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    im = ax.imshow(matrix, cmap="Blues")
    ax.set_xticks(np.arange(len(labels)))
    ax.set_yticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_yticklabels(labels)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title("MIT-BIH exploratory ML confusion matrix")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, int(matrix[i, j]), ha="center", va="center", color="#111827")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="results/figures")
    parser.add_argument("--mitdb-csv", default="results/mitdb_qrs_results.csv")
    parser.add_argument("--qtdb-json", default="results/qtdb_fiducial_results.json")
    parser.add_argument("--duration-json", default="results/mitdb_duration_summary.json")
    parser.add_argument("--detector-json", default="results/mitdb_detector_comparison.json")
    parser.add_argument("--nstdb-json", default="results/nstdb_sqi_results.json")
    parser.add_argument("--live-json", default="results/real_ad8232_log_summary.json")
    parser.add_argument("--ml-json", default="results/ml_mitdb_results.json")
    args = parser.parse_args(argv)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    plot_pqrst(out / "ecg_pqrst_markers.png")
    plot_filter_branches(out / "raw_vs_filtered_branches.png")
    plot_sqi_timeline(out / "sqi_timeline_scenarios.png")
    plot_mitdb_f1(Path(args.mitdb_csv), out / "mitdb_per_record_f1.png")
    plot_qtdb_errors(Path(args.qtdb_json), out / "qtdb_timing_error_distribution.png")
    plot_duration_sweep(Path(args.duration_json), out / "mitdb_duration_sweep.png")
    plot_detector_comparison(Path(args.detector_json), out / "mitdb_detector_comparison.png")
    plot_nstdb_sqi(Path(args.nstdb_json), out / "nstdb_sqi_stress.png")
    plot_realtime_acquisition(Path(args.live_json), out / "realtime_acquisition_summary.png")
    plot_ml_confusion_matrix(Path(args.ml_json), out / "ml_mitdb_confusion_matrix.png")
    print(f"saved_figures_dir={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
