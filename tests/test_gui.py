"""Tests for the live GUI logic.

The PyQtGraph rendering itself is not exercised here (it needs a Qt binding and a
display); these tests cover the data source, the per-window analysis, empty and
poor-SQI handling, and the graceful behaviour when GUI deps are missing.
"""

import unittest

import numpy as np

from ecg_monitor import gui
from ecg_monitor.gui import (
    SAFETY_TEXT,
    SUPPRESSED_TEXT,
    ChunkResult,
    DatasetReplaySource,
    DemoSignalSource,
    analyze_window,
    pyqtgraph_available,
    _relative_marker_indices,
)
from ecg_monitor.synthetic import synthetic_ecg


class ImportGuardTests(unittest.TestCase):
    def test_pyqtgraph_available_is_bool(self):
        self.assertIsInstance(pyqtgraph_available(), bool)

    def test_run_gui_graceful_without_pyqtgraph(self):
        if pyqtgraph_available():
            self.skipTest("PyQtGraph is installed; graceful-missing path not applicable")
        rc = gui.run_gui(DemoSignalSource(), fs=250.0)
        self.assertEqual(rc, 1)  # exits gracefully, does not crash


class DemoSourceTests(unittest.TestCase):
    def test_demo_chunk_has_expected_fields(self):
        source = DemoSignalSource(fs=250.0, chunk_seconds=0.2)
        chunk = source.read_chunk()
        self.assertIsInstance(chunk, ChunkResult)
        self.assertEqual(chunk.samples.size, int(0.2 * 250.0))
        self.assertTrue(np.all(chunk.samples >= 0) and np.all(chunk.samples <= 1023))
        self.assertIsInstance(chunk.lead_off, bool)
        self.assertIsInstance(chunk.packet_loss_rate, float)

    def test_demo_source_streams_continuously(self):
        source = DemoSignalSource(fs=250.0, chunk_seconds=0.2)
        first = source.read_chunk().samples
        second = source.read_chunk().samples
        self.assertEqual(first.size, second.size)  # wraps without error

    def test_dataset_replay_source_loops_with_metadata(self):
        samples = np.arange(100, dtype=float)
        source = DatasetReplaySource(samples=samples, fs=100.0, chunk_seconds=0.2, name="fixture")
        chunk = source.read_chunk()
        self.assertEqual(chunk.samples.size, 20)
        self.assertEqual(source.current_scenario_info()["mode"], "Dataset replay")
        for _ in range(8):
            chunk = source.read_chunk()
        self.assertEqual(chunk.samples.size, 20)


class AnalyzeWindowTests(unittest.TestCase):
    def test_clean_window_detects_beats(self):
        signal, _ = synthetic_ecg(duration_s=10.0, sampling_rate=250.0)
        adc = np.clip(np.round(512 + signal * 300), 0, 1023).astype(float)
        result = analyze_window(adc, 250.0)
        self.assertGreater(result.r_peaks.size, 5)
        self.assertIsNotNone(result.hr_bpm)
        self.assertIn("Usable", result.sqi_label)
        self.assertFalse(result.warning_suppressed)

    def test_empty_detection_handled(self):
        result = analyze_window(np.zeros(10), 250.0)  # too short / flat
        self.assertEqual(result.r_peaks.size, 0)
        self.assertEqual(result.markers, [])
        self.assertTrue(result.warning_suppressed)

    def test_poor_sqi_suppresses_warning(self):
        signal, _ = synthetic_ecg(duration_s=6.0, sampling_rate=250.0)
        adc = np.clip(np.round(512 + signal * 300), 0, 1023).astype(float)
        result = analyze_window(adc, 250.0, lead_off=True)
        self.assertTrue(result.warning_suppressed)
        self.assertEqual(result.warning_label, SUPPRESSED_TEXT)

    def test_no_ml_advisory_without_model(self):
        signal, _ = synthetic_ecg(duration_s=8.0, sampling_rate=250.0)
        adc = np.clip(np.round(512 + signal * 300), 0, 1023).astype(float)
        result = analyze_window(adc, 250.0, ml_model=None)
        self.assertIsNone(result.ml_advisory)

    def test_safety_text_constants(self):
        self.assertIn("not a medical device", SAFETY_TEXT)
        self.assertIn("suppressed", SUPPRESSED_TEXT.lower())

    def test_absolute_markers_track_scrolling_buffer(self):
        markers_abs = np.asarray([100, 125, 150, 175, 200])
        relative = _relative_marker_indices(markers_abs, buffer_start_abs=140, buffer_size=50)
        np.testing.assert_array_equal(relative, np.asarray([10, 35]))


if __name__ == "__main__":
    unittest.main()
