"""Tests for QTDB fiducial parsing, matching, and the evaluation script.

These tests use mocked annotation objects and synthetic markers, so they run
without WFDB or internet access.
"""

import importlib.util
import unittest
from pathlib import Path

import numpy as np

from ecg_monitor.fiducials import (
    match_markers,
    parse_waveform_annotations,
    timing_error_stats,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QtdbParserTests(unittest.TestCase):
    def test_parses_triplet_structure(self):
        # Two beats: ( p ) ( N ) ( t )  ... ( p ) ( N ) ( t )
        samples = [10, 20, 30, 40, 50, 60, 70, 80, 90,
                   110, 120, 130, 140, 150, 160, 170, 180, 190]
        symbols = ["(", "p", ")", "(", "N", ")", "(", "t", ")",
                   "(", "p", ")", "(", "N", ")", "(", "t", ")"]
        ref = parse_waveform_annotations(samples, symbols)
        self.assertEqual(ref.p_peaks.tolist(), [20, 120])
        self.assertEqual(ref.qrs_peaks.tolist(), [50, 150])
        self.assertEqual(ref.t_peaks.tolist(), [80, 180])
        # QRS onset = "(" before N, offset = ")" after N.
        self.assertEqual(ref.qrs_onsets.tolist(), [40, 140])
        self.assertEqual(ref.qrs_offsets.tolist(), [60, 160])
        self.assertEqual(ref.n_unmapped, 0)

    def test_beat_symbols_other_than_normal(self):
        samples = [10, 20, 30]
        symbols = ["(", "V", ")"]
        ref = parse_waveform_annotations(samples, symbols)
        self.assertEqual(ref.qrs_peaks.tolist(), [20])
        self.assertEqual(ref.qrs_onsets.tolist(), [10])
        self.assertEqual(ref.qrs_offsets.tolist(), [30])

    def test_unknown_symbols_counted_not_faked(self):
        samples = [10, 20, 30]
        symbols = ["x", "N", "z"]
        ref = parse_waveform_annotations(samples, symbols)
        self.assertEqual(ref.qrs_peaks.tolist(), [20])
        self.assertEqual(ref.n_unmapped, 2)
        self.assertAlmostEqual(ref.unmapped_rate, 2 / 3, places=6)

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            parse_waveform_annotations([1, 2], ["("])


class MatchingTests(unittest.TestCase):
    def test_perfect_match_within_tolerance(self):
        predicted = [100, 200, 300]
        reference = [102, 198, 305]
        result = match_markers(predicted, reference, tolerance_samples=10)
        self.assertEqual(result.matched, 3)
        self.assertEqual(result.false_positive, 0)
        self.assertEqual(result.missing, 0)
        self.assertAlmostEqual(result.coverage, 1.0)
        # signed errors predicted - reference
        self.assertEqual(sorted(result.signed_errors_samples.tolist()), [-5, -2, 2])

    def test_tolerance_excludes_far_markers(self):
        result = match_markers([100], [500], tolerance_samples=10)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.false_positive, 1)
        self.assertEqual(result.missing, 1)

    def test_missing_and_false_positive_counts(self):
        result = match_markers([100, 400], [100, 200, 300], tolerance_samples=5)
        self.assertEqual(result.matched, 1)  # 100 matches
        self.assertEqual(result.false_positive, 1)  # 400 unmatched
        self.assertEqual(result.missing, 2)  # 200, 300 unmatched

    def test_empty_inputs(self):
        self.assertEqual(match_markers([], [1, 2], 5).missing, 2)
        self.assertEqual(match_markers([1, 2], [], 5).false_positive, 2)
        empty = match_markers([], [], 5)
        self.assertEqual(empty.matched, 0)
        self.assertEqual(empty.coverage, 0.0)

    def test_one_to_one_no_double_counting(self):
        # Two predictions near a single reference: only one should match.
        result = match_markers([100, 101], [100], tolerance_samples=5)
        self.assertEqual(result.matched, 1)
        self.assertEqual(result.false_positive, 1)


class MetricTests(unittest.TestCase):
    def test_timing_error_stats_ms_conversion(self):
        errors = np.asarray([2.0, -2.0, 4.0], dtype=float)
        stats = timing_error_stats(errors, sampling_rate=250.0)
        self.assertEqual(stats["n"], 3)
        # mean abs = 8/3 samples -> * (1000/250)=4 ms/sample
        self.assertAlmostEqual(stats["mae_samples"], 8 / 3, places=6)
        self.assertAlmostEqual(stats["mae_ms"], (8 / 3) * 4.0, places=6)
        self.assertAlmostEqual(stats["median_ae_ms"], 2.0 * 4.0, places=6)

    def test_empty_errors_return_none(self):
        stats = timing_error_stats(np.asarray([], dtype=float), 250.0)
        self.assertEqual(stats["n"], 0)
        self.assertIsNone(stats["mae_ms"])


class ScriptGracefulTests(unittest.TestCase):
    def test_script_reports_when_dataset_unavailable(self):
        module = _load_script("evaluate_qtdb")

        def _boom(*args, **kwargs):
            raise module.DatasetUnavailable("simulated missing dataset")

        module._load_qtdb_record = _boom
        rc = module.main(["--record", "sel100"])
        self.assertEqual(rc, 2)  # graceful non-crash exit code


if __name__ == "__main__":
    unittest.main()
