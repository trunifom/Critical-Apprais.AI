"""Which records may go to the model, and how good is their abstract (plan chapters 8.4 and 26.3).

Records are **marked, never removed**. A record that must not be sent to the model gets an
``exclusion_reason`` with details; it stays in ``records.csv`` and in the result table.

Reasons owned by this module (``VALIDITY_REASONS``), in priority order:

``NOT_SCREENABLE``
    The title names front or back matter and not a study ("Front-matter", "Index", "Table of
    contents", "Cover"). Only a title that consists of exactly such a phrase counts.
``RETRACTED``
    A retracted publication, only when ``exclude_retracted`` is switched on. Otherwise a retracted
    study stays in and is only flagged (``is_retracted``), so it is never included unnoticed.
``NO_ABSTRACT``
    No abstract text. Switched off by ``include_title_only`` (then the model sees the title alone).

Reasons set elsewhere are never overwritten: ``DUPLICATE`` (dedup), ``EMPTY_RECORD`` and
``IMPORT_ERROR`` (import). ``mark_duplicates`` may replace a validity reason by ``DUPLICATE``,
because PRISMA removes duplicates first. Run order: import, dedup, validity.

``abstract_quality`` is a hint for the preflight, never a reason to exclude:

``ok``
    normal abstract
``short``
    fewer than :data:`SHORT_ABSTRACT_WORDS` words (often a note or a truncated field)
``suspect_concat``
    the text looks garbled or glued together: a "word" longer than :data:`LONG_WORD_LETTERS`
    letters (40; the plan says 25, but ordinary German compounds such as
    "Verarbeitungsgeschwindigkeit" have 28), or a very high average word length. Missing spaces
    inside ordinary-length words (the Cochrane example "stressmanagement") cannot be detected
    without a dictionary and are **not** flagged.
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from crapai.io.records_store import Record
from crapai.prisma.dedup import normalize_title
from crapai.prisma.reasons import (
    REASON_NO_ABSTRACT,
    REASON_NOT_SCREENABLE,
    REASON_RETRACTED,
    VALIDITY_REASONS,
)

logger = logging.getLogger(__name__)

QUALITY_OK = "ok"
_UNSPACED_SCRIPTS = re.compile(
    r"[\u0e00-\u0e7f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]"
)
SHORT_ABSTRACT_CHARS_UNSPACED = 120  # about 40 words of English, counted in characters
QUALITY_SHORT = "short"
QUALITY_SUSPECT = "suspect_concat"

# The plan gives no threshold for "short"; 20 words is a working value, evidence in the tests:
# the shortest real abstracts of the fixtures have 18 (a MEDLINE note) and 2 words (a broken field).
SHORT_ABSTRACT_WORDS = 40
LONG_WORD_LETTERS = 40  # the plan names 25; German compounds reach 28+, see the tests
GARBLED_MEAN_WORD_LETTERS = 9.0  # natural text, incl. German compounds, stays below ~8
MIN_WORDS_FOR_MEAN = 30

# Titles that are front or back matter. Compared after normalisation (case, punctuation, accents).
NOT_SCREENABLE_TITLES: frozenset[str] = frozenset(
    {
        "front matter",
        "frontmatter",
        "back matter",
        "backmatter",
        "index",
        "author index",
        "subject index",
        "table of contents",
        "contents",
        "cover",
        "cover page",
        "title page",
        "copyright page",
    }
)

_LETTER_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass(frozen=True)
class QualityThresholds:
    """The numbers behind the abstract-quality hint; ``quality:`` in ``project.yaml``.

    Attributes:
        long_word_letters: A single word longer than this looks glued together.
        short_abstract_words: Fewer words than this counts as ``short``.
        garbled_mean_word_letters: A higher mean word length (with enough words) looks garbled.
        min_words_for_mean: Fewer words than this are too few to judge the mean word length.
        short_abstract_chars_unspaced: ``short`` limit in characters for scripts without spaces.
    """

    long_word_letters: int = LONG_WORD_LETTERS
    short_abstract_words: int = SHORT_ABSTRACT_WORDS
    garbled_mean_word_letters: float = GARBLED_MEAN_WORD_LETTERS
    min_words_for_mean: int = MIN_WORDS_FOR_MEAN
    short_abstract_chars_unspaced: int = SHORT_ABSTRACT_CHARS_UNSPACED


@dataclass(frozen=True)
class ValidityConfig:
    """Options of the validity check.

    Attributes:
        include_title_only: Do not flag records without abstract; they go to the model by title.
        exclude_retracted: Mark retracted publications as ``RETRACTED`` (else only flagged).
        not_screenable_titles: Normalised whole titles that are not studies.
        quality: Thresholds of the abstract-quality hint.
    """

    include_title_only: bool = False
    exclude_retracted: bool = False
    not_screenable_titles: frozenset[str] = NOT_SCREENABLE_TITLES
    quality: QualityThresholds = field(default_factory=lambda: QualityThresholds())


@dataclass
class ValidityResult:
    """Outcome of one run.

    Attributes:
        records: All records in the original order with reasons and quality set.
        by_reason: Number of records that carry each reason after the run (also reasons set
            elsewhere, so the numbers add up to the records that do not go to the model).
        quality: Abstract quality counts (records with an abstract only).
        valid_for_model: Records without any exclusion reason.
    """

    records: list[Record]
    by_reason: dict[str, int] = field(default_factory=dict)
    quality: dict[str, int] = field(default_factory=dict)
    valid_for_model: int = 0


def is_not_screenable(title: str, config: ValidityConfig | None = None) -> bool:
    """True if the whole title is a front/back-matter phrase such as "Front-matter" or "Index"."""
    titles = (config or ValidityConfig()).not_screenable_titles
    return normalize_title(title) in titles


def _is_unspaced_script(text: str) -> bool:
    """True if most letters belong to a script that is written without spaces between words."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    wide = sum(1 for ch in letters if _UNSPACED_SCRIPTS.match(ch))
    return wide / len(letters) > 0.5


