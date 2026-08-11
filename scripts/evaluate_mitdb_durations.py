"""Run MIT-BIH QRS evaluation at multiple durations.

Useful thesis presets:

* 60 seconds: fast smoke result for all 48 records.
* 300 seconds: more representative first-five-minute result.
* 0 seconds: full-record evaluation. This can take noticeably longer.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _duration_label(seconds: float) -> str:
    if seconds == 0:
        return "full"
    if seconds < 60:
        return f"{seconds:g}s"
    if seconds % 60 == 0:
        return f"{int(seconds // 60)}min"
    return f"{seconds:g}s"


def _run_duration(seconds: float, args) -> dict:
    label = _duration_label(seconds)
    out_csv = Path(args.output_dir) / f"mitdb_qrs_{label}.csv"
    out_json = Path(args.output_dir) / f"mitdb_qrs_{label}.json"
    summary_json = Path(args.output_dir) / f"mitdb_qrs_{label}_summary.json"
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "evaluate_mitdb.py"),
        "--seconds",
        str(seconds),
        "--out-csv",
        str(out_csv),
        "--out-json",
        str(out_json),
        "--summary-json",
        str(summary_json),
        "--tolerance-ms",
        str(args.tolerance_ms),
        "--refractory-ms",
        str(args.refractory_ms),
    ]
    if args.all_local:
        cmd.extend(["--all-local", "--local-dir", args.local_dir])
    elif args.records:
        cmd.extend(["--records", *args.records])
        if args.local_dir:
            cmd.extend(["--local-dir", args.local_dir])
    else:
        cmd.extend(["--record", args.record])
        if args.local_dir:
            cmd.extend(["--local-dir", args.local_dir])
    subprocess.run(cmd, check=True)
    with summary_json.open() as f:
        summary = json.load(f)
    summary["duration_label"] = label
    summary["seconds"] = seconds
    summary["csv"] = str(out_csv)
    summary["json"] = str(out_json)
    summary["summary_json"] = str(summary_json)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--durations", type=float, nargs="+", default=[60.0, 300.0])
    parser.add_argument("--include-full", action="store_true", help="Append full-record evaluation (seconds=0)")
    parser.add_argument("--record", default="100")
    parser.add_argument("--records", nargs="*")
    parser.add_argument("--all-local", action="store_true")
    parser.add_argument("--local-dir", default="data/physionet/mitdb")
    parser.add_argument("--tolerance-ms", type=float, default=150.0)
    parser.add_argument("--refractory-ms", type=float, default=220.0)
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--summary-csv", default="results/mitdb_duration_summary.csv")
    parser.add_argument("--summary-json", default="results/mitdb_duration_summary.json")
    args = parser.parse_args(argv)

    durations = list(args.durations)
    if args.include_full and 0.0 not in durations:
        durations.append(0.0)

    rows = [_run_duration(seconds, args) for seconds in durations]
    fieldnames = [
        "duration_label",
        "seconds",
        "records",
        "tp",
        "fp",
        "fn",
        "sensitivity",
        "positive_predictive_value",
        "f1",
        "false_positives_per_minute",
        "csv",
        "json",
        "summary_json",
    ]
    out_csv = Path(args.summary_csv)
    out_json = Path(args.summary_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fieldnames} for row in rows)
    with out_json.open("w") as f:
        json.dump(rows, f, indent=2)

    print("\nMIT-BIH duration summary")
    for row in rows:
        print(
            f"{row['duration_label']}: Se={row['sensitivity']:.4f} "
            f"PPV={row['positive_predictive_value']:.4f} F1={row['f1']:.4f} "
            f"FP/min={row['false_positives_per_minute']:.3f}"
        )
    print(f"saved_summary_csv={out_csv}")
    print(f"saved_summary_json={out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
