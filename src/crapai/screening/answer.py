"""The model's answer: schema, validation, consistency check and quote check (plan chapter 10).

A language model answers in free text, so **nothing is taken on trust**. This module turns the
raw text into an :class:`Answer` or raises :class:`~crapai.errors.ParseError` (E304) that says
what was wrong, so the engine can ask again with that hint. There is never a silent default: a
broken, empty or cut-off answer is an error, not an "include" (the predecessor counted every
unreadable answer as an inclusion).

The schema follows chapter 10.3 and puts the decision **last**, after the per-criterion verdicts
and the reasoning, so the model "thinks" before it commits. Validation is done here in code because
some providers (SwissGPT) cannot enforce a JSON schema.

Two checks are made after a valid parse:

``consistent``
    The decision the model gave is compared with the one the verdicts imply (chapter 10.4).
    A difference is recorded, not corrected: the model's decision stays the default.
``quote_unverified``
    A quote the model cites must appear in the title or abstract (compared without case, blanks
    and punctuation). A quote that does not is flagged; it may be a paraphrase or an invention.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from crapai.errors import ParseError

SCHEMA_VERSION = 1
DECISIONS = ("INCLUDE", "EXCLUDE", "UNCERTAIN")
INCLUSION_VERDICTS = ("met", "not_met", "unclear")
EXCLUSION_VERDICTS = ("triggered", "not_triggered", "unclear")
MAX_NOTE = 200
MAX_QUOTE = 300
MAX_REASONING = 600

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["inclusion", "exclusion", "reasoning", "decision"],
    "properties": {
        "inclusion": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["criterion", "verdict", "note"],
                "properties": {
                    "criterion": {"type": "string"},
                    "verdict": {"enum": list(INCLUSION_VERDICTS)},
                    "note": {"type": "string", "maxLength": MAX_NOTE},
                    "quote": {"type": "string", "maxLength": MAX_QUOTE},
                },
            },
        },
        "exclusion": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["criterion", "verdict", "note"],
                "properties": {
                    "criterion": {"type": "string"},
                    "verdict": {"enum": list(EXCLUSION_VERDICTS)},
                    "note": {"type": "string", "maxLength": MAX_NOTE},
                    "quote": {"type": "string", "maxLength": MAX_QUOTE},
                },
            },
        },
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string", "maxLength": MAX_REASONING},
        "decision": {"enum": list(DECISIONS)},
    },
}


@dataclass(frozen=True)
class Verdict:
    """The model's verdict on one criterion."""

    criterion: str
    verdict: str
    note: str = ""
    quote: str = ""


@dataclass
class Answer:
    """A validated answer.

    Attributes:
        inclusion: Verdicts on the inclusion criteria.
        exclusion: Verdicts on the exclusion criteria.
        ambiguities: Open questions the model named.
        reasoning: The model's reasoning (at most 600 characters; longer text is cut).
        decision: ``INCLUDE``, ``EXCLUDE`` or ``UNCERTAIN`` as the model gave it.
        derived_decision: The decision the verdicts imply.
        consistent: Whether ``decision`` equals ``derived_decision``.
        unverified_quotes: Criteria whose quote is not in the record text.
    """

    inclusion: list[Verdict]
    exclusion: list[Verdict]
    reasoning: str
    decision: str
    ambiguities: list[str] = field(default_factory=list)
    derived_decision: str = ""
    consistent: bool = True
    unverified_quotes: list[str] = field(default_factory=list)


def _fail(reason: str) -> ParseError:
    return ParseError(
        f"The answer is not valid: {reason}",
        code="E304",
        hint="The model is asked again; if this keeps happening, try another model or prompt.",
        details={"reason": reason},
    )


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> Any:
    """The JSON value in a model answer (a markdown fence or text around it is tolerated).

    Raises:
        ParseError: E304 for an empty answer or text that holds no valid JSON.
    """
    stripped = _FENCE.sub("", text.strip()).strip()
    if not stripped:
        raise _fail("the answer is empty")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise _fail("it is not valid JSON")


def _verdicts(items: Any, name: str, allowed: tuple[str, ...]) -> list[Verdict]:
    if not isinstance(items, list):
        raise _fail(f"'{name}' must be a list")
    verdicts: list[Verdict] = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise _fail(f"{name}[{position}] must be an object")
        criterion, verdict = item.get("criterion"), item.get("verdict")
        if not isinstance(criterion, str) or not criterion.strip():
            raise _fail(f"{name}[{position}] has no criterion")
        if verdict not in allowed:
            raise _fail(f"{name}[{position}] verdict must be one of {', '.join(allowed)}")
        note, quote = item.get("note", ""), item.get("quote", "")
        if not isinstance(note, str) or not isinstance(quote, str):
            raise _fail(f"{name}[{position}] note and quote must be text")
        verdicts.append(Verdict(criterion.strip(), verdict, note[:MAX_NOTE], quote[:MAX_QUOTE]))
    return verdicts


