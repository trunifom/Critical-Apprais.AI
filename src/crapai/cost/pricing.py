"""Price sources (plan chapter 8.5).

Prices change and belong to the user, so they are **data**: an editable ``pricing.csv`` with the
columns ``provider, model, price_input_per_1k, price_output_per_1k, currency`` and the optional
columns ``valid_from`` and ``source``. ``templates/pricing.example.csv`` shows the format; its
values are illustrative only.

An unknown model has no price: callers then report tokens without a cost.
"""

from __future__ import annotations

import csv
import logging
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from crapai.errors import ConfigError

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("provider", "model", "price_input_per_1k", "price_output_per_1k")


@dataclass(frozen=True)
class Price:
    """Price of one model per 1000 tokens.

    Attributes:
        input_per_1k: Price of 1000 input tokens.
        output_per_1k: Price of 1000 output tokens.
        currency: Upper-case currency code such as ``USD`` or ``CHF``.
        valid_from: Date text from the price file ("" if none), shown in reports.
        source: Free text where the price comes from ("" if none).
    """

    input_per_1k: float
    output_per_1k: float
    currency: str = "USD"
    valid_from: str = ""
    source: str = ""


class PriceSource(Protocol):
    """Interface of a price lookup."""

    def get_price(self, provider: str, model: str) -> Price | None:
        """Return the price, or None if it is unknown."""
        ...


@dataclass(frozen=True)
class StaticPriceSource:
    """One price for every model; handy in tests and for a fixed agreement."""

    price: Price

    def get_price(self, provider: str, model: str) -> Price | None:
        """Return the fixed price."""
        return self.price


def parse_number(text: str | None) -> float | None:
    """Parse ``0.0006`` or ``0,0006``; None for empty, invalid, infinite, NaN or negative input."""
    if text is None:
        return None
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


class CsvPriceSource:
    """Prices from a ``pricing.csv`` file, read once on construction.

    Matching ignores case and surrounding blanks. The separator is a comma, or a semicolon if the
    header line has more semicolons than commas (Excel with a German locale saves that way).
    If a model appears in several rows, the row with the **latest** ``valid_from`` that is not in
    the future wins (a row without a date counts as the oldest; on a tie the first row wins), so a
    new price can be appended below an old one. Rows with a missing or invalid price are skipped
    with a warning in the log.

    Args:
        path: The CSV file.
        today: The date that decides which ``valid_from`` is already in force (for tests).

    Raises:
        ConfigError: E203 if the file cannot be read or lacks a required column.
    """

    def __init__(self, path: Path, *, today: date | None = None) -> None:
        self.path = path
        self._today = (today or date.today()).isoformat()
        self._prices: dict[tuple[str, str], Price] = {}
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                header = handle.readline()
                handle.seek(0)
                delimiter = ";" if header.count(";") > header.count(",") else ","
                reader = csv.DictReader(handle, delimiter=delimiter)
                fields = [(f or "").strip().lower() for f in reader.fieldnames or []]
                missing = [c for c in REQUIRED_COLUMNS if c not in fields]
                if missing:
                    raise ConfigError(
                        f"{path.name}: missing column(s) {', '.join(missing)}",
                        code="E203",
                        hint="Use the columns of templates/pricing.example.csv.",
                        details={"file": path.name, "missing": missing},
                    )
                for number, raw in enumerate(reader, start=2):
                    self._add(number, {(k or "").strip().lower(): v for k, v in raw.items()})
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise ConfigError(
                f"{path.name}: cannot read the price file ({exc.__class__.__name__})",
                code="E203",
                hint="Save the file as CSV in UTF-8.",
                details={"file": path.name},
            ) from exc

    def _add(self, line: int, row: dict[str, str | None]) -> None:
        provider = (row.get("provider") or "").strip().lower()
        model = (row.get("model") or "").strip().lower()
        price_in = parse_number(row.get("price_input_per_1k"))
        price_out = parse_number(row.get("price_output_per_1k"))
        if not provider or not model or price_in is None or price_out is None:
            logger.warning("%s line %d: skipped (no model or no valid price)", self.path.name, line)
            return
        price = Price(
            price_in,
            price_out,
            (row.get("currency") or "USD").strip().upper(),
            (row.get("valid_from") or "").strip(),
            (row.get("source") or "").strip(),
        )
        current = self._prices.get((provider, model))
        if current is None or self._rank(price) > self._rank(current):
            self._prices[(provider, model)] = price
        if current is not None:
            logger.info(
                "%s line %d: %s/%s appears more than once", self.path.name, line, provider, model
            )

    def _rank(self, price: Price) -> tuple[int, str]:
        """Sort key: prices already in force beat future ones, later dates beat earlier ones."""
        in_force = price.valid_from <= self._today  # "" (no date) is always in force, oldest
        return (1 if in_force else 0, price.valid_from if in_force else "")

    def __len__(self) -> int:
        return len(self._prices)

    def get_price(self, provider: str, model: str) -> Price | None:
        """Return the price of ``provider``/``model`` or None."""
        return self._prices.get((provider.strip().lower(), model.strip().lower()))
