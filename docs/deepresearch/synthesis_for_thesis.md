# Deep Research Synthesis for This Project

## Decisions to carry into the thesis

1. Scope the system as an educational real-time ECG signal-processing prototype, not a medical diagnostic device.
2. Keep Arduino as a deterministic acquisition unit only: ADC sampling, lead-off reading, sequence number, timestamp, and USB/Serial transfer.
3. Run DSP on the computer with two branches:
   - display/delineation branch: morphology-preserving filtering around 0.5-40 Hz;
   - QRS branch: QRS-emphasizing filtering around 5-15 or 5-20 Hz.
4. Use modified Pan-Tompkins/Hamilton-style R detection as the primary implementation. Treat WFDB XQRS, Hamilton, or wavelet methods as comparison or future-work candidates.
5. Estimate P/Q/S/T as confidence-gated fiducial points. Q/S are stronger claims than P/T.
6. Add SQI before warning logic. Lead-off, flatline, clipping, severe packet loss, implausible RR, and poor morphology should suppress rhythm warnings.
7. Keep arrhythmia output rule-based and non-diagnostic. Use warning language, not diagnosis language.

## Implementation updates made from the research

- Arduino packet now includes a sample sequence and separate `LO+` / `LO-` flags:

```text
S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>
```

- Python serial parser accepts the new packet and keeps backward compatibility with the older three-field packet.
- Added an SQI module with hard rejection and graded confidence levels:
  - `unreliable`
  - `poor`
  - `usable_for_rate_qrs`
  - `usable_for_pqrst`
- Rule-based warnings now suppress all rhythm analysis when signal quality is very poor.
- Bradycardia logic is more conservative: below 60 bpm is a low-rate status, while below 50 bpm is a stronger preliminary bradycardia warning.
- Wide-QRS warning is only allowed when signal quality is high enough for morphology.

## Chapter 4 structure

1. Hardware implementation:
   - AD8232 role and safety boundary
   - Arduino Uno/Nano ADC sampling
   - lead-off pins
   - packet format and sequence number
2. Python implementation:
   - serial receiver
   - buffering and timestamp handling
   - filtering branches
   - QRS detector
   - PQRST estimator
   - SQI gate
   - rule-based warning module
3. Evaluation:
   - synthetic signal tests
   - MIT-BIH R-peak benchmark
   - QTDB fiducial benchmark as the next step
   - NSTDB/SQI stress test as the next step
   - real AD8232 recordings: rest, mild motion, lead-off, electrode reattachment

## References to prioritize

- Pan and Tompkins, 1985: baseline real-time QRS algorithm.
- Hamilton and Tompkins, 1986 / Hamilton open-source ECG analysis: practical QRS rules and prematurity heuristics.
- Arzeno et al., 2008: derivative-based QRS detector comparison.
- Martinez et al., 2004: wavelet ECG delineator.
- Orphanidou et al., 2015 and Zhao & Zhang, 2018: SQI and quality gating.
- PhysioNet MIT-BIH, QTDB, NSTDB, PWAVE, AFDB: datasets.
- Analog Devices AD8232 datasheet and Arduino Uno documentation: hardware constraints.

## Claims to avoid

- Do not claim medical arrhythmia diagnosis.
- Do not claim reliable clinical P/T measurement from noisy single-lead AD8232 data.
- Do not claim ML classification unless a separate patient-wise validation experiment is performed.
- Do not present 60/100 bpm thresholds as clinical diagnosis; present them as educational warning heuristics.
