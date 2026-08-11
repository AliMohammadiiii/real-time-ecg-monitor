// ECG simulator for the real-time ECG monitoring prototype.
//
// Generates a synthetic PQRST-like waveform and streams it over serial in the
// SAME packet format the Python side expects, so you can test the full pipeline
// (serial -> QRS detection -> SQI -> warnings -> GUI) using only the Arduino
// board, with no AD8232 or electrodes connected.
//
// Packet format (matches ecg_monitor.serial_reader):
//   S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>
//     seq      : increasing sample counter (packet-loss detection)
//     micros   : Arduino timestamp in microseconds
//     adc      : synthetic 10-bit sample, 0..1023, centered ~512
//     lo_plus  : 0 (leads-on, simulated)
//     lo_minus : 0
//
// This is an educational simulator, NOT real physiological data.

const unsigned long SAMPLE_RATE_HZ = 250;
const unsigned long SAMPLE_PERIOD_US = 1000000UL / SAMPLE_RATE_HZ;
const float HEART_RATE_BPM = 75.0f;

unsigned long next_sample_us = 0;
unsigned long sequence = 0;

// Gaussian bump helper (centered at c samples, width w samples).
static float bump(float t, float c, float w) {
  float x = (t - c) / w;
  return expf(-0.5f * x * x);
}

void setup() {
  Serial.begin(115200);
  randomSeed(analogRead(A0));   // a little noise seed
  next_sample_us = micros();
}

void loop() {
  const unsigned long now = micros();
  if ((long)(now - next_sample_us) < 0) {
    return;
  }

  // Position within the current heartbeat, in samples.
  const float rr_samples = (60.0f / HEART_RATE_BPM) * (float)SAMPLE_RATE_HZ;
  const float t = (float)(sequence % (unsigned long)rr_samples);

  // Synthetic PQRST around a 512 baseline (approximate, educational).
  float v = 512.0f;
  v += 40.0f  * bump(t, 0.20f * rr_samples, 0.035f * rr_samples);   // P wave
  v -= 45.0f  * bump(t, 0.29f * rr_samples, 0.008f * rr_samples);   // Q
  v += 380.0f * bump(t, 0.31f * rr_samples, 0.010f * rr_samples);   // R peak
  v -= 90.0f  * bump(t, 0.34f * rr_samples, 0.012f * rr_samples);   // S
  v += 110.0f * bump(t, 0.50f * rr_samples, 0.045f * rr_samples);   // T wave
  v += (float)random(-6, 7);                                        // small noise

  int adc = (int)v;
  if (adc < 0) adc = 0;
  if (adc > 1023) adc = 1023;

  Serial.print("S,");
  Serial.print(sequence++);
  Serial.print(',');
  Serial.print(now);
  Serial.print(',');
  Serial.print(adc);
  Serial.print(",0,0");
  Serial.print('\n');

  next_sample_us += SAMPLE_PERIOD_US;
  if ((long)(now - next_sample_us) > (long)SAMPLE_PERIOD_US) {
    next_sample_us = now + SAMPLE_PERIOD_US;   // resync if we fell behind
  }
}
