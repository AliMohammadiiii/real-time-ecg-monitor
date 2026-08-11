"""Generate an HTML ECG validation/session report.

The report is educational and non-diagnostic. It combines whichever result files
exist: MIT-BIH QRS summaries, QTDB fiducial summaries, NSTDB SQI stress tests,
scenario-suite outputs, and real AD8232 log evaluations.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_json(path: str | None):
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def _pct(value) -> str:
    if value is None:
        return "NA"
    return f"{100.0 * float(value):.2f}%"


def _num(value, digits: int = 2) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _section(title: str, body: str) -> str:
    return f"<section><h2>{html.escape(title)}</h2>{body}</section>"


def _mitdb_section(summary) -> str:
    if not summary:
        return _section("MIT-BIH QRS Evaluation", "<p>No MIT-BIH summary file was provided.</p>")
    rows = [[
        summary.get("records"),
        summary.get("tp"),
        summary.get("fp"),
        summary.get("fn"),
        _pct(summary.get("sensitivity")),
        _pct(summary.get("positive_predictive_value")),
        _pct(summary.get("f1")),
        _num(summary.get("false_positives_per_minute"), 3),
    ]]
    worst = summary.get("worst_records_by_fp", [])
    worst_rows = [[r.get("record"), r.get("fp"), r.get("fn"), _pct(r.get("positive_predictive_value")), _pct(r.get("f1"))] for r in worst]
    body = _table(["Records", "TP", "FP", "FN", "Sensitivity", "PPV", "F1", "FP/min"], rows)
    body += "<h3>Worst Records by FP</h3>"
    body += _table(["Record", "FP", "FN", "PPV", "F1"], worst_rows) if worst_rows else "<p>No worst-record list available.</p>"
    return _section("MIT-BIH QRS Evaluation", body)


def _duration_section(duration_summary) -> str:
    if not duration_summary:
        return ""
    rows = [
        [
            r.get("duration_label"),
            r.get("records"),
            _pct(r.get("sensitivity")),
            _pct(r.get("positive_predictive_value")),
            _pct(r.get("f1")),
            _num(r.get("false_positives_per_minute"), 3),
        ]
        for r in duration_summary
    ]
    return _section(
        "MIT-BIH Duration Sweep",
        _table(["Duration", "Records", "Sensitivity", "PPV", "F1", "FP/min"], rows),
    )


def _detector_section(detector_summary) -> str:
    if not detector_summary:
        return ""
    summaries = detector_summary.get("summaries", [])
    rows = [
        [
            s.get("detector"),
            _pct(s.get("sensitivity")),
            _pct(s.get("positive_predictive_value")),
            _pct(s.get("f1")),
            _num(s.get("mean_runtime_ms_per_minute_ecg"), 2),
        ]
        for s in summaries
    ]
    return _section(
        "Detector Comparison",
        _table(["Detector", "Sensitivity", "PPV", "F1", "Runtime ms/min ECG"], rows),
    )


def _qtdb_section(qtdb) -> str:
    if not qtdb:
        return _section("QTDB Fiducials", "<p>No QTDB result file was provided.</p>")
    by_marker = qtdb.get("aggregate", {}).get("by_marker", {})
    rows = [
        [
            marker,
            _num(metrics.get("mean_mae_ms"), 2),
            _pct(metrics.get("mean_coverage")),
            metrics.get("n_records_with_marker"),
        ]
        for marker, metrics in by_marker.items()
    ]
    return _section("QTDB Fiducials", _table(["Marker", "Mean MAE ms", "Coverage", "Records"], rows))


def _scenario_section(scenario) -> str:
    if not scenario:
        return ""
    summary = scenario.get("summary", {})
    rows = [[
        summary.get("source"),
        summary.get("n_scenarios"),
        _pct(summary.get("scenario_pass_rate")),
        _pct(summary.get("hr_pass_rate")),
        _pct(summary.get("rhythm_pass_rate")),
        _pct(summary.get("mean_marker_completeness")),
    ]]
    body = _table(["Source", "Scenarios", "Overall Pass", "HR Pass", "Warning Pass", "Marker Completeness"], rows)
    detail_rows = [
        [r.get("scenario"), r.get("overall_pass"), r.get("sqi_level"), r.get("mean_hr_bpm"), r.get("rhythm_label")]
        for r in scenario.get("rows", [])
    ]
    if detail_rows:
        body += "<h3>Scenario Detail</h3>" + _table(["Scenario", "Pass", "SQI", "HR", "System Output"], detail_rows)
    return _section("Scenario Simulation", body)


def _live_log_section(live) -> str:
    if not live:
        return ""
    summary = live.get("summary", {})
    rows = [
        ["Duration s", _num(summary.get("duration_s"), 2)],
        ["Average HR bpm", _num(summary.get("mean_hr_bpm"), 2)],
        ["SQI", f"{summary.get('overall_sqi_level')} ({_num(summary.get('overall_sqi_score'), 2)})"],
        ["Packet loss", _pct(summary.get("packet_loss_rate"))],
        ["Lead-off events", summary.get("lead_off_period_count")],
        ["Warnings suppressed windows", summary.get("windows_warning_suppressed")],
        ["Rhythm output", summary.get("rhythm_label")],
    ]
    return _section("Real-Time / AD8232 Session", _table(["Metric", "Value"], rows))


def _nstdb_section(nstdb) -> str:
    if not nstdb:
        return ""
    if isinstance(nstdb, list):
        rows = [
            [
                r.get("record"),
                r.get("snr_db"),
                _num(r.get("mean_sqi_score"), 3),
                r.get("warnings_suppressed_windows"),
                r.get("total_qrs_detected"),
            ]
            for r in nstdb
        ]
    else:
        rows = [
            [
                r.get("record"),
                r.get("snr_db"),
                _num(r.get("mean_sqi_score"), 3),
                r.get("warnings_suppressed_windows"),
                r.get("total_qrs_detected"),
            ]
            for r in nstdb.get("rows", nstdb.get("records", []))
        ]
    return _section("NSTDB SQI Stress Test", _table(["Record", "SNR", "Mean SQI", "Suppressed Windows", "QRS Count"], rows))


def _image(path: str | None, title: str, *, relative_to: Path | None = None) -> str:
    if not path or not Path(path).exists():
        return ""
    src = path
    if relative_to is not None:
        src = os.path.relpath(Path(path), start=relative_to)
    return f"<figure><img src='{html.escape(src)}' alt='{html.escape(title)}'><figcaption>{html.escape(title)}</figcaption></figure>"


def build_report(args) -> str:
    mitdb = _load_json(args.mitdb_summary)
    duration = _load_json(args.duration_summary)
    detector = _load_json(args.detector_comparison)
    qtdb = _load_json(args.qtdb_results)
    nstdb = _load_json(args.nstdb_results)
    scenario = _load_json(args.scenario_results)
    live = _load_json(args.live_log_results)

    sections = [
        _mitdb_section(mitdb),
        _duration_section(duration),
        _detector_section(detector),
        _qtdb_section(qtdb),
        _nstdb_section(nstdb),
        _scenario_section(scenario),
        _live_log_section(live),
    ]
    default_figures = [
        "results/figures/raw_vs_filtered_branches.png",
        "results/figures/ecg_pqrst_markers.png",
        "results/figures/sqi_timeline_scenarios.png",
        "results/figures/mitdb_per_record_f1.png",
        "results/figures/mitdb_duration_sweep.png",
        "results/figures/mitdb_detector_comparison.png",
        "results/figures/qtdb_timing_error_distribution.png",
        "results/figures/nstdb_sqi_stress.png",
        "results/figures/realtime_acquisition_summary.png",
        "results/figures/ml_mitdb_confusion_matrix.png",
    ]
    output_dir = Path(args.output).parent
    figures = _image(args.ecg_plot, "ECG waveform", relative_to=output_dir) + _image(
        args.sqi_plot, "SQI timeline", relative_to=output_dir
    )
    for figure in (args.figure or default_figures):
        figures += _image(figure, Path(figure).stem.replace("_", " "), relative_to=output_dir)
    if figures:
        sections.append(_section("Figures", figures))
    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2933; }
    h1 { margin-bottom: 0; }
    .scope { color: #9a3412; font-weight: 700; margin: 8px 0 24px; }
    section { margin: 28px 0; }
    table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 14px; }
    th, td { border: 1px solid #cbd5df; padding: 7px 9px; text-align: left; }
    th { background: #eef2f6; }
    img { max-width: 100%; border: 1px solid #d8dee6; }
    figcaption { color: #52616f; font-size: 13px; margin-top: 6px; }
    """
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>ECG Session Report</title>"
        f"<style>{css}</style></head><body>"
        "<h1>ECG Session Report</h1>"
        "<div class='scope'>Educational prototype - not a medical device; not for diagnosis.</div>"
        + "".join(sections)
        + "</body></html>"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mitdb-summary", default="results/mitdb_qrs_summary.json")
    parser.add_argument("--duration-summary", default="results/mitdb_duration_summary.json")
    parser.add_argument("--detector-comparison", default="results/mitdb_detector_comparison.json")
    parser.add_argument("--qtdb-results", default="results/qtdb_fiducial_results.json")
    parser.add_argument("--nstdb-results", default="results/nstdb_sqi_results.json")
    parser.add_argument("--scenario-results", default="results/scenario_suite_results.json")
    parser.add_argument("--live-log-results", default="results/real_ad8232_log_summary.json")
    parser.add_argument("--ecg-plot", default=None)
    parser.add_argument("--sqi-plot", default=None)
    parser.add_argument("--figure", action="append", help="Additional figure path to embed; may be repeated")
    parser.add_argument("--output", default="results/ecg_session_report.html")
    args = parser.parse_args(argv)

    report = build_report(args)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"saved_report={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
