"""Agreement between several screening runs: test-retest / inter-rater (plan chapter 14.1).

Compares the *decisions* (``INCLUDE``/``EXCLUDE``/``UNCERTAIN``) of two or more runs of the same
project, record by record (keyed by ``study_uid``). Only records that every compared run actually
decided (``status == "ok"`` and a known decision) are counted: a record one run never reached, or
answered with an error, is not a disagreement, it is simply not comparable yet.

This module is pure: no project, no file access. The caller (:mod:`crapai.services.results`)
supplies ``{run_id: {study_uid: decision}}``, built from one
:class:`crapai.screening.store.RunStore.last_results` per run.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations


def landis_koch_label(kappa: float) -> str:
    """The Landis & Koch (1977) interpretation of a kappa value."""
    if kappa < 0:
        return "poor"
    if kappa <= 0.20:
        return "slight"
    if kappa <= 0.40:
        return "fair"
    if kappa <= 0.60:
        return "moderate"
    if kappa <= 0.80:
        return "substantial"
    return "almost perfect"


def _common_items(
    decisions_by_run: Mapping[str, Mapping[str, str]], run_ids: Sequence[str]
) -> list[str]:
    """``study_uid`` decided in every one of ``run_ids``, sorted for a stable order."""
    if not run_ids:
        return []
    common = set(decisions_by_run.get(run_ids[0], {}))
    for run_id in run_ids[1:]:
        common &= set(decisions_by_run.get(run_id, {}))
    return sorted(common)


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Cohen's kappa for two equal-length, paired sequences of categorical labels.

    Returns:
        None if there is nothing to compare (empty input); 1.0 if the two sequences are identical
        and expected agreement by chance would be total (a single shared category); 0.0 if they
        disagree everywhere in that same degenerate case.
    """
    n = len(a)
    if n == 0 or n != len(b):
        return None
    po = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    counts_a, counts_b = Counter(a), Counter(b)
    categories = set(counts_a) | set(counts_b)
    pe = sum((counts_a.get(c, 0) / n) * (counts_b.get(c, 0) / n) for c in categories)
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


@dataclass(frozen=True)
class PairResult:
    """Agreement between two runs, on the records both of them decided.

    Attributes:
        run_a, run_b: The two run ids.
        n: Records both runs decided (``status == "ok"``, a known decision).
        agreement: Share of identical decisions, 0 to 1.
        kappa: Cohen's kappa, or None if ``n`` is 0.
        label: The Landis & Koch label of ``kappa``, or None.
    """

    run_a: str
    run_b: str
    n: int
    agreement: float
    kappa: float | None
    label: str | None


def pairwise(
    decisions_by_run: Mapping[str, Mapping[str, str]], run_ids: Sequence[str]
) -> list[PairResult]:
    """Agreement and Cohen's kappa for every pair of ``run_ids``, each on its own common records."""
    results: list[PairResult] = []
    for run_a, run_b in combinations(run_ids, 2):
        common = _common_items(decisions_by_run, [run_a, run_b])
        a = [decisions_by_run[run_a][u] for u in common]
        b = [decisions_by_run[run_b][u] for u in common]
        n = len(common)
        agreement = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n if n else 0.0
        kappa = cohens_kappa(a, b)
        label = landis_koch_label(kappa) if kappa is not None else None
        results.append(PairResult(run_a, run_b, n, agreement, kappa, label))
    return results


def fleiss_kappa(
    decisions_by_run: Mapping[str, Mapping[str, str]], run_ids: Sequence[str]
) -> tuple[float | None, int]:
    """Fleiss' kappa over all ``run_ids`` at once, on records every one of them decided.

    Returns:
        ``(kappa, n_items)``. ``kappa`` is None with fewer than 2 runs or no common record.
    """
    common = _common_items(decisions_by_run, run_ids)
    n_items, n_raters = len(common), len(run_ids)
    if n_items == 0 or n_raters < 2:
        return None, 0
    categories = sorted({decisions_by_run[r][u] for r in run_ids for u in common})
    if len(categories) < 2:
        return 1.0, n_items  # every run agreed on every record: nothing else to measure
    table = [
        [sum(1 for r in run_ids if decisions_by_run[r][u] == c) for c in categories]
        for u in common
    ]
    p_j = [sum(row[j] for row in table) / (n_items * n_raters) for j in range(len(categories))]
    p_i = [(sum(x * x for x in row) - n_raters) / (n_raters * (n_raters - 1)) for row in table]
    p_bar = sum(p_i) / n_items
    pe_bar = sum(p * p for p in p_j)
    if pe_bar >= 1.0:
        return (1.0 if p_bar >= 1.0 else 0.0), n_items
    return (p_bar - pe_bar) / (1.0 - pe_bar), n_items


@dataclass(frozen=True)
class UnstableRecord:
    """A record not every run decided the same way."""

    study_uid: str
    decisions: dict[str, str]


def unstable_records(
    decisions_by_run: Mapping[str, Mapping[str, str]], run_ids: Sequence[str]
) -> list[UnstableRecord]:
    """Records every run in ``run_ids`` decided, but not all the same way (``study_uid`` order)."""
    common = _common_items(decisions_by_run, run_ids)
    out: list[UnstableRecord] = []
    for uid in common:
        decisions = {run_id: decisions_by_run[run_id][uid] for run_id in run_ids}
        if len(set(decisions.values())) > 1:
            out.append(UnstableRecord(uid, decisions))
    return out


@dataclass(frozen=True)
class ComparisonSummary:
    """Full comparison of two or more runs.

    Attributes:
        run_ids: The compared runs, in the given order.
        n_common: Records every run decided (the basis of ``fleiss_kappa``).
        pairwise: One :class:`PairResult` per pair of runs (own common-record count each).
        fleiss_kappa: Agreement across all runs at once, or None (fewer than 2 runs, or no
            common record).
        fleiss_label: The Landis & Koch label of ``fleiss_kappa``, or None.
        unstable: Records every run decided, but not all the same way.
    """

    run_ids: tuple[str, ...]
    n_common: int
    pairwise: list[PairResult] = field(default_factory=list)
    fleiss_kappa: float | None = None
    fleiss_label: str | None = None
    unstable: list[UnstableRecord] = field(default_factory=list)


def compare(
    decisions_by_run: Mapping[str, Mapping[str, str]], run_ids: Sequence[str]
) -> ComparisonSummary:
    """Compare ``run_ids``: pairwise agreement and kappa, Fleiss' kappa, and unstable records."""
    run_ids = tuple(run_ids)
    kappa, n_common = fleiss_kappa(decisions_by_run, run_ids)
    return ComparisonSummary(
        run_ids=run_ids,
        n_common=n_common,
        pairwise=pairwise(decisions_by_run, run_ids),
        fleiss_kappa=kappa,
        fleiss_label=landis_koch_label(kappa) if kappa is not None else None,
        unstable=unstable_records(decisions_by_run, run_ids),
    )
