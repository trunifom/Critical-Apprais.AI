"""Tests for test-retest / inter-rater agreement (plan chapter 14.1)."""

from __future__ import annotations

import pytest

from crapai.stats.agreement import (
    ComparisonSummary,
    cohens_kappa,
    compare,
    fleiss_kappa,
    landis_koch_label,
    pairwise,
    unstable_records,
)

# --- Landis & Koch label -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kappa,label",
    [
        (-0.5, "poor"),
        (0.0, "slight"),
        (0.2, "slight"),
        (0.21, "fair"),
        (0.4, "fair"),
        (0.41, "moderate"),
        (0.6, "moderate"),
        (0.61, "substantial"),
        (0.8, "substantial"),
        (0.81, "almost perfect"),
        (1.0, "almost perfect"),
    ],
)
def test_landis_koch_label_boundaries(kappa: float, label: str) -> None:
    assert landis_koch_label(kappa) == label


# --- Cohen's kappa --------------------------------------------------------------------------------


def test_cohens_kappa_of_identical_sequences_is_one() -> None:
    a = ["INCLUDE", "EXCLUDE", "INCLUDE", "UNCERTAIN"]
    assert cohens_kappa(a, a) == 1.0


def test_cohens_kappa_of_opposite_binary_sequences_is_minus_one() -> None:
    a = ["INCLUDE", "EXCLUDE"]
    b = ["EXCLUDE", "INCLUDE"]
    assert cohens_kappa(a, b) == pytest.approx(-1.0)


def test_cohens_kappa_handles_chance_agreement() -> None:
    # 10 items, 50/50 split, agreeing exactly on the expected-by-chance share.
    a = ["INCLUDE"] * 5 + ["EXCLUDE"] * 5
    b = ["INCLUDE"] * 3 + ["EXCLUDE"] * 2 + ["INCLUDE"] * 2 + ["EXCLUDE"] * 3
    kappa = cohens_kappa(a, b)
    assert kappa is not None and -1.0 <= kappa <= 1.0


def test_cohens_kappa_is_none_for_empty_or_mismatched_input() -> None:
    assert cohens_kappa([], []) is None
    assert cohens_kappa(["INCLUDE"], []) is None


def test_cohens_kappa_degenerate_single_category() -> None:
    # Both raters only ever say INCLUDE: no disagreement possible (pe == 1); perfect agreement.
    assert cohens_kappa(["INCLUDE"] * 3, ["INCLUDE"] * 3) == 1.0


# --- pairwise ---------------------------------------------------------------------------------


def test_pairwise_only_compares_records_both_runs_decided() -> None:
    decisions = {
        "r1": {"a": "INCLUDE", "b": "EXCLUDE", "c": "INCLUDE"},
        "r2": {"a": "INCLUDE", "b": "EXCLUDE"},  # "c" not screened by r2
    }
    (result,) = pairwise(decisions, ["r1", "r2"])
    assert result.n == 2 and result.agreement == 1.0 and result.kappa == 1.0
    assert result.label == "almost perfect"


def test_pairwise_covers_every_pair_of_three_runs() -> None:
    decisions = {
        "r1": {"a": "INCLUDE"},
        "r2": {"a": "EXCLUDE"},
        "r3": {"a": "INCLUDE"},
    }
    pairs = {(p.run_a, p.run_b) for p in pairwise(decisions, ["r1", "r2", "r3"])}
    assert pairs == {("r1", "r2"), ("r1", "r3"), ("r2", "r3")}


def test_pairwise_with_no_common_records_is_zero_not_a_crash() -> None:
    decisions = {"r1": {"a": "INCLUDE"}, "r2": {"b": "EXCLUDE"}}
    (result,) = pairwise(decisions, ["r1", "r2"])
    assert result.n == 0 and result.agreement == 0.0 and result.kappa is None


# --- Fleiss' kappa ------------------------------------------------------------------------------


def test_fleiss_kappa_of_a_hand_computed_example() -> None:
    # item "a": unanimous (3x A); item "b": 2x A, 1x B. Hand-computed kappa: -0.2.
    decisions = {
        "r1": {"a": "A", "b": "A"},
        "r2": {"a": "A", "b": "A"},
        "r3": {"a": "A", "b": "B"},
    }
    kappa, n = fleiss_kappa(decisions, ["r1", "r2", "r3"])
    assert n == 2
    assert kappa == pytest.approx(-0.2, abs=1e-9)


def test_fleiss_kappa_is_one_when_every_run_agrees_on_everything() -> None:
    decisions = {r: {"a": "INCLUDE", "b": "EXCLUDE"} for r in ("r1", "r2", "r3")}
    kappa, n = fleiss_kappa(decisions, ["r1", "r2", "r3"])
    assert kappa == 1.0 and n == 2


def test_fleiss_kappa_needs_at_least_two_runs_and_a_common_record() -> None:
    assert fleiss_kappa({"r1": {"a": "INCLUDE"}}, ["r1"]) == (None, 0)
    assert fleiss_kappa({"r1": {"a": "INCLUDE"}, "r2": {"b": "INCLUDE"}}, ["r1", "r2"]) == (
        None,
        0,
    )


# --- unstable records ---------------------------------------------------------------------------


def test_unstable_records_lists_only_disagreements_on_common_records() -> None:
    decisions = {
        "r1": {"a": "INCLUDE", "b": "EXCLUDE", "c": "INCLUDE"},
        "r2": {"a": "INCLUDE", "b": "INCLUDE", "c": "EXCLUDE"},
    }
    unstable = unstable_records(decisions, ["r1", "r2"])
    assert {u.study_uid for u in unstable} == {"b", "c"}
    by_uid = {u.study_uid: u.decisions for u in unstable}
    assert by_uid["b"] == {"r1": "EXCLUDE", "r2": "INCLUDE"}


def test_unstable_records_is_empty_when_everything_agrees() -> None:
    decisions = {"r1": {"a": "INCLUDE"}, "r2": {"a": "INCLUDE"}}
    assert unstable_records(decisions, ["r1", "r2"]) == []


# --- compare (the combined summary) --------------------------------------------------------------


def test_compare_bundles_pairwise_fleiss_and_unstable() -> None:
    decisions = {
        "r1": {"a": "INCLUDE", "b": "EXCLUDE"},
        "r2": {"a": "INCLUDE", "b": "INCLUDE"},
        "r3": {"a": "INCLUDE", "b": "EXCLUDE"},
    }
    summary = compare(decisions, ["r1", "r2", "r3"])
    assert isinstance(summary, ComparisonSummary)
    assert summary.run_ids == ("r1", "r2", "r3") and summary.n_common == 2
    assert len(summary.pairwise) == 3
    assert summary.fleiss_kappa is not None and summary.fleiss_label is not None
    assert {u.study_uid for u in summary.unstable} == {"b"}


def test_compare_with_a_single_run_has_no_fleiss_kappa() -> None:
    summary = compare({"r1": {"a": "INCLUDE"}}, ["r1"])
    assert summary.fleiss_kappa is None and summary.pairwise == [] and summary.unstable == []