def classify_abstract(abstract: str, thresholds: QualityThresholds | None = None) -> str:
    """Quality of an abstract: ``""`` (none), ``ok``, ``short`` or ``suspect_concat``."""
    limits = thresholds or QualityThresholds()
    text = abstract.strip()
    if not text:
        return ""
    if _is_unspaced_script(text):
        # Chinese, Japanese, Korean and Thai are written without spaces: a "word" is a whole
        # sentence, so the word-based checks would call every abstract garbled or short.
        return QUALITY_OK if len(text) >= limits.short_abstract_chars_unspaced else QUALITY_SHORT
    letters = [len(word) for word in _LETTER_WORDS.findall(text)]
    if letters and max(letters) > limits.long_word_letters:
        return QUALITY_SUSPECT
    garbled = statistics.mean(letters) > limits.garbled_mean_word_letters if letters else False
    if len(letters) >= limits.min_words_for_mean and garbled:
        return QUALITY_SUSPECT
    if len(text.split()) < limits.short_abstract_words:
        return QUALITY_SHORT
    return QUALITY_OK


def _reason_for(record: Record, config: ValidityConfig) -> tuple[str, str] | None:
    """The validity reason and its details for one record, or None."""
    if is_not_screenable(record.title, config):
        return REASON_NOT_SCREENABLE, f"title is front or back matter: {record.title.strip()!r}"
    if config.exclude_retracted and record.is_retracted:
        return REASON_RETRACTED, "retracted publication"
    if not record.abstract.strip() and not config.include_title_only:
        return REASON_NO_ABSTRACT, "no abstract"
    return None


def mark_validity(records: list[Record], config: ValidityConfig | None = None) -> ValidityResult:
    """Set ``exclusion_reason``, ``has_abstract`` and ``abstract_quality`` for all records.

    Earlier validity reasons are recomputed from scratch (so switching an option works);
    reasons set by other steps are kept. The input list and its records are not modified.
    """
    config = config or ValidityConfig()
    result = ValidityResult(records=[])
    reasons: Counter[str] = Counter()
    quality: Counter[str] = Counter()
    for record in records:
        update: dict[str, object] = {}
        has_abstract = bool(record.abstract.strip())
        if record.has_abstract != has_abstract:
            update["has_abstract"] = has_abstract
        grade = classify_abstract(record.abstract, config.quality)
        if record.abstract_quality != grade:
            update["abstract_quality"] = grade
        if grade:
            quality[grade] += 1

        current = record.exclusion_reason
        if current in VALIDITY_REASONS:
            current = ""
            update["exclusion_reason"] = ""
            update["exclusion_details"] = ""
        if not current:
            found = _reason_for(record, config)
            if found is not None:
                current = found[0]
                update["exclusion_reason"], update["exclusion_details"] = found
        result.records.append(record.model_copy(update=update) if update else record)
        if current:
            reasons[current] += 1
        else:
            result.valid_for_model += 1
    result.by_reason = dict(reasons)
    result.quality = dict(quality)
    logger.info(
        "Validity: %d of %d records go to the model; reasons %s",
        result.valid_for_model,
        len(records),
        dict(reasons),
    )
    return result
