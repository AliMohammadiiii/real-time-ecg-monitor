// Simulated ECG packet generator for testing the Python pipeline without AD8232.
//
// Output packet:
// S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>
//
// The waveform is synthetic and educational. It is not a physiological model.
// Default mode simulates a fast rhythm so the Python rule-based module should
// report a preliminary high-heart-rate / tachycardia-pattern warning.

const unsigned long SAMPLE_RATE_HZ = 250;
const unsigned long SAMPLE_PERIOD_US = 1000000UL / SAMPLE_RATE_HZ;

// 480 ms RR interval is about 125 bpm.
const unsigned long RR_INTERVAL_US = 480000UL;

unsigned long next_sample_us = 0;
unsigned long beat_start_us = 0;
unsigned long sequence = 0;

int triangle(unsigned long phase_us, unsigned long center_us, unsigned long half_width_us, int amplitude) {
  const long distance = labs((long)phase_us - (long)center_us);
  if ((unsigned long)distance >= half_width_us) {
    return 0;
  }
  const long scaled = (long)amplitude * ((long)half_width_us - distance) / (long)half_width_us;
  return (int)scaled;
}

int simulatedEcgAdc(unsigned long phase_us) {
  int value = 512;

  // Gentle low-frequency baseline motion using a cheap triangular drift.
  const unsigned long drift_period_us = 4000000UL;
  unsigned long drift_phase = micros() % drift_period_us;
  int drift = drift_phase < drift_period_us / 2
                ? map(drift_phase, 0, drift_period_us / 2, -10, 10)
                : map(drift_phase, drift_period_us / 2, drift_period_us, 10, -10);

  // P-QRS-T morphology, scaled for Arduino 10-bit ADC.
  value += drift;
  value += triangle(phase_us, 90000UL, 30000UL, 28);      // P wave
  value += triangle(phase_us, 170000UL, 12000UL, -45);    // Q
  value += triangle(phase_us, 200000UL, 12000UL, 255);    // R
  value += triangle(phase_us, 232000UL, 16000UL, -65);    // S
  value += triangle(phase_us, 350000UL, 65000UL, 85);     // T wave

  if (value < 0) value = 0;
  if (value > 1023) value = 1023;
  return value;
}

void setup() {
  Serial.begin(115200);
  next_sample_us = micros();
  beat_start_us = next_sample_us;
}

void loop() {
  const unsigned long now = micros();
  if ((long)(now - next_sample_us) < 0) {
    return;
  }

  while ((unsigned long)(now - beat_start_us) >= RR_INTERVAL_US) {
    beat_start_us += RR_INTERVAL_US;
  }

  const unsigned long phase_us = now - beat_start_us;
  const int adc_value = simulatedEcgAdc(phase_us);

  // Simulated lead-off flags: always connected.
  const int lo_plus = 0;
  const int lo_minus = 0;

  Serial.print("S,");
  Serial.print(sequence++);
  Serial.print(',');
  Serial.print(now);
  Serial.print(',');
  Serial.print(adc_value);
  Serial.print(',');
  Serial.print(lo_plus);
  Serial.print(',');
  Serial.println(lo_minus);

  next_sample_us += SAMPLE_PERIOD_US;
  if ((long)(now - next_sample_us) > (long)SAMPLE_PERIOD_US) {
    next_sample_us = now + SAMPLE_PERIOD_US;
  }
}
