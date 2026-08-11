"""Tests for the AD8232 real-hardware log evaluator.

Uses the synthetic demo fixture under tests/fixtures/, so no hardware or network
is required.
"""

import importlib.util
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "demo_ad8232_log.csv"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evl = _load_script("evaluate_realtime_log")


class LogEvaluatorTests(unittest.TestCase):
    def test_evaluate_demo_fixture(self):
        result = evl.evaluate_log(FIXTURE)
        summary = result["summary"]
        self.assertGreater(summary["valid_samples"], 5000)
        self.assertGreaterEqual(summary["malformed_packets"], 2)  # injected malformed lines
        self.assertGreater(summary["dropped_packets"], 0)  # injected sequence gap
        self.assertAlmostEqual(summary["estimated_sampling_rate_hz"], 250.0, delta=5.0)
        self.assertGreaterEqual(summary["lead_off_period_count"], 1)

    def test_sequence_gap_detected(self):
        _samples, stats, _malformed = evl.parse_log(FIXTURE)
        self.assertGreater(stats.dropped_packets, 0)

    def test_lead_off_period_detection(self):
        flags = np.asarray([0, 0, 1, 1, 1, 0, 0, 1, 0], dtype=bool)
        ts = np.arange(flags.size, dtype=float)
        periods = evl.find_boolean_periods(flags, ts)
        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[0]["start_index"], 2)
        self.assertEqual(periods[0]["end_index"], 4)
        self.assertEqual(periods[1]["start_index"], 7)

    def test_lead_off_period_at_end(self):
        flags = np.asarray([0, 0, 1, 1], dtype=bool)
        ts = np.arange(flags.size, dtype=float)
        periods = evl.find_boolean_periods(flags, ts)
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["end_index"], 3)

    def test_jitter_stats(self):
        stats = evl.jitter_stats([4000, 4000, 4000, 4000])
        self.assertAlmostEqual(stats["mean_interval_us"], 4000.0)
        self.assertAlmostEqual(stats["std_jitter_us"], 0.0)
        self.assertAlmostEqual(stats["jitter_ratio"], 0.0)
        jittered = evl.jitter_stats([3900, 4100, 3800, 4200])
        self.assertGreater(jittered["std_jitter_us"], 0.0)

    def test_jitter_empty(self):
        stats = evl.jitter_stats([])
        self.assertIsNone(stats["mean_interval_us"])
        self.assertIsNone(stats["jitter_ratio"])

    def test_sqi_timeline_generation(self):
        result = evl.evaluate_log(FIXTURE, window_s=5.0)
        timeline = result["sqi_timeline"]
        self.assertGreaterEqual(len(timeline), 3)
        for w in timeline:
            self.assertIn(w["sqi_level"],
                          {"unreliable", "poor", "usable_for_rate_qrs", "usable_for_pqrst"})
            self.assertIn("warning_allowed", w)
        # At least one window should overlap the lead-off period and be suppressed.
        self.assertTrue(any(not w["warning_allowed"] for w in timeline))

    def test_no_crash_on_malformed_lines(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir) / "malformed.csv"
            tmp.write_text(
                "S,0,0,500,0,0\n"
                "not,a,valid,line\n"
                "S,1,4000,510,0,0\n"
                "garbage\n"
                "S,2,8000,520,0,0\n"
            )
            samples, stats, malformed = evl.parse_log(tmp)
            self.assertEqual(len(samples), 3)
            self.assertEqual(malformed, 2)


if __name__ == "__main__":
    unittest.main()
