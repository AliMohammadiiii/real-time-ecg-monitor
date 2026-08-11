"""Launch the beautiful live ECG dashboard on a real recording, positioned on
its cleanest, healthy-looking segment — ideal for a report screenshot.

This replays a real AD8232 packet log through the same live GUI used for
hardware, but seeks straight to the automatically selected clean window so the
first frame already shows a good signal, a normal heart rate, PQRST markers and
a low arrhythmia risk.

Examples
--------
    # Default: the clean normal-rhythm segment of the real human recording.
    python3 scripts/report_live_demo.py

    # Point at any other recording (e.g. one of the uploaded sessions):
    python3 scripts/report_live_demo.py --log data/real_ad8232/20260704_004343_ad8232_log.csv

Requires PyQtGraph + a Qt binding:
    pip install pyqtgraph PyQt5
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from ecg_monitor.gui import DatasetReplaySource, INSTALL_MESSAGE, pyqtgraph_available, run_gui  # noqa: E402
from scripts.report_snapshot_common import DEFAULT_LOG, best_window_start, load_log, worst_window_start  # noqa: E402


class SeekedReplaySource(DatasetReplaySource):
    """Dataset replay that starts at a chosen sample offset and reports a
    report-friendly scenario line in the GUI footer."""

    def current_scenario_info(self) -> dict:
        return {
            "mode": "Replay · real AD8232 recording",
            "scenario": self.name,
            "expected": "clean segment · normal rhythm · PQRST markers visible",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="AD8232 packet log to replay")
    parser.add_argument("--fs", type=float, default=250.0, help="Sampling rate (Hz)")
    parser.add_argument("--window-seconds", type=float, default=10.0, help="Scrolling window length")
    parser.add_argument("--chunk-seconds", type=float, default=0.04, help="GUI refresh chunk (0.04 ≈ 25 FPS)")
    parser.add_argument("--start-seconds", type=float, default=None,
                        help="Force a window start (s). Default: auto-detect a window.")
    parser.add_argument("--select", choices=["clean", "risk"], default="clean",
                        help="Land on the cleanest window ('clean') or the one that best shows the arrhythmia ('risk').")
    parser.add_argument("--model", default=None, help="Optional exploratory ML model .pkl for an advisory")
    args = parser.parse_args(argv)

    if not pyqtgraph_available():
        print(INSTALL_MESSAGE)
        return 1

    signal = load_log(args.log, fs=args.fs)
    if args.start_seconds is not None:
        start = int(args.start_seconds * args.fs)
    elif args.select == "risk":
        start = worst_window_start(signal, window_seconds=args.window_seconds)
    else:
        start = best_window_start(signal, window_seconds=args.window_seconds)
    print(f"Replaying {signal.name} from t={start / args.fs:.1f}s (auto-selected clean window)")

    source = SeekedReplaySource(
        samples=signal.adc,
        fs=args.fs,
        chunk_seconds=args.chunk_seconds,
        lead_off_flags=signal.lead_off.astype(bool),
        name=signal.name,
        loop=True,
    )
    # Pre-fill the scrolling buffer so the very first painted frame is the clean
    # window, then continue streaming forward from there.
    source._pos = int(start)

    ml_model = None
    if args.model:
        try:
            from ecg_monitor.ml_model import ExploratoryMLWarningModel

            ml_model = ExploratoryMLWarningModel.load(args.model)
        except Exception as exc:  # pragma: no cover
            print(f"Could not load ML model ({exc}); continuing without advisory.", file=sys.stderr)

    return run_gui(source, fs=args.fs, window_seconds=args.window_seconds, ml_model=ml_model)


if __name__ == "__main__":
    raise SystemExit(main())
