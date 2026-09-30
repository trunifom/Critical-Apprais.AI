from crapai.i18n import I18n


def test_english_texts_load_and_format() -> None:
    i18n = I18n()
    i18n.load("en")
    assert i18n.t("sections.project.header")
    assert "x.ris" in i18n.tf("sections.upload.abstract.database_field.label", filename="x.ris")
    assert ".ris" in i18n.lst("sections.upload.abstract.file_type.options")


def test_unknown_language_falls_back_to_english() -> None:
    i18n = I18n()
    i18n.load("xx")
    assert i18n.t("sections.project.header")


def test_validate_reports_missing_keys() -> None:
    i18n = I18n()
    i18n.load("en")
    assert i18n.validate(["sections.project.header", "does.not.exist"]) == ["does.not.exist"]
