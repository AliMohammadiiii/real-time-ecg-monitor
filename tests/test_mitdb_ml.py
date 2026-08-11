"""Tests for MIT-BIH patient-wise ML data prep and the ML scripts.

Network access is avoided by monkeypatching the WFDB loader with synthetic data.
"""

import importlib.util
import unittest
from pathlib import Path

import numpy as np

from ecg_monitor import ExploratoryMLWarningModel, mitdb_ml
from ecg_monitor.ml_features import FEATURE_NAMES
from ecg_monitor.ml_model import SklearnUnavailable
from ecg_monitor.synthetic import synthetic_ecg

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_loader(label_symbol):
    """Return a fake _load_wfdb producing a synthetic record with given beat symbols."""
    def loader(record, lead, seconds, local_dir):
        fs = 360.0
        signal, r = synthetic_ecg(duration_s=20.0, sampling_rate=fs, heart_rate_bpm=72.0)
        samples = np.asarray(r, dtype=int)
        symbols = [label_symbol] * len(samples)
        return signal, fs, samples, symbols
    return loader


class SplitTests(unittest.TestCase):
    def test_ds1_ds2_no_overlap(self):
        self.assertEqual(set(mitdb_ml.DS1) & set(mitdb_ml.DS2), set())
        self.assertEqual(len(mitdb_ml.DS1), 22)
        self.assertEqual(len(mitdb_ml.DS2), 22)


class LabelMappingTests(unittest.TestCase):
    def test_binary_mapping(self):
        self.assertEqual(mitdb_ml.map_label("N", "binary"), "normal_like")
        self.assertEqual(mitdb_ml.map_label("L", "binary"), "normal_like")
        self.assertEqual(mitdb_ml.map_label("V", "binary"), "warning_like")
        self.assertEqual(mitdb_ml.map_label("A", "binary"), "warning_like")
        self.assertEqual(mitdb_ml.map_label("F", "binary"), "warning_like")
        self.assertIsNone(mitdb_ml.map_label("/", "binary"))  # Q group skipped in binary
        self.assertIsNone(mitdb_ml.map_label("+", "binary"))  # non-beat

    def test_aami_mapping(self):
        self.assertEqual(mitdb_ml.map_label("N", "aami"), "N")
        self.assertEqual(mitdb_ml.map_label("A", "aami"), "S")
        self.assertEqual(mitdb_ml.map_label("V", "aami"), "V")
        self.assertEqual(mitdb_ml.map_label("E", "aami"), "V")
        self.assertEqual(mitdb_ml.map_label("F", "aami"), "F")
        self.assertEqual(mitdb_ml.map_label("/", "aami"), "Q")
        self.assertIsNone(mitdb_ml.map_label("~", "aami"))


class FeatureTableTests(unittest.TestCase):
    def test_feature_table_shape(self):
        original = mitdb_ml._load_wfdb
        mitdb_ml._load_wfdb = _fake_loader("N")
        try:
            ds = mitdb_ml.build_record_dataset("999", scheme="binary", seconds=20.0)
        finally:
            mitdb_ml._load_wfdb = original
        self.assertEqual(ds.features.shape[1], len(FEATURE_NAMES))
        self.assertEqual(ds.features.shape[0], ds.labels.shape[0])
        self.assertGreater(ds.features.shape[0], 5)
        self.assertTrue(np.all(np.isfinite(ds.features)))

    def test_build_dataset_groups_align(self):
        original = mitdb_ml._load_wfdb
        mitdb_ml._load_wfdb = _fake_loader("V")
        try:
            x, y, groups, skipped, per_record = mitdb_ml.build_dataset(
                ["101", "106"], scheme="binary", seconds=20.0
            )
        finally:
            mitdb_ml._load_wfdb = original
        self.assertEqual(x.shape[0], len(y))
        self.assertEqual(x.shape[0], len(groups))
        self.assertEqual(set(groups), {"101", "106"})
        self.assertTrue(np.all(y == "warning_like"))


class MLSuppressionTests(unittest.TestCase):
    def test_low_sqi_suppresses_advisory(self):
        try:
            model = ExploratoryMLWarningModel()
            x = np.random.default_rng(0).normal(size=(6, len(FEATURE_NAMES)))
            y = np.asarray(["normal_like", "warning_like"] * 3)
            model.fit(x, y)
        except SklearnUnavailable as exc:
            self.skipTest(str(exc))
        suppressed = model.predict(x, sqi_level="poor")
        self.assertTrue(np.all(suppressed == "suppressed_low_sqi"))
        self.assertIsNone(model.predict_proba(x, sqi_level="unreliable"))


class ScriptGracefulTests(unittest.TestCase):
    def test_train_mitdb_graceful_when_unavailable(self):
        module = _load_script("train_ml_warning_model")

        def _boom(*a, **k):
            raise module.mitdb_ml.DatasetUnavailable("simulated")

        module.mitdb_ml.build_dataset = _boom
        rc = module.main(["--source", "mitdb", "--records", "101"])
        self.assertEqual(rc, 2)

    def test_train_and_eval_synthetic_still_work(self):
        import tempfile

        train = _load_script("train_ml_warning_model")
        ev = _load_script("evaluate_ml_warning_model")
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "m.pkl"
            summary = Path(tmp) / "s.json"
            try:
                rc = train.main(["--source", "synthetic", "--output", str(model_path),
                                 "--summary-json", str(summary)])
            except SystemExit as exc:  # sklearn missing
                self.skipTest(str(exc))
            self.assertEqual(rc, 0)
            self.assertTrue(model_path.exists())
            rc2 = ev.main(["--source", "synthetic", "--model", str(model_path),
                           "--output-json", str(Path(tmp) / "r.json"),
                           "--output-csv", str(Path(tmp) / "r.csv")])
            self.assertEqual(rc2, 0)


if __name__ == "__main__":
    unittest.main()
