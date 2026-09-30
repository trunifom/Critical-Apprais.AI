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
