// Multi-scenario ECG packet player for validating the Python live monitor.
//
// Output packet:
//   S,<seq>,<micros>,<adc>,<lo_plus>,<lo_minus>
//
// Send one character over Serial to select a mode:
//   0 normal_75
//   1 brady_45
//   2 tachy_125
//   3 irregular_rr
//   4 wide_qrs
//   5 noisy
//   6 lead_off
//
// This is an educational simulator, not physiological or diagnostic data.

const unsigned long SAMPLE_RATE_HZ = 250;
const unsigned long SAMPLE_PERIOD_US = 1000000UL / SAMPLE_RATE_HZ;

struct Scenario {
  const char* name;
  float bpm;
  float p_amp;
  float q_amp;
  float r_amp;
  float s_amp;
  float t_amp;
  float qrs_width_scale;
  int noise;
  bool irregular;
  bool lead_off;
};

Scenario scenarios[] = {
  {"normal_75",   75.0f, 34.0f, -42.0f, 260.0f, -70.0f, 82.0f, 1.0f,  3, false, false},
  {"brady_45",    45.0f, 34.0f, -42.0f, 260.0f, -70.0f, 82.0f, 1.0f,  3, false, false},
  {"tachy_125",  125.0f, 28.0f, -42.0f, 260.0f, -70.0f, 72.0f, 1.0f,  3, false, false},
  {"irregular_rr", 82.0f, 32.0f, -42.0f, 260.0f, -70.0f, 82.0f, 1.0f,  3, true,  false},
  {"wide_qrs",    75.0f, 30.0f, -38.0f, 230.0f, -60.0f, 78.0f, 2.8f,  3, false, false},
  {"noisy",       75.0f, 30.0f, -42.0f, 245.0f, -70.0f, 82.0f, 1.0f, 12, false, false},
  {"lead_off",    75.0f,  0.0f,   0.0f,   0.0f,   0.0f,  0.0f, 1.0f,  1, false, true},
};

const int SCENARIO_COUNT = sizeof(scenarios) / sizeof(scenarios[0]);
const float irregular_rr_s[] = {0.72f, 1.18f, 0.58f, 0.96f, 0.80f, 1.28f};
const int IRREGULAR_COUNT = sizeof(irregular_rr_s) / sizeof(irregular_rr_s[0]);

unsigned long next_sample_us = 0;
unsigned long sequence = 0;
int scenario_index = 0;
int beat_sample = 0;
int rr_samples = 200;
int irregular_index = 0;

static float bump(float t, float c, float w) {
  const float x = (t - c) / w;
  return expf(-0.5f * x * x);
}

static int scenarioRrSamples() {
  const Scenario& s = scenarios[scenario_index];
  if (s.irregular) {
    return max(1, (int)(irregular_rr_s[irregular_index] * (float)SAMPLE_RATE_HZ));
  }
  return max(1, (int)((60.0f / s.bpm) * (float)SAMPLE_RATE_HZ));
}

static void resetScenario(int next_index) {
  if (next_index < 0 || next_index >= SCENARIO_COUNT) {
    return;
  }
  scenario_index = next_index;
  beat_sample = 0;
  irregular_index = 0;
  rr_samples = scenarioRrSamples();
  Serial.print("#MODE,");
  Serial.print(scenario_index);
  Serial.print(',');
  Serial.println(scenarios[scenario_index].name);
}

static void handleSerialCommand() {
  while (Serial.available() > 0) {
    const char c = (char)Serial.read();
    if (c >= '0' && c <= '6') {
      resetScenario(c - '0');
    }
  }
}

static int simulatedAdc() {
  const Scenario& s = scenarios[scenario_index];
  if (s.lead_off) {
    return 512 + random(-2, 3);
  }

  const float t = (float)beat_sample;
  const float rr = (float)rr_samples;
  float v = 512.0f;

  v += 10.0f * sinf(2.0f * PI * ((float)sequence / (4.0f * SAMPLE_RATE_HZ)));
  const float r_center = 0.36f * rr;
  const float q_center = r_center - 0.030f * rr * s.qrs_width_scale;
  const float s_center = r_center + 0.030f * rr * s.qrs_width_scale;
  v += s.p_amp * bump(t, 0.18f * rr, 0.030f * rr);
  v += s.q_amp * bump(t, q_center, 0.010f * rr * s.qrs_width_scale);
  v += s.r_amp * bump(t, 0.36f * rr, 0.008f * rr * s.qrs_width_scale);
  v += s.s_amp * bump(t, s_center, 0.012f * rr * s.qrs_width_scale);
  v += s.t_amp * bump(t, 0.58f * rr, 0.052f * rr);
  v += (float)random(-s.noise, s.noise + 1);

  int adc = (int)v;
  if (adc < 0) adc = 0;
  if (adc > 1023) adc = 1023;
  return adc;
}

void setup() {
  Serial.begin(115200);
  randomSeed(analogRead(A0));
  next_sample_us = micros();
  resetScenario(0);
}

void loop() {
  handleSerialCommand();

  const unsigned long now = micros();
  if ((long)(now - next_sample_us) < 0) {
    return;
  }

  const int adc = simulatedAdc();
  const int lead_off = scenarios[scenario_index].lead_off ? 1 : 0;

  Serial.print("S,");
  Serial.print(sequence++);
  Serial.print(',');
  Serial.print(now);
  Serial.print(',');
  Serial.print(adc);
  Serial.print(',');
  Serial.print(lead_off);
  Serial.print(',');
  Serial.println(lead_off);

  beat_sample++;
  if (beat_sample >= rr_samples) {
    beat_sample = 0;
    if (scenarios[scenario_index].irregular) {
      irregular_index = (irregular_index + 1) % IRREGULAR_COUNT;
    }
    rr_samples = scenarioRrSamples();
  }

  next_sample_us += SAMPLE_PERIOD_US;
  if ((long)(now - next_sample_us) > (long)SAMPLE_PERIOD_US) {
    next_sample_us = now + SAMPLE_PERIOD_US;
  }
}