def derive_decision(inclusion: list[Verdict], exclusion: list[Verdict]) -> str:
    """The decision the verdicts imply (plan 10.4).

    Any triggered exclusion means EXCLUDE; otherwise all inclusion criteria met means INCLUDE;
    otherwise a clearly unmet inclusion criterion means EXCLUDE; otherwise UNCERTAIN.
    """
    if any(v.verdict == "triggered" for v in exclusion):
        return "EXCLUDE"
    if inclusion and all(v.verdict == "met" for v in inclusion):
        return "INCLUDE"
    if any(v.verdict == "not_met" for v in inclusion):
        return "EXCLUDE"
    return "UNCERTAIN"


def parse_answer(text: str) -> Answer:
    """Validate a structured answer.

    Raises:
        ParseError: E304 with the reason in ``details["reason"]`` for anything that does not
            match the schema. Text that is too long is cut instead of refused (the limits are
            to keep the files small, not to catch errors).
    """
    data = extract_json(text)
    if not isinstance(data, dict):
        raise _fail("the top level must be an object")
    extra = sorted(set(data) - set(ANSWER_SCHEMA["properties"]))
    if extra:
        raise _fail(f"unknown field(s): {', '.join(extra)}")
    for required in ANSWER_SCHEMA["required"]:
        if required not in data:
            raise _fail(f"'{required}' is missing")
    decision = data["decision"]
    if decision not in DECISIONS:
        raise _fail(f"decision must be one of {', '.join(DECISIONS)}")
    reasoning = data["reasoning"]
    if not isinstance(reasoning, str):
        raise _fail("'reasoning' must be text")
    ambiguities = data.get("ambiguities", [])
    if not isinstance(ambiguities, list) or not all(isinstance(a, str) for a in ambiguities):
        raise _fail("'ambiguities' must be a list of text")
    inclusion = _verdicts(data["inclusion"], "inclusion", INCLUSION_VERDICTS)
    exclusion = _verdicts(data["exclusion"], "exclusion", EXCLUSION_VERDICTS)
    derived = derive_decision(inclusion, exclusion)
    return Answer(
        inclusion=inclusion,
        exclusion=exclusion,
        reasoning=reasoning[:MAX_REASONING],
        decision=decision,
        ambiguities=list(ambiguities),
        derived_decision=derived,
        consistent=decision == derived,
    )


_NON_WORD = re.compile(r"\W+", re.UNICODE)


def _squash(text: str) -> str:
    return _NON_WORD.sub("", text.casefold())


def check_quotes(answer: Answer, record_text: str) -> list[str]:
    """Criteria whose quote is not found in ``record_text``; sets ``answer.unverified_quotes``.

    Case, blanks and punctuation are ignored, so a quote with different line breaks still counts.
    An ellipsis (``...``) splits a quote into parts that must each be present.
    """
    haystack = _squash(record_text)
    missing: list[str] = []
    for verdict in [*answer.inclusion, *answer.exclusion]:
        if not verdict.quote.strip():
            continue
        parts = [p for p in re.split(r"\.\.\.|…", verdict.quote) if _squash(p)]
        if not all(_squash(part) in haystack for part in parts):
            missing.append(verdict.criterion)
    answer.unverified_quotes = missing
    return missing


LEGACY_DECISIONS = {"XXX": "EXCLUDE", "YYY": "INCLUDE"}


def parse_legacy(text: str) -> Answer:
    """Read the predecessor's format: the last line is only ``XXX`` (exclude) or ``YYY``.

    Raises:
        ParseError: E304 if the last line is neither (the predecessor counted that as an
            inclusion; here it is an error).
    """
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise _fail("the answer is empty")
    last = lines[-1].strip("'\"`*. ").upper()
    if last not in LEGACY_DECISIONS:
        raise _fail("the last line must be only XXX or YYY")
    decision = LEGACY_DECISIONS[last]
    return Answer(
        inclusion=[],
        exclusion=[],
        reasoning="\n".join(lines[:-1])[:MAX_REASONING],
        decision=decision,
        derived_decision=decision,
        consistent=True,
    )
