"""Tests for the NBIB/MEDLINE reader (task T-M1-06, plan chapter 25.3)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from crapai.errors import ImportFailed
from crapai.io.readers.detect import SourceFormat, detect_format
from crapai.io.readers.nbib import parse_nbib_text, read_nbib

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
EXPECTED = json.loads((DATA / "EXPECTED.json").read_text(encoding="utf-8"))
NBIB_FIXTURES = sorted(
    name.removeprefix("data/")
    for name, info in EXPECTED.items()
    if name.startswith("data/") and info.get("kind") == "nbib"
)


def raw_lines(name: str) -> list[str]:
    return (DATA / name).read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")


@pytest.mark.parametrize("name", NBIB_FIXTURES)
def test_record_counts_equal_the_oracle(name: str) -> None:
    result = read_nbib(DATA / name)
    assert result.format is SourceFormat.NBIB
    assert len(result.records) == EXPECTED[f"data/{name}"]["records"]
    assert [r.source_row for r in result.records] == list(range(1, len(result.records) + 1))


def test_acceptance_100_and_62_records() -> None:
    assert len(read_nbib(DATA / "pubmed-adhd-set.nbib").records) == 100
    assert len(read_nbib(DATA / "pubmed-adhdANDchi-set.nbib").records) == 62


def test_ris_named_copy_reads_identically() -> None:
    """The same bytes saved as .ris give the same result once detect_format says NBIB."""
    assert detect_format(DATA / "pubmed-adhd-set.ris").format is SourceFormat.NBIB
    a = read_nbib(DATA / "pubmed-adhd-set.nbib")
    b = read_nbib(DATA / "pubmed-adhd-set.ris")
    assert [r.fields for r in a.records] == [r.fields for r in b.records]


def test_abstracts_doi_and_pmid_equal_independent_line_counts() -> None:
    """Oracle computed from the raw lines, not from the parser."""
    lines = raw_lines("pubmed-adhd-set.nbib")
    ab_lines = sum(1 for ln in lines if ln.startswith("AB  - "))
    pmids = [ln[6:].strip() for ln in lines if ln.startswith("PMID- ")]
    result = read_nbib(DATA / "pubmed-adhd-set.nbib")
    assert sum(1 for r in result.records if r.fields.get("abstract")) == ab_lines == 94
    assert [r.fields["pmid"] for r in result.records] == pmids
    # every record's DOI comes from a LID/AID line with the [doi] marker
    doi_records = sum(1 for r in result.records if r.fields.get("doi"))
    text = "\n".join(lines)
    blocks = [b for b in text.split("\n\n") if b.startswith("PMID- ")]
    assert doi_records == sum(1 for b in blocks if re.search(r"^(LID|AID) - .+\[doi\]", b, re.M))


def test_wrapped_abstract_lines_are_joined() -> None:
    result = read_nbib(DATA / "pubmed-adhd-set.nbib")
    first = result.records[0].fields
    assert first["pmid"] == "32559806"
    assert first["title"].startswith("ADHD: Current Concepts")
    assert first["abstract"].startswith("Attention deficit hyperactivity disorder (ADHD)")
    assert "\n" not in first["abstract"] and "  " not in first["abstract"]
    assert first["abstract"].endswith("their evidence base.")
    assert first["doi"] == "10.1055/s-0040-1701658"
    assert first["year"] == 2020 and first["pmcid"] == "PMC7508636"


def test_full_authors_publication_types_and_lists() -> None:
    first = read_nbib(DATA / "pubmed-adhd-set.nbib").records[0].fields
    assert first["authors"].startswith("Drechsler, Renate; Brem, Silvia")  # FAU, not "Drechsler R"
    assert first["publication_types"] == "Journal Article; Review"
    assert first["journal"] == "Neuropediatrics"
    assert first["keywords_mesh"].startswith("Adolescent; Attention Deficit Disorder")
    assert first["language"] == "eng"


def test_admin_tags_are_kept_in_extra() -> None:
    record = read_nbib(DATA / "pubmed-adhd-set.nbib").records[0]
    for tag in ("OWN", "STAT", "DCOM", "LR", "DP", "AD", "AUID", "DEP"):
        assert f"nbib_{tag}" in record.extra, tag
    assert record.extra["nbib_DP"] == "2020 Oct"  # full date, only the year is a field
    assert record.extra["nbib_OWN"] == "NLM"


SAMPLE = (
    "PMID- 111\n"
    "TI  - A study\n"
    "      continued title\n"
    "LID - S0001 [pii]\n"
    "LID - 10.1000/abc [doi]\n"
    "AID - 10.1000/abc [doi]\n"
    "DP  - 2021 Oct-Dec\n"
    "AU  - Doe J\n"
    "FAU - Doe, Jane\n"
    "AU  - Roe R\n"
    "FAU - Roe, Rick\n"
    "PT  - Journal Article\n"
    "PT  - Retracted Publication\n"
    "OT  - alpha\n"
    "OT  - beta\n"
    "\n"
    "PMID- 222\n"
    "TT  - Translated only\n"
    "AU  - Solo A\n"
    "PT  - Letter\n"
    "\n"
    "PMID- 333\n"
    "TI  - Retracted: Something\n"
    "PT  - Journal Article\n"
)


def test_sample_mapping_rules() -> None:
    first, second, third = parse_nbib_text(SAMPLE).records
    f = first.fields
    assert f["title"] == "A study continued title"
    assert f["doi"] == "10.1000/abc" and first.extra["nbib_AID"] == "S0001 [pii]"
    assert f["year"] == 2021 and first.extra["nbib_DP"] == "2021 Oct-Dec"
    assert f["authors"] == "Doe, Jane; Roe, Rick"
    assert f["keywords"] == "alpha; beta"
    assert f["record_type"] == "journal_article"
    assert f["is_retracted"] is True and any("Retracted Publication" in n for n in first.notes)

    assert second.fields["title"] == "Translated only"  # TT as fallback
    assert "title_translated" not in second.fields
    assert second.fields["authors"] == "Solo A"  # AU when no FAU
    assert second.fields["record_type"] == "other" and second.fields["is_retracted"] is False
    assert "abstract" not in second.fields  # letters have no abstract

    assert third.fields["is_retracted"] is True  # title pattern "Retracted:"
    assert any("Retracted:" in n for n in third.notes)  # last record without trailing blank line


def test_translated_title_is_kept_next_to_original() -> None:
    record = parse_nbib_text("PMID- 1\nTI  - Original\nTT  - Translated\n").records[0]
    assert record.fields["title"] == "Original"
    assert record.fields["title_translated"] == "Translated"


def test_retraction_notice_and_plain_records_are_distinguished() -> None:
    notice = parse_nbib_text("PMID- 1\nTI  - T\nPT  - Retraction of Publication\n").records[0]
    assert notice.fields["is_retracted"] is True
    text = "PMID- 2\nTI  - Retraction of vaccine myths\nPT  - Review\n"
    plain = parse_nbib_text(text).records[0]
    assert plain.fields["is_retracted"] is False  # the word alone does not flag a record


def test_fixture_has_no_retractions_and_all_records_have_the_flag() -> None:
    records = read_nbib(DATA / "pubmed-adhd-set.nbib").records
    assert all(isinstance(r.fields["is_retracted"], bool) for r in records)


def test_repeated_single_tags_keep_the_extra_value() -> None:
    record = parse_nbib_text("PMID- 1\nTI  - T\nVI  - 5\nVI  - 6\n").records[0]
    assert record.fields["volume"] == "5" and record.extra["nbib_VI"] == "6"


def test_no_pmid_raises_e102_and_ris_is_not_nbib() -> None:
    for text in ("", "some prose\n", "TY  - JOUR\nTI  - T\nER  - \n"):
        with pytest.raises(ImportFailed) as info:
            parse_nbib_text(text)
        assert info.value.code == "E102"
    with pytest.raises(ImportFailed):
        read_nbib(DATA / "example_AB_nr4.ris")


def test_encoding_is_reported_and_forced_encoding_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "x.nbib"
    path.write_bytes("PMID- 1\r\nTI  - Größe\r\n".encode("cp1252"))
    assert read_nbib(path).encoding == "cp1252"
    assert read_nbib(path).records[0].fields["title"] == "Größe"
    with pytest.raises(ImportFailed) as info:
        read_nbib(path, encoding="ascii")
    assert info.value.code == "E103"
