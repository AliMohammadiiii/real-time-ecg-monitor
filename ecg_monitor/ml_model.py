from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pickle

import numpy as np


class SklearnUnavailable(RuntimeError):
    pass


def _require_sklearn():
    try:
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise SklearnUnavailable("Install scikit-learn to use the exploratory ML module.") from exc
    return Pipeline, StandardScaler


def _build_estimator(model_type: str):
    """Return an sklearn estimator. LogisticRegression is the default."""
    if model_type == "logreg":
        from sklearn.linear_model import LogisticRegression
        return LogisticRegression(max_iter=1000, class_weight="balanced", random_state=7)
    if model_type == "linsvc":
        from sklearn.svm import LinearSVC
        return LinearSVC(class_weight="balanced", random_state=7)
    if model_type == "rf":
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(
            n_estimators=200, class_weight="balanced", random_state=7, n_jobs=-1
        )
    raise ValueError(f"Unknown model_type {model_type!r} (use logreg, linsvc, or rf)")


@dataclass
class ExploratoryMLWarningModel:
    """Non-diagnostic exploratory normal-like vs warning-like classifier."""

    pipeline: object | None = None
    model_type: str = "logreg"

    def fit(self, x: np.ndarray, y: np.ndarray, model_type: str | None = None) -> "ExploratoryMLWarningModel":
        Pipeline, StandardScaler = _require_sklearn()
        if model_type is not None:
            self.model_type = model_type
        self.pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("model", _build_estimator(self.model_type)),
            ]
        )
        self.pipeline.fit(x, y)
        return self

    def predict(self, x: np.ndarray, sqi_level: str = "usable_for_pqrst") -> np.ndarray:
        if sqi_level in {"unreliable", "poor"}:
            return np.asarray(["suppressed_low_sqi"] * len(x), dtype=object)
        if self.pipeline is None:
            raise RuntimeError("Model has not been fitted or loaded")
        return self.pipeline.predict(x)

    def predict_proba(self, x: np.ndarray, sqi_level: str = "usable_for_pqrst") -> np.ndarray | None:
        if sqi_level in {"unreliable", "poor"}:
            return None
        if self.pipeline is None:
            raise RuntimeError("Model has not been fitted or loaded")
        if hasattr(self.pipeline, "predict_proba"):
            return self.pipeline.predict_proba(x)
        return None

    def save(self, path: str | Path) -> None:
        if self.pipeline is None:
            raise RuntimeError("Cannot save an unfitted model")
        with Path(path).open("wb") as f:
            pickle.dump(self.pipeline, f)

    @classmethod
    def load(cls, path: str | Path) -> "ExploratoryMLWarningModel":
        with Path(path).open("rb") as f:
            pipeline = pickle.load(f)
        return cls(pipeline=pipeline)
