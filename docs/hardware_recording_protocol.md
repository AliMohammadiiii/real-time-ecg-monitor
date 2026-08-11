# AD8232 Hardware Recording Protocol

This document explains how to record real single-lead ECG with the Arduino +
AD8232 front end and how to evaluate the recorded logs.

> **Safety and scope.** This is an educational, non-diagnostic signal-processing
> prototype. It is **not** a medical device and must not be used for diagnosis,
> treatment, or emergency monitoring. When electrodes are attached to a person,
> prefer battery / power-bank operation, keep the laptop disconnected from mains
> power, and use a USB isolator. Never connect a mains-powered, non-isolated
> setup to a human subject.

## 1. Wiring

Flash `arduino/ad8232_sampler/ad8232_sampler.ino` and wire as follows:

| AD8232 | Arduino | Role |
|---|---|---|
| OUTPUT | A5 | analog ECG input used by the final sketch |
| LO+ | D3 | lead-off detection |
| LO- | D2 | lead-off detection |
| VCC | 3.3 V in the final recording setup | power |
| GND | GND | common ground |

Use disposable ECG electrodes following the module cable labels (typical
RA / LA / RL placement for a three-electrode educational setup). The sketch
streams packets at 250 Hz in the format
`S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>,<checksum>` at 115200 baud.

## 2. Find the serial port on macOS

```bash
ls /dev/cu.usbmodem*      # most Arduino-compatible boards
ls /dev/cu.usbserial*     # CH340 / FTDI clones
```

Close the Arduino IDE Serial Monitor before recording (only one program can hold
the port).

## 3. Record

Activate the venv, then record each condition. Files are written to
`data/real_ad8232/` as `YYYYMMDD_HHMMSS_ad8232_log.csv` with a matching
`_metadata.json`.

### 3a. 30 s at rest

```bash
.venv/bin/python scripts/record_ad8232_log.py \
  --port /dev/cu.usbmodemXXXX --duration 30 \
  --subject-id demo001 --condition rest \
  --notes "seated, still, battery power"
```

### 3b. Mild motion

```bash
.venv/bin/python scripts/record_ad8232_log.py \
  --port /dev/cu.usbmodemXXXX --duration 30 \
  --subject-id demo001 --condition mild_motion \
  --notes "gentle arm movement to induce motion artifact"
```

### 3c. Lead-off (and re-attach)

Detach one electrode partway through to trigger the LO flags, then re-attach:

```bash
.venv/bin/python scripts/record_ad8232_log.py \
  --port /dev/cu.usbmodemXXXX --duration 30 \
  --subject-id demo001 --condition lead_off \
  --notes "detach LA electrode ~10s, reattach ~20s"
```

During recording the script prints a live estimate of sample rate, packet loss,
malformed count, and lead-off state.

For the final live GUI workflow, `scripts/run_live_gui.py` records raw packets
while displaying the filtered ECG:

```bash
.venv/bin/python scripts/run_live_gui.py \
  --mode live --port /dev/cu.usbmodemXXXX --baud 115200 --fs 250 --window-seconds 10
```

This creates `*_ad8232_live_log.csv` and `*_live_metadata.json` in
`data/real_ad8232/`.

## 4. Evaluate a recorded log

```bash
.venv/bin/python scripts/evaluate_realtime_log.py \
  data/real_ad8232/YYYYMMDD_HHMMSS_ad8232_log.csv \
  --ecg-plot results/real_ad8232_ecg_plot.png \
  --sqi-plot results/real_ad8232_sqi_timeline.png
```

The evaluator reports duration, estimated sampling rate, packet loss,
malformed-packet count, timing jitter, lead-off periods, ADC clipping rate,
flatline periods, an SQI timeline, R-peak count, mean HR, and a warning
timeline, saving `results/real_ad8232_log_summary.csv` and `.json`.

You can validate the evaluator without hardware using the labelled **synthetic**
demo log:

```bash
.venv/bin/python scripts/evaluate_realtime_log.py tests/fixtures/demo_ad8232_log.csv
```

(`tests/fixtures/demo_ad8232_log.csv` is synthetic — see
`tests/fixtures/README.md`. It is not a real recording.)

## 5. Including results in the thesis

1. Record each real session with metadata.
2. Run the evaluator and `scripts/analyze_real_ad8232_sessions.py`.
3. Use only clean windows for PQRST figures if motion/device-placement artifacts
   appear in the raw stream.
4. Keep all wording non-diagnostic: report packet loss, sampling stability,
   lead-off handling, and SQI behaviour — not clinical findings.

The current final thesis artifacts include two real AD8232 recordings in
`data/real_ad8232/`: one from a 23-year-old female subject and one from a
24-year-old male subject. Broader hardware claims still require more people,
repeated sessions, controlled timestamps, and comparison with a clinical-grade
reference device.
