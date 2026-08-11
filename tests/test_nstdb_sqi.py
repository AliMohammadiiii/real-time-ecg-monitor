"""Tests for the NSTDB SQI noise stress-test helpers and script.

These tests use synthetic signals only, so they run without WFDB or internet.
"""

import importlib.util
import unittest
from pathlib import Path

import numpy as np

from ecg_monitor import assess_signal_quality
from ecg_monitor.synthetic import synthetic_ecg

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nstdb = _load_script("evaluate_nstdb_sqi")


class NoiseMetricTests(unittest.TestCase):
    def test_clean_signal_high_sqi(self):
        signal, _ = synthetic_ecg(duration_s=10.0, sampling_rate=250.0, noise_std=0.01)
        result = nstdb.evaluate_window(signal, 250.0)
        self.assertGreaterEqual(result["sqi_score"], 0.45)
        self.assertIn(result["sqi_level"], {"usable_for_rate_qrs", "usable_for_pqrst"})

    def test_noisy_signal_lowers_sqi(self):
        clean, _ = synthetic_ecg(duration_s=10.0, sampling_rate=250.0, noise_std=0.01)
        noisy, _ = synthetic_ecg(duration_s=10.0, sampling_rate=250.0, noise_std=0.30)
        clean_sqi = nstdb.evaluate_window(clean, 250.0)["sqi_score"]
        noisy_sqi = nstdb.evaluate_window(noisy, 250.0)["sqi_score"]
        self.assertLess(noisy_sqi, clean_sqi)

    def test_flatline_is_unreliable(self):
        result = nstdb.evaluate_window(np.ones(2500), 250.0)
        self.assertEqual(result["sqi_level"], "unreliable")
        self.assertFalse(result["warning_allowed"])

    def test_clipping_is_unreliable(self):
        # A rail-to-rail clipped signal via the SQI adc bounds.
        clipped = np.full(1000, 1023.0)
        sqi = assess_signal_quality(clipped, adc_min=0, adc_max=1023)
        self.assertEqual(sqi.level, "unreliable")
        self.assertFalse(sqi.warning_allowed)

    def test_warning_suppressed_under_poor_sqi(self):
        # Lead-off is a hard rejection -> unreliable -> warnings suppressed.
        signal, _ = synthetic_ecg(duration_s=6.0, sampling_rate=250.0)
        sqi = assess_signal_quality(signal, lead_off=True)
        self.assertIn(sqi.level, {"unreliable", "poor"})
        self.assertFalse(sqi.warning_allowed)

    def test_baseline_wander_score_increases_with_drift(self):
        fs = 250.0
        t = np.arange(0, 10, 1 / fs)
        clean, _ = synthetic_ecg(duration_s=10.0, sampling_rate=fs, noise_std=0.01)
        drift = clean + 2.0 * np.sin(2 * np.pi * 0.15 * t)
        self.assertGreater(
            nstdb.baseline_wander_score(drift, fs),
            nstdb.baseline_wander_score(clean, fs),
        )

    def test_snr_parsing(self):
        self.assertEqual(nstdb.snr_from_record("118e24"), 24)
        self.assertEqual(nstdb.snr_from_record("118e00"), 0)
        self.assertEqual(nstdb.snr_from_record("118e_6"), -6)
        self.assertIsNone(nstdb.snr_from_record("118"))

    def test_rr_plausibility_bounds(self):
        # 250 Hz, 1 s spacing -> 60 bpm, all plausible.
        peaks = np.arange(0, 2500, 250)
        self.assertAlmostEqual(nstdb.rr_plausibility_score(peaks, 250.0), 1.0)


class ScriptGracefulTests(unittest.TestCase):
    def test_script_reports_when_dataset_unavailable(self):
        def _boom(*args, **kwargs):
            raise nstdb.DatasetUnavailable("simulated missing dataset")

        nstdb._load_nstdb_record = _boom
        rc = nstdb.main(["--records", "118e24", "--seconds", "5"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
