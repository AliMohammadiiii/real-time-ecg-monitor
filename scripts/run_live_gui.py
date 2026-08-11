"""Launch the live ECG GUI (educational prototype — not a medical device).

Two modes:

* ``--demo synthetic`` streams a synthetic ECG so the GUI works without any
  Arduino (useful for screenshots and testing).
* ``--mode replay`` replays a CSV or local WFDB record like a live ECG.
* ``--mode scenario`` cycles labelled validation scenarios.
* ``--mode live`` reads live packets from the Arduino serial port.

If PyQtGraph / a Qt binding is not installed, the script prints installation
instructions and exits gracefully without crashing the rest of the project.

Examples
--------
    python3 scripts/run_live_gui.py --demo synthetic
    python3 scripts/run_live_gui.py --port /dev/cu.usbmodem1101 --baud 115200 --fs 250
    python3 scripts/run_live_gui.py --demo synthetic --model results/ml_warning_model.pkl
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from ecg_monitor.gui import ChunkResult, DatasetReplaySource, DemoSignalSource, INSTALL_MESSAGE, pyqtgraph_available, run_gui
from ecg_monitor.serial_reader import SerialPacketTracker


class SerialSignalSource:
    """Reads Arduino packets from a serial port and yields ADC chunks."""

    def __init__(
        self,
        port: str,
        baud: int,
        fs: float = 250.0,
        chunk_seconds: float = 0.04,
        record_output_dir: str | Path | None = None,
    ):
        self.port = port
        self.baud = baud
        self.fs = fs
        self.chunk_seconds = chunk_seconds
        self.max_samples_per_chunk = max(1, int(round(self.chunk_seconds * self.fs)))
        self.tracker = SerialPacketTracker()
        self._rx_buffer = b""
        self._record_file = None
        self._record_log_path: Path | None = None
        self._record_meta_path: Path | None = None
        self._record_started_utc: str | None = None
        try:
            import serial
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "pyserial is required for live serial mode. Install with: "
                "pip install -r requirements.txt"
            ) from exc
        try:
            self.ser = serial.Serial(port, baud, timeout=0)
        except Exception as exc:
            raise SystemExit(
                f"Could not open serial port {port!r} at {baud} baud: {exc}\n"
                "List candidate ports on macOS with:  ls /dev/cu.usbmodem*"
            ) from exc
        if hasattr(self.ser, "reset_input_buffer"):
            self.ser.reset_input_buffer()
        if record_output_dir is not None:
            out_dir = Path(record_output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._record_log_path = out_dir / f"{stamp}_ad8232_live_log.csv"
            self._record_meta_path = out_dir / f"{stamp}_live_metadata.json"
            self._record_started_utc = datetime.now(timezone.utc).isoformat()
            self._record_file = self._record_log_path.open("w", buffering=1)
            print(f"live_raw_recording={self._record_log_path}", flush=True)

    def _read_complete_lines(self) -> list[bytes]:
        waiting = int(getattr(self.ser, "in_waiting", 0) or 0)
        if waiting <= 0:
            return []
        raw = self.ser.read(waiting)
        if not raw:
            return []
        self._rx_buffer += raw
        parts = self._rx_buffer.split(b"\n")
        if self._rx_buffer.endswith(b"\n"):
            complete = parts[:-1]
            self._rx_buffer = b""
        else:
            complete = parts[:-1]
            self._rx_buffer = parts[-1]
        if len(self._rx_buffer) > 4096:
            self._rx_buffer = b""
        return complete

    def read_chunk(self) -> ChunkResult:
        samples: list[float] = []
        lead_off = False
        for raw in self._read_complete_lines():
            line = raw.decode("ascii", errors="replace").strip()
            if self._record_file is not None and line:
                self._record_file.write(line + "\n")
            sample = self.tracker.update_line(line)
            if sample is not None:
                samples.append(float(sample.adc_value))
                lead_off = lead_off or sample.lead_off
        stats = self.tracker.snapshot()
        return ChunkResult(
            samples=np.asarray(samples[-self.max_samples_per_chunk:], dtype=float),
            lead_off=lead_off,
            packet_loss_rate=stats.packet_loss_rate,
        )

    def current_scenario_info(self) -> dict:
        recording = self._record_log_path.name if self._record_log_path else "off"
        return {
            "mode": "Live Arduino",
            "scenario": "hardware stream",
            "expected": f"stable SQI and packet flow | recording: {recording}",
        }

    def close(self) -> None:
        try:
            if hasattr(self.ser, "close"):
                self.ser.close()
        finally:
            if self._record_file is not None:
                self._record_file.close()
                self._record_file = None
            if self._record_meta_path is not None:
                stats = self.tracker.snapshot()
                metadata = {
                    "source": "run_live_gui.py --mode live",
                    "port": self.port,
                    "baud": self.baud,
                    "fs": self.fs,
                    "chunk_seconds": self.chunk_seconds,
                    "started_utc": self._record_started_utc,
                    "finished_utc": datetime.now(timezone.utc).isoformat(),
                    "log_file": self._record_log_path.name if self._record_log_path else None,
                    "packet_format": "S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>,<checksum>",
                    "valid_samples": stats.valid_samples,
                    "malformed_packets": stats.malformed_packets,
                    "checksum_errors": stats.checksum_errors,
                    "dropped_packets": stats.dropped_packets,
                    "packet_loss_rate": stats.packet_loss_rate,
                    "estimated_sampling_rate_hz": stats.sample_rate_estimate,
                    "lead_off_samples": stats.lead_off_samples,
                    "device": "Arduino + AD8232 (educational, non-diagnostic)",
                }
                self._record_meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                print(f"live_raw_metadata={self._record_meta_path}", flush=True)


class ScenarioSignalSource:
    """Cycle the labelled synthetic validation scenarios in the GUI."""

    def __init__(self, fs: float, chunk_seconds: float, scenario_seconds: float):
        from scripts.evaluate_scenario_suite import SCENARIOS, synthetic_scenario

        self.fs = fs
        self.chunk_seconds = chunk_seconds
        self.scenario_seconds = scenario_seconds
        self._scenarios = SCENARIOS
        self._synthetic_scenario = synthetic_scenario
        self._scenario_index = -1
        self._source: DatasetReplaySource | None = None
        self._scenario = None
        self._advance()

    def _advance(self) -> None:
        self._scenario_index = (self._scenario_index + 1) % len(self._scenarios)
        self._scenario = self._scenarios[self._scenario_index]
        adc, _truth, lead_off = self._synthetic_scenario(self._scenario, self.scenario_seconds, self.fs, seed=41 + self._scenario_index)
        self._source = DatasetReplaySource(
            samples=adc,
            fs=self.fs,
            chunk_seconds=self.chunk_seconds,
            lead_off_flags=lead_off,
            name=self._scenario.key,
            loop=False,
        )

    def read_chunk(self) -> ChunkResult:
        assert self._source is not None
        chunk = self._source.read_chunk()
        if self._source._pos >= self._source.samples.size:
            self._advance()
        return chunk

    def current_scenario_info(self) -> dict:
        expected = "HR/QRS usable"
        if self._scenario is not None:
            if self._scenario.lead_off:
                expected = "Poor signal; analysis suppressed"
            elif self._scenario.expected_reasons:
                expected = ", ".join(self._scenario.expected_reasons)
            elif not self._scenario.pqrst_expected:
                expected = "SQI drops; morphology unreliable"
        return {
            "mode": "Scenario simulation",
            "scenario": self._scenario.key if self._scenario else "--",
            "expected": expected,
        }


def _load_csv_samples(path: Path) -> np.ndarray:
    import csv

    with path.open() as f:
        first = f.readline()
        f.seek(0)
        if "," not in first:
            return np.loadtxt(path, dtype=float)
        reader = csv.DictReader(f)
        if reader.fieldnames:
            preferred = ["adc_value", "adc", "sample", "value", "ecg"]
            field = next((name for name in preferred if name in reader.fieldnames), None)
            if field is not None:
                return np.asarray([float(row[field]) for row in reader if row.get(field) not in (None, "")], dtype=float)
        f.seek(0)
        rows = []
        raw_reader = csv.reader(f)
        for row in raw_reader:
            if not row:
                continue
            try:
                rows.append(float(row[-1]))
            except ValueError:
                continue
        return np.asarray(rows, dtype=float)


def _load_wfdb_samples(record: str, local_dir: str | None, lead: int) -> tuple[np.ndarray, float]:
    try:
        import wfdb
    except ImportError as exc:
        raise SystemExit("wfdb is required for WFDB replay. Install with: pip install -r requirements.txt") from exc
    record_path = str(Path(local_dir) / record) if local_dir else record
    signals, fields = wfdb.rdsamp(record_path)
    lead = lead if lead < signals.shape[1] else 0
    return np.asarray(signals[:, lead], dtype=float), float(fields["fs"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default=None, help="Serial port for live mode, e.g. /dev/cu.usbmodem1101")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--fs", type=float, default=250.0, help="Sampling rate in Hz")
    parser.add_argument("--window-seconds", type=float, default=10.0, help="Scrolling window length")
    parser.add_argument(
        "--chunk-seconds",
        type=float,
        default=0.04,
        help="Live serial GUI refresh chunk length; 0.04 gives ~25 FPS at 250 Hz",
    )
    parser.add_argument("--demo", choices=["synthetic"], default=None, help="Run without hardware")
    parser.add_argument("--model", default=None, help="Optional exploratory ML model .pkl to show an advisory")
    parser.add_argument("--log-output", default=None, help="Optional path to log streamed ADC values")
    parser.add_argument(
        "--record-output-dir",
        default="data/real_ad8232",
        help="Directory for raw live serial packet recording in live mode",
    )
    parser.add_argument("--no-record", action="store_true", help="Disable automatic raw packet recording in live mode")
    parser.add_argument("--mode", choices=["live", "synthetic", "replay", "scenario"], default=None)
    parser.add_argument("--replay-csv", default=None, help="CSV path for --mode replay")
    parser.add_argument("--replay-wfdb", default=None, help="WFDB record id/path stem for --mode replay")
    parser.add_argument("--local-dir", default=None, help="Local WFDB database directory for replay")
    parser.add_argument("--lead", type=int, default=0, help="WFDB lead index for replay")
    parser.add_argument("--scenario-seconds", type=float, default=12.0, help="Seconds per scenario in scenario mode")
    args = parser.parse_args(argv)

    if not pyqtgraph_available():
        print(INSTALL_MESSAGE)
        return 1

    mode = args.mode or ("synthetic" if args.demo == "synthetic" else "live" if args.port else None)
    if mode == "synthetic":
        source = DemoSignalSource(fs=args.fs)
    elif mode == "replay":
        if args.replay_csv:
            samples = _load_csv_samples(Path(args.replay_csv))
            source = DatasetReplaySource(samples=samples, fs=args.fs, chunk_seconds=args.chunk_seconds, name=Path(args.replay_csv).name)
        elif args.replay_wfdb:
            samples, replay_fs = _load_wfdb_samples(args.replay_wfdb, args.local_dir, args.lead)
            source = DatasetReplaySource(samples=samples, fs=replay_fs, chunk_seconds=args.chunk_seconds, name=args.replay_wfdb)
            args.fs = replay_fs
        else:
            parser.error("--mode replay requires --replay-csv or --replay-wfdb")
    elif mode == "scenario":
        source = ScenarioSignalSource(fs=args.fs, chunk_seconds=args.chunk_seconds, scenario_seconds=args.scenario_seconds)
    elif mode == "live" and args.port:
        source = SerialSignalSource(
            args.port,
            args.baud,
            fs=args.fs,
            chunk_seconds=args.chunk_seconds,
            record_output_dir=None if args.no_record else args.record_output_dir,
        )
    else:
        parser.error("Provide --demo synthetic, --mode replay, --mode scenario, or --mode live --port <serial-port>.")

    ml_model = None
    if args.model:
        try:
            from ecg_monitor.ml_model import ExploratoryMLWarningModel

            ml_model = ExploratoryMLWarningModel.load(args.model)
        except Exception as exc:
            print(f"Could not load ML model ({exc}); continuing without ML advisory.", file=sys.stderr)

    return run_gui(source, fs=args.fs, window_seconds=args.window_seconds,
                   ml_model=ml_model, log_output=args.log_output)


if __name__ == "__main__":
    raise SystemExit(main())
