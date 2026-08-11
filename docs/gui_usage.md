# Live ECG GUI Usage

`scripts/run_live_gui.py` shows a scrolling live ECG display built on PyQtGraph.

> **Educational prototype — not a medical device.** The GUI shows this banner at
> all times, and when signal quality is poor it displays
> "Signal unreliable; rhythm warnings suppressed." instead of a rhythm warning.

## Install GUI dependencies

The GUI is optional. The rest of the project (evaluation scripts, tests) runs
without it. Install a Qt binding plus PyQtGraph:

```bash
.venv/bin/python -m pip install pyqtgraph PyQt5
# PyQt6, PySide6, or PySide2 also work
```

If these are missing, the script prints this installation hint and exits
gracefully (it never crashes the rest of the project).

## Demo mode (no Arduino required)

```bash
.venv/bin/python scripts/run_live_gui.py --demo synthetic
```

This streams a synthetic ECG and is useful for screenshots and for verifying the
display without hardware.

## Live mode (with Arduino)

```bash
.venv/bin/python scripts/run_live_gui.py --port /dev/cu.usbmodemXXXX --baud 115200 --fs 250
```

Find the port on macOS with `ls /dev/cu.usbmodem*`. Close the Arduino Serial
Monitor first.

## Options

| Option | Meaning |
|---|---|
| `--demo synthetic` | Run without hardware using a synthetic ECG |
| `--port` | Serial port for live mode |
| `--baud` | Serial baud rate (default 115200) |
| `--fs` | Sampling rate in Hz (default 250) |
| `--window-seconds` | Scrolling window length (default 10) |
| `--model` | Optional exploratory ML model `.pkl` to show a non-diagnostic advisory |
| `--log-output` | Optional path to log streamed ADC values |

## What the GUI shows

- Scrolling ECG (ADC units) with detected R-peaks marked, and P/T markers when
  SQI allows morphology analysis.
- Current heart rate, SQI level and score, lead-off status, and packet-loss rate.
- A rule-based warning label (or the suppression message under poor SQI).
- An optional exploratory ML advisory (only when a model is loaded and SQI
  permits it) — this is non-diagnostic and never overrides the rule-based logic.

## Threading note

The GUI uses a single Qt `QTimer` to poll the data source and repaint, so serial
reads never block the UI thread. The demo and serial sources both expose the
same `read_chunk()` interface, which keeps the GUI simple.
