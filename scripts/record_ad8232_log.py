"""Record raw AD8232 / Arduino ECG packets from a serial port to a CSV log.

This is the real-hardware acquisition front end. It opens the serial port the
Arduino sketch (``arduino/ad8232_sampler``) prints to, validates each packet,
and writes a timestamped raw log plus a metadata sidecar file. It never
fabricates data: if no hardware or serial port is available it fails with a
clear message.

Packet format (from the Arduino sketch)::

    S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>,<checksum>

Output files (under ``--output-dir``)::

    YYYYMMDD_HHMMSS_ad8232_log.csv    raw packets, one per line
    YYYYMMDD_HHMMSS_metadata.json     recording metadata

Example
-------
    python3 scripts/record_ad8232_log.py --port /dev/cu.usbmodem1101 \
        --duration 30 --subject-id demo001 --condition rest

Use ``--duration 0`` to record continuously until Ctrl+C. The script still
finalizes metadata when interrupted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ecg_monitor.serial_reader import SerialPacketTracker

CONDITIONS = ("rest", "mild_motion", "lead_off", "reattach")


def _open_serial(port: str, baud: int):
    try:
        import serial  # pyserial
    except ImportError as exc:
        raise SystemExit(
            "pyserial is required to record from hardware. Install with: "
            "pip install -r requirements.txt"
        ) from exc
    try:
        return serial.Serial(port, baud, timeout=1.0)
    except Exception as exc:  # serial.SerialException and friends
        raise SystemExit(
            f"Could not open serial port {port!r} at {baud} baud.\n"
            f"Underlying error: {exc}\n"
            "On macOS list candidate ports with:  ls /dev/cu.usbmodem*  (or /dev/cu.usbserial*)\n"
            "Make sure the Arduino is connected and no other program (e.g. the "
            "Arduino Serial Monitor) is holding the port."
        ) from exc


def record(port: str, baud: int, duration: float, out_dir: Path,
           subject_id: str, condition: str, notes: str) -> tuple[Path, Path]:
    ser = _open_serial(port, baud)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = out_dir / f"{stamp}_ad8232_log.csv"
    meta_path = out_dir / f"{stamp}_metadata.json"

    tracker = SerialPacketTracker()
    start = time.monotonic()
    last_report = start
    started_iso = datetime.now(timezone.utc).isoformat()

    duration_label = "until Ctrl+C" if duration <= 0 else f"for {duration:g}s"
    print(f"Recording from {port} @ {baud} baud {duration_label} -> {log_path.name}")
    print("(Educational prototype — not a medical device. Prefer battery power / USB isolation.)")
    try:
        with log_path.open("w", buffering=1) as log_file:
            while duration <= 0 or time.monotonic() - start < duration:
                raw = ser.readline()
                if not raw:
                    continue
                try:
                    line = raw.decode("ascii", errors="replace").strip()
                except Exception:
                    continue
                if not line:
                    continue
                log_file.write(line + "\n")
                sample = tracker.update_line(line)
                now = time.monotonic()
                if now - last_report >= 1.0:
                    stats = tracker.snapshot()
                    lead_off = sample.lead_off if sample is not None else False
                    rate = stats.sample_rate_estimate or 0.0
                    print(
                        f"  t={now - start:5.1f}s rate~{rate:6.1f}Hz "
                        f"valid={stats.valid_samples} loss={stats.packet_loss_rate:.3%} "
                        f"malformed={stats.malformed_packets} lead_off={lead_off}",
                        flush=True,
                    )
                    last_report = now
    except KeyboardInterrupt:
        print("\nStopping recording on Ctrl+C; finalizing files...")
    finally:
        try:
            ser.close()
        except Exception:
            pass

    stats = tracker.snapshot()
    metadata = {
        "subject_id": subject_id,
        "condition": condition,
        "notes": notes,
        "port": port,
        "baud": baud,
        "requested_duration_s": duration,
        "stop_mode": "manual_ctrl_c" if duration <= 0 else "fixed_duration",
        "started_utc": started_iso,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "log_file": log_path.name,
        "packet_format": "S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>,<checksum>",
        "valid_samples": stats.valid_samples,
        "malformed_packets": stats.malformed_packets,
        "dropped_packets": stats.dropped_packets,
        "packet_loss_rate": stats.packet_loss_rate,
        "estimated_sampling_rate_hz": stats.sample_rate_estimate,
        "lead_off_samples": stats.lead_off_samples,
        "device": "Arduino + AD8232 (educational, non-diagnostic)",
    }
    with meta_path.open("w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nsaved_log={log_path}")
    print(f"saved_metadata={meta_path}")
    print(f"valid_samples={stats.valid_samples} malformed={stats.malformed_packets} "
          f"packet_loss={stats.packet_loss_rate:.3%} "
          f"rate~{(stats.sample_rate_estimate or 0.0):.1f}Hz")
    if stats.valid_samples == 0:
        print("WARNING: no valid packets captured — check wiring, sketch, and port.", file=sys.stderr)
    return log_path, meta_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/cu.usbmodem1101")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--duration", type=float, default=60.0, help="Recording duration in seconds; 0 means until Ctrl+C")
    parser.add_argument("--output-dir", default="data/real_ad8232", help="Directory for log + metadata")
    parser.add_argument("--subject-id", default="demo001", help="Subject identifier (educational use)")
    parser.add_argument("--condition", default="rest", choices=CONDITIONS, help="Recording condition")
    parser.add_argument("--notes", default="", help="Free-text notes about the recording")
    args = parser.parse_args(argv)

    record(
        port=args.port,
        baud=args.baud,
        duration=args.duration,
        out_dir=Path(args.output_dir),
        subject_id=args.subject_id,
        condition=args.condition,
        notes=args.notes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
