"""Tests for the error hierarchy (plan chapters 26.4 and 28.7)."""

from __future__ import annotations

import pytest

from crapai import errors
from crapai.errors import (
    AuthError,
    ConfigError,
    ContentRefused,
    ContextTooLong,
    EvaluationError,
    ImportFailed,
    ParseError,
    ProviderError,
    QuotaExceeded,
    RateLimited,
    SaraError,
    StorageError,
    TransientError,
)


def test_defaults_carry_code_message_hint_and_details() -> None:
    err = SaraError("boom", code="E203", hint="fix it", details={"path": "llm.rpm"})
    assert (err.code, err.user_message, err.hint) == ("E203", "boom", "fix it")
    assert err.details == {"path": "llm.rpm"}
    assert err.text_key == "errors.E203"
    assert str(err) == "[E203] boom"


def test_details_are_copied_not_shared() -> None:
    details = {"a": 1}
    err = SaraError("x", details=details)
    details["a"] = 2
    assert err.details == {"a": 1}


def test_base_class_defaults_to_unexpected_error_code() -> None:
    assert SaraError("x").code == errors.UNEXPECTED_ERROR_CODE == "E999"


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (ConfigError, "E203"),
        (ImportFailed, "E101"),
        (AuthError, "E301"),
        (RateLimited, "E302"),
        (ContextTooLong, "E303"),
        (ParseError, "E304"),
        (TransientError, "E305"),
        (ContentRefused, "E306"),
        (QuotaExceeded, "E307"),
        (StorageError, "E401"),
        (EvaluationError, "E501"),
    ],
)
def test_subclass_default_codes_follow_the_catalogue(cls: type[SaraError], code: str) -> None:
    assert cls("x").code == code


def test_provider_errors_share_a_base_class() -> None:
    provider_errors = (
        AuthError,
        RateLimited,
        TransientError,
        ContextTooLong,
        ContentRefused,
        QuotaExceeded,
    )
    for cls in provider_errors:
        assert issubclass(cls, ProviderError)
    assert not issubclass(ParseError, ProviderError)
    assert all(
        issubclass(c, SaraError) for c in (ConfigError, ImportFailed, ParseError, StorageError)
    )
