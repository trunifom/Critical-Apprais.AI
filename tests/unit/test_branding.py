from pathlib import Path

from crapai.branding import PREDECESSOR_NAMES, PRODUCT_NAME

SRC = Path(__file__).resolve().parents[2] / "src" / "crapai"


def test_product_name_is_exact_and_not_a_predecessor_name() -> None:
    assert PRODUCT_NAME == "Critical Apprais.AI"
    assert PRODUCT_NAME not in PREDECESSOR_NAMES


def test_ui_texts_do_not_call_the_product_sara() -> None:
    """User-visible YAML texts must not mention the predecessor name."""
    for yaml_file in (SRC / "i18n" / "texts").glob("*.yaml"):
        body = "".join(
            line
            for line in yaml_file.read_text(encoding="utf-8").splitlines(True)
            if not line.lstrip().startswith("#")
        )
        assert "SARA" not in body, yaml_file.name
