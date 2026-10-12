#!/usr/bin/env python3
"""
Unit tests for clustering_analysis.py.

Run with: python3 skills/scikit-learn/tests/test_clustering_analysis.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
import numpy as np
import pandas as pd
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from clustering_analysis import (  # noqa: E402
    preprocess_for_clustering,
    find_optimal_k_kmeans,
    compare_clustering_algorithms,
    complete_clustering_analysis,
)


def _make_blob_data(n_samples=100, n_features=4, centers=3, random_state=42):
    """Generate synthetic blob data for clustering."""
    from sklearn.datasets import make_blobs
    X, y = make_blobs(
        n_samples=n_samples,
        n_features=n_features,
        centers=centers,
        cluster_std=1.0,
        random_state=random_state
    )
    return X, y


def test_preprocess_for_clustering_scale_only():
    """Preprocessing scales data when scale=True, pca_components=None."""
    X, _ = _make_blob_data(n_samples=50, n_features=4, centers=3)
    X_processed = preprocess_for_clustering(X, scale=True, pca_components=None)

    assert X_processed.shape == (50, 4)
    # Check that data is standardized (mean ~0, std ~1)
    assert np.allclose(X_processed.mean(axis=0), 0, atol=1e-10)
    assert np.allclose(X_processed.std(axis=0), 1, atol=1e-10)


def test_preprocess_for_clustering_no_scale():
    """Preprocessing returns unchanged data when scale=False."""
    X, _ = _make_blob_data(n_samples=50, n_features=4, centers=3)
    X_processed = preprocess_for_clustering(X, scale=False, pca_components=None)

    assert X_processed.shape == (50, 4)
    # Data should be unchanged
    assert np.allclose(X_processed, X)


def test_preprocess_for_clustering_with_pca():
    """Preprocessing applies PCA when pca_components is set."""
    X, _ = _make_blob_data(n_samples=50, n_features=10, centers=3)
    X_processed = preprocess_for_clustering(X, scale=True, pca_components=3)

    assert X_processed.shape == (50, 3)


def test_preprocess_for_clustering_pca_without_scale():
    """PCA works without scaling."""
    X, _ = _make_blob_data(n_samples=50, n_features=10, centers=3)
    X_processed = preprocess_for_clustering(X, scale=False, pca_components=3)

    assert X_processed.shape == (50, 3)


def test_find_optimal_k_kmeans_returns_expected_keys():
    """find_optimal_k_kmeans returns dict with expected keys."""
    X, _ = _make_blob_data(n_samples=100, n_features=4, centers=3)
    X_scaled = preprocess_for_clustering(X, scale=True)

    results = find_optimal_k_kmeans(X_scaled, k_range=range(2, 6))

    assert "k_values" in results
    assert "inertias" in results
    assert "silhouette_scores" in results
    assert "best_k" in results
    assert len(results["k_values"]) == 4  # 2, 3, 4, 5
    assert len(results["inertias"]) == 4
    assert len(results["silhouette_scores"]) == 4
    assert results["best_k"] in results["k_values"]


def test_find_optimal_k_kmeans_inertia_decreases():
    """Inertia should generally decrease as K increases."""
    X, _ = _make_blob_data(n_samples=100, n_features=4, centers=3)
    X_scaled = preprocess_for_clustering(X, scale=True)

    results = find_optimal_k_kmeans(X_scaled, k_range=range(2, 6))

    # Inertia should be non-increasing
    for i in range(1, len(results["inertias"])):
        assert results["inertias"][i] <= results["inertias"][i - 1] + 1e-10


def test_compare_clustering_algorithms_returns_results():
    """compare_clustering_algorithms returns results for each algorithm."""
    X, _ = _make_blob_data(n_samples=100, n_features=4, centers=3)
    X_scaled = preprocess_for_clustering(X, scale=True)

    results = compare_clustering_algorithms(X_scaled, n_clusters=3)

    expected_algorithms = ["K-Means", "Agglomerative", "Gaussian Mixture"]
    for name in expected_algorithms:
        assert name in results
        assert "labels" in results[name]
        assert "silhouette" in results[name]
        assert "calinski_harabasz" in results[name]
        assert "davies_bouldin" in results[name]


def test_compare_clustering_algorithms_labels_shape():
    """Clustering labels have correct shape."""
    X, _ = _make_blob_data(n_samples=100, n_features=4, centers=3)
    X_scaled = preprocess_for_clustering(X, scale=True)

    results = compare_clustering_algorithms(X_scaled, n_clusters=3)

    for name, result in results.items():
        if name != "DBSCAN":  # DBSCAN handled separately
            assert len(result["labels"]) == 100
            assert result["n_clusters"] == 3


def test_compare_clustering_algorithms_dbscan_handled():
    """DBSCAN is included in results when it finds clusters."""
    X, _ = _make_blob_data(n_samples=200, n_features=4, centers=3)
    X_scaled = preprocess_for_clustering(X, scale=True)

    results = compare_clustering_algorithms(X_scaled, n_clusters=3)

    # DBSCAN may or may not be in results depending on data
    if "DBSCAN" in results:
        assert "labels" in results["DBSCAN"]
        assert "n_clusters" in results["DBSCAN"]
        assert "n_noise" in results["DBSCAN"]


def test_complete_clustering_analysis_returns_all_results():
    """complete_clustering_analysis returns all expected result components."""
    X, y = _make_blob_data(n_samples=100, n_features=4, centers=3)

    results = complete_clustering_analysis(
        X,
        true_labels=y,
        scale=True,
        find_k=True,
        k_range=range(2, 5),
        n_clusters=3
    )

    assert "X_processed" in results
    assert "optimization" in results
    assert "comparison" in results

    # Optimization results should be present
    assert results["optimization"] is not None
    assert "best_k" in results["optimization"]

    # Comparison should have all algorithms
    assert "K-Means" in results["comparison"]
    assert "Agglomerative" in results["comparison"]
    assert "Gaussian Mixture" in results["comparison"]


def test_complete_clustering_analysis_without_find_k():
    """complete_clustering_analysis works when find_k=False."""
    X, y = _make_blob_data(n_samples=100, n_features=4, centers=3)

    results = complete_clustering_analysis(
        X,
        true_labels=y,
        scale=True,
        find_k=False,
        n_clusters=3
    )

    assert "X_processed" in results
    assert results["optimization"] is None
    assert "comparison" in results


def test_complete_clustering_analysis_without_true_labels():
    """complete_clustering_analysis works without true labels."""
    X, _ = _make_blob_data(n_samples=100, n_features=4, centers=3)

    results = complete_clustering_analysis(
        X,
        true_labels=None,
        scale=True,
        find_k=True,
        k_range=range(2, 5),
        n_clusters=3
    )

    assert "X_processed" in results
    assert "optimization" in results
    assert "comparison" in results


def test_complete_clustering_analysis_scaling_option():
    """complete_clustering_analysis respects scale parameter."""
    X, _ = _make_blob_data(n_samples=50, n_features=4, centers=3)

    results_scaled = complete_clustering_analysis(X, scale=True, find_k=False, n_clusters=3)
    results_unscaled = complete_clustering_analysis(X, scale=False, find_k=False, n_clusters=3)

    # Scaled data should have mean ~0, std ~1
    assert np.allclose(results_scaled["X_processed"].mean(axis=0), 0, atol=1e-10)
    assert np.allclose(results_scaled["X_processed"].std(axis=0), 1, atol=1e-10)

    # Unscaled data should be unchanged
    assert np.allclose(results_unscaled["X_processed"], X)


def main() -> int:
    tests = [
        ("preprocess_for_clustering_scale_only", test_preprocess_for_clustering_scale_only),
        ("preprocess_for_clustering_no_scale", test_preprocess_for_clustering_no_scale),
        ("preprocess_for_clustering_with_pca", test_preprocess_for_clustering_with_pca),
        ("preprocess_for_clustering_pca_without_scale", test_preprocess_for_clustering_pca_without_scale),
        ("find_optimal_k_kmeans_returns_expected_keys", test_find_optimal_k_kmeans_returns_expected_keys),
        ("find_optimal_k_kmeans_inertia_decreases", test_find_optimal_k_kmeans_inertia_decreases),
        ("compare_clustering_algorithms_returns_results", test_compare_clustering_algorithms_returns_results),
        ("compare_clustering_algorithms_labels_shape", test_compare_clustering_algorithms_labels_shape),
        ("compare_clustering_algorithms_dbscan_handled", test_compare_clustering_algorithms_dbscan_handled),
        ("complete_clustering_analysis_returns_all_results", test_complete_clustering_analysis_returns_all_results),
        ("complete_clustering_analysis_without_find_k", test_complete_clustering_analysis_without_find_k),
        ("complete_clustering_analysis_without_true_labels", test_complete_clustering_analysis_without_true_labels),
        ("complete_clustering_analysis_scaling_option", test_complete_clustering_analysis_scaling_option),
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