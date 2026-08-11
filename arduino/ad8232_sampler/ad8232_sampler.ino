const int ECG_PIN = A5;
const int LO_PLUS_PIN = 3;
const int LO_MINUS_PIN = 2;

// Wiring:
// Matches the wiring image supplied by the user:
// AD8232 OUTPUT -> Arduino A5
// AD8232 LO+    -> Arduino D3
// AD8232 LO-    -> Arduino D2
// AD8232 VCC    -> 3.3V or 5V according to the module documentation
// AD8232 GND    -> Arduino GND
//
// Electrode placement depends on the AD8232 module cable labels. For typical
// three-electrode educational testing, use RA/LA/RL positions recommended by
// the module vendor. This sketch is for educational signal acquisition only.
// It is not a medical device. Prefer battery power and USB isolation when
// electrodes are connected to a human subject.

const unsigned long SAMPLE_RATE_HZ = 250;
const unsigned long SAMPLE_PERIOD_US = 1000000UL / SAMPLE_RATE_HZ;
const int ADC_OVERSAMPLE_COUNT = 4;

unsigned long next_sample_us = 0;
unsigned long sequence = 0;

int readSmoothedAdc() {
  long total = 0;
  for (int i = 0; i < ADC_OVERSAMPLE_COUNT; i++) {
    total += analogRead(ECG_PIN);
    delayMicroseconds(120);
  }
  return (int)((total + ADC_OVERSAMPLE_COUNT / 2) / ADC_OVERSAMPLE_COUNT);
}

unsigned int packetChecksum(unsigned long seq, unsigned long timestamp_us, int adc_value, int lo_plus, int lo_minus) {
  unsigned int value = (unsigned int)(seq & 0xFFFF);
  value ^= (unsigned int)(timestamp_us & 0xFFFF);
  value ^= (unsigned int)((timestamp_us >> 16) & 0xFFFF);
  value ^= (unsigned int)(adc_value & 0x03FF);
  value ^= (unsigned int)((lo_plus & 1) << 10);
  value ^= (unsigned int)((lo_minus & 1) << 11);
  return value;
}

void setup() {
  pinMode(ECG_PIN, INPUT);
  pinMode(LO_PLUS_PIN, INPUT);
  pinMode(LO_MINUS_PIN, INPUT);
  Serial.begin(115200);
  next_sample_us = micros();
}

void loop() {
  const unsigned long now = micros();
  if ((long)(now - next_sample_us) < 0) {
    return;
  }

  const int adc_value = readSmoothedAdc();
  const int lo_plus = digitalRead(LO_PLUS_PIN) == HIGH ? 1 : 0;
  const int lo_minus = digitalRead(LO_MINUS_PIN) == HIGH ? 1 : 0;

  const unsigned long current_sequence = sequence++;
  const unsigned int checksum = packetChecksum(current_sequence, now, adc_value, lo_plus, lo_minus);

  // CSV packet fields:
  // S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>,<checksum>
  // seq: monotonically increasing sample counter for packet-loss checks
  // micros: Arduino timestamp in microseconds
  // adc: raw 10-bit ADC value from A5
  // lo_plus/lo_minus: AD8232 lead-off flags
  // checksum: XOR integrity check, parser remains backward compatible with
  // packets that omit this field
  Serial.print("S,");
  Serial.print(current_sequence);
  Serial.print(',');
  Serial.print(now);
  Serial.print(',');
  Serial.print(adc_value);
  Serial.print(',');
  Serial.print(lo_plus);
  Serial.print(',');
  Serial.print(lo_minus);
  Serial.print(',');
  Serial.println(checksum);

  next_sample_us += SAMPLE_PERIOD_US;
  if ((long)(now - next_sample_us) > (long)SAMPLE_PERIOD_US) {
    next_sample_us = now + SAMPLE_PERIOD_US;
  }
}
