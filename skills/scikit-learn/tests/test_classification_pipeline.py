#!/usr/bin/env python3
"""
Unit tests for classification_pipeline.py.

Run with: python3 skills/scikit-learn/tests/test_classification_pipeline.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
import numpy as np
import pandas as pd
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from classification_pipeline import create_preprocessing_pipeline, train_and_evaluate_model  # noqa: E402


def _make_classification_data(n_samples=200, n_features=5, n_classes=2, random_state=42):
    """Generate synthetic classification data with mixed numeric/categorical features."""
    rng = np.random.default_rng(random_state)
    X = pd.DataFrame(
        rng.normal(0, 1, (n_samples, n_features)),
        columns=[f"num_{i}" for i in range(n_features)]
    )
    # Add categorical features
    X["cat_0"] = rng.choice(["A", "B", "C"], n_samples)
    X["cat_1"] = rng.choice(["X", "Y"], n_samples)
    y = pd.Series(rng.integers(0, n_classes, n_samples))
    return X, y


def test_create_preprocessing_pipeline_numeric_only():
    """Preprocessing pipeline works with only numeric features."""
    numeric_features = ["num_0", "num_1"]
    categorical_features = []

    preprocessor = create_preprocessing_pipeline(numeric_features, categorical_features)

    assert preprocessor is not None
    # ColumnTransformer always has both transformers; check numeric has features
    transformer_dict = {t[0]: t[2] for t in preprocessor.transformers}
    assert "num" in transformer_dict
    assert list(transformer_dict["num"]) == ["num_0", "num_1"]
    assert list(transformer_dict["cat"]) == []


def test_create_preprocessing_pipeline_mixed():
    """Preprocessing pipeline works with mixed numeric and categorical features."""
    numeric_features = ["num_0", "num_1"]
    categorical_features = ["cat_0", "cat_1"]

    preprocessor = create_preprocessing_pipeline(numeric_features, categorical_features)

    assert preprocessor is not None
    assert len(preprocessor.transformers) == 2
    transformer_names = {t[0] for t in preprocessor.transformers}
    assert transformer_names == {"num", "cat"}


def test_create_preprocessing_pipeline_categorical_only():
    """Preprocessing pipeline works with only categorical features."""
    numeric_features = []
    categorical_features = ["cat_0", "cat_1"]

    preprocessor = create_preprocessing_pipeline(numeric_features, categorical_features)

    assert preprocessor is not None
    # ColumnTransformer always has both transformers; check categorical has features
    transformer_dict = {t[0]: t[2] for t in preprocessor.transformers}
    assert "cat" in transformer_dict
    assert list(transformer_dict["cat"]) == ["cat_0", "cat_1"]
    assert list(transformer_dict["num"]) == []


def test_train_and_evaluate_model_binary_classification():
    """Complete pipeline runs and returns expected results for binary classification."""
    X, y = _make_classification_data(n_samples=200, n_features=3, n_classes=2, random_state=42)
    numeric_features = ["num_0", "num_1", "num_2"]
    categorical_features = ["cat_0", "cat_1"]

    results = train_and_evaluate_model(
        X, y, numeric_features, categorical_features,
        test_size=0.2, random_state=42
    )

    assert "model" in results
    assert "y_test" in results
    assert "y_pred" in results
    assert "y_pred_proba" in results
    assert "metrics" in results

    metrics = results["metrics"]
    assert "accuracy" in metrics
    assert "precision" in metrics
    assert "recall" in metrics
    assert "f1" in metrics

    # Metrics should be valid
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert 0.0 <= metrics["precision"] <= 1.0
    assert 0.0 <= metrics["recall"] <= 1.0
    assert 0.0 <= metrics["f1"] <= 1.0


def test_train_and_evaluate_model_multiclass():
    """Pipeline works with multiclass classification."""
    X, y = _make_classification_data(n_samples=200, n_features=3, n_classes=3, random_state=42)
    numeric_features = ["num_0", "num_1", "num_2"]
    categorical_features = ["cat_0", "cat_1"]

    results = train_and_evaluate_model(
        X, y, numeric_features, categorical_features,
        test_size=0.2, random_state=42
    )

    assert "metrics" in results
    metrics = results["metrics"]
    assert 0.0 <= metrics["accuracy"] <= 1.0


def test_train_and_evaluate_model_handles_missing_values():
    """Pipeline handles missing values in numeric features."""
    X, y = _make_classification_data(n_samples=100, n_features=2, n_classes=2, random_state=42)
    X.loc[0, "num_0"] = np.nan
    X.loc[1, "num_1"] = np.nan

    numeric_features = ["num_0", "num_1"]
    categorical_features = ["cat_0", "cat_1"]

    results = train_and_evaluate_model(
        X, y, numeric_features, categorical_features,
        test_size=0.2, random_state=42
    )

    assert "model" in results
    metrics = results["metrics"]
    assert 0.0 <= metrics["accuracy"] <= 1.0


def test_train_and_evaluate_model_stratified_split():
    """Train/test split preserves class distribution."""
    X, y = _make_classification_data(n_samples=200, n_features=2, n_classes=2, random_state=42)
    numeric_features = ["num_0", "num_1"]
    categorical_features = ["cat_0", "cat_1"]

    results = train_and_evaluate_model(
        X, y, numeric_features, categorical_features,
        test_size=0.25, random_state=42
    )

    y_test = results["y_test"]
    # Test set should have both classes (stratified)
    assert len(np.unique(y_test)) == 2


def test_train_and_evaluate_model_returns_model_with_predict_method():
    """Returned model has predict and predict_proba methods."""
    X, y = _make_classification_data(n_samples=100, n_features=2, n_classes=2, random_state=42)
    numeric_features = ["num_0", "num_1"]
    categorical_features = ["cat_0", "cat_1"]

    results = train_and_evaluate_model(
        X, y, numeric_features, categorical_features,
        test_size=0.2, random_state=42
    )

    model = results["model"]
    assert hasattr(model, "predict")
    assert hasattr(model, "predict_proba")
    assert callable(model.predict)
    assert callable(model.predict_proba)


def main() -> int:
    tests = [
        ("create_preprocessing_pipeline_numeric_only", test_create_preprocessing_pipeline_numeric_only),
        ("create_preprocessing_pipeline_mixed", test_create_preprocessing_pipeline_mixed),
        ("create_preprocessing_pipeline_categorical_only", test_create_preprocessing_pipeline_categorical_only),
        ("train_and_evaluate_model_binary_classification", test_train_and_evaluate_model_binary_classification),
        ("train_and_evaluate_model_multiclass", test_train_and_evaluate_model_multiclass),
        ("train_and_evaluate_model_handles_missing_values", test_train_and_evaluate_model_handles_missing_values),
        ("train_and_evaluate_model_stratified_split", test_train_and_evaluate_model_stratified_split),
        ("train_and_evaluate_model_returns_model_with_predict_method", test_train_and_evaluate_model_returns_model_with_predict_method),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())