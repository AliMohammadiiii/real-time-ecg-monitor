import tempfile
import unittest
from pathlib import Path

import numpy as np

from ecg_monitor import ExploratoryMLWarningModel
from ecg_monitor.ml_model import SklearnUnavailable


class MLModelTests(unittest.TestCase):
    def test_model_train_predict_save_load_or_skip(self):
        try:
            model = ExploratoryMLWarningModel()
            x = np.asarray([[0.8, 0.8, 1, 75, 75, 0.01, 0.08, 1, 0.1, 1, 1, 1], [1.5, 1.5, 1, 40, 40, 0.02, 0.08, 1, 0.1, 1, 1, 1]])
            y = np.asarray(["normal_like", "warning_like"])
            model.fit(x, y)
        except SklearnUnavailable as exc:
            self.skipTest(str(exc))
        pred = model.predict(x)
        self.assertEqual(pred.shape[0], 2)
        suppressed = model.predict(x, sqi_level="poor")
        self.assertTrue(np.all(suppressed == "suppressed_low_sqi"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.pkl"
            model.save(path)
            loaded = ExploratoryMLWarningModel.load(path)
            self.assertEqual(loaded.predict(x).shape[0], 2)


if __name__ == "__main__":
    unittest.main()
