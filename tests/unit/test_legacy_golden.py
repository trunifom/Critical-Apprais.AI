"""Golden test: reproduce the SARA-App test-retest reports from the archived legacy runs."""

from pathlib import Path

import pandas as pd
import pytest

from saralocal.legacy import cohen_kappa, interpret_kappa, load_runs, pairwise_stats

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ["project-01_dhl", "project-02_dhl", "project-03_dhem"]


@pytest.mark.parametrize("project", PROJECTS)
def test_test_retest_matches_archived_report(project: str) -> None:
    expected_file = next((ROOT / "expected" / project).glob("*.csv"))
    expected = pd.read_csv(expected_file)
    actual = pairwise_stats(load_runs(ROOT / "legacy_runs" / project))
    assert list(actual["run1"]) == list(expected["run1"])
    assert list(actual["run2"]) == list(expected["run2"])
    assert list(actual["n_overlap"]) == list(expected["n_overlap"])
    pd.testing.assert_series_equal(
        actual["percent_agreement"], expected["percent_agreement"], check_exact=False, atol=1e-4
    )
    pd.testing.assert_series_equal(
        actual["cohen_kappa"], expected["cohen_kappa"], check_exact=False, atol=1e-4
    )
    assert list(actual["interpretation"]) == list(expected["interpretation"])


def test_kappa_basics() -> None:
    a = pd.Series([1, 1, 0, 0])
    assert cohen_kappa(a, a) == 1.0
    assert cohen_kappa(a, 1 - a) == -1.0
    assert interpret_kappa(0.95) == "Almost Perfect"
    assert interpret_kappa(-0.1) == "Poor"
    assert interpret_kappa(cohen_kappa(pd.Series([1, 1]), pd.Series([1, 1]))) == "Undefined"
