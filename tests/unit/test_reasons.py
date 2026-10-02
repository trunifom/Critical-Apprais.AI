"""The reason catalogue that the steps share (plan chapter 26.3, ADR 0018)."""

from __future__ import annotations

from crapai.io.records_store import EXCLUSION_REASONS
from crapai.prisma import reasons


def test_every_reason_constant_is_in_the_persisted_catalogue() -> None:
    constants = {getattr(reasons, name) for name in dir(reasons) if name.startswith("REASON_")}
    assert constants <= EXCLUSION_REASONS  # a reason not in the catalogue would not load back
    assert constants >= reasons.VALIDITY_REASONS


def test_validity_reasons_are_exactly_the_three_of_the_validity_step() -> None:
    assert {"NOT_SCREENABLE", "RETRACTED", "NO_ABSTRACT"} == reasons.VALIDITY_REASONS
    assert {"DUPLICATE", "EMPTY_RECORD", "IMPORT_ERROR"}.isdisjoint(reasons.VALIDITY_REASONS)


def test_ai_prefilter_reason_is_its_own_tier_not_touched_by_the_automatic_chain() -> None:
    """ADR 0029: AI_PREFILTER_JEV is never run by 'crapai check'/'crapai screen', so it must not
    be clearable or replaceable by the steps those commands do run automatically."""
    assert {"AI_PREFILTER_JEV"} == reasons.AI_PREFILTER_REASONS
    assert reasons.AI_PREFILTER_REASONS.isdisjoint(reasons.PREFILTER_REASONS)
    assert reasons.AI_PREFILTER_REASONS.isdisjoint(reasons.VALIDITY_REASONS)
    assert reasons.AI_PREFILTER_REASONS.isdisjoint(reasons.REPLACEABLE_BY_DEDUP)
