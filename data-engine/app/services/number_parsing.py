"""Locale-aware number parsing for financial amounts.

One parser, one set of rules, used by every ingestion path. The previous state
of the codebase had three independent implementations, and two of them stripped
every comma, which is wrong for a product that reads Spanish-language filings
(CNMV, ESEF) and Spanish-locale broker exports:

* ``"0,24"``  -> ``24``     (100x)
* ``"1.234,56"`` -> ``1.23456``  (1000x)

and the validation in those paths agreed the Spanish form was well formed, so
the corruption was persisted.

Rules
-----
* both separators present: the LAST one is the decimal separator
  (``1.234,56`` and ``1,234.56`` both mean 1234.56)
* a single separator followed by 1-2 digits is a decimal separator (``0,24``)
* a single separator followed by exactly 3 digits is a thousands separator
  (``1,234`` and ``1.250``) unless the integer part is 0 (``0,250`` and
  ``0.250`` are 0.25: no thousands group starts with 0), and a repeated
  separator is grouping
  (``1.234.567``); without this, ``(1.250)`` thousand became -1.25 instead of
  -1.250.000 and es-ES grouping was rejected outright
* parentheses around the whole token mean negative (accounting notation)
* non-breaking and regular spaces are thousands separators
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# A single comma followed by one or two digits: a decimal separator.
_DECIMAL_COMMA = re.compile(r"^[-+]?\d+,\d{1,2}$")
# Parte entera formada solo por ceros y UN separador decimal ("0.250"): no
# puede ser agrupacion de miles, porque un grupo inicial nunca es 0.
_ZERO_INTEGER = re.compile(r"^0+\.\d+$")
# A numeric token, optionally signed, with digits and separators only.
_NUMERIC = re.compile(r"^[-+]?\d[\d.,\s\u00a0]*$")
# A run of digits and separators inside free text, keeping the sign and the
# accounting parentheses of the number it belongs to: the class has no space,
# so a token can never span the gap between two figures of a sentence.
# A sign only starts a token when it does not follow a digit: in "5-10 %",
# "2023-2024" or "2024-03-31" the hyphen is a range or date separator, and
# reading it as a minus produced figures of -10, -2024 and -31 that the KPI
# grounding accepted as negative values stated by the quote.
_NUMBER_RUN = re.compile(r"\(?\s*(?:(?<!\d)[-+])?\d[\d.,]*\)?")
# A space that separates thousands INSIDE one number ("1 234 567,89"), never
# two numbers of a sentence. The left side must not end in a separator, because
# "en 2024, 1.234,5 millones" is two figures and merging them yields the
# nonsense 20241.2345; the right side must be a group of exactly three digits,
# so "12,5 % 3" and "1 2345" are left alone.
_SPACE_THOUSANDS = re.compile(r"(?<!\d[.,])[ \u00a0](?=\d{3}(?!\d))")
# Typographic minus signs. PDF, ESEF and CNMV text writes a negative figure with
# U+2212 (or its small/full-width forms) rather than the ASCII hyphen, and the
# numeric patterns only know ``-``: "−3,2 %" was read as +3,2, a silent sign
# flip that let a wrong-signed KPI ground against the quote. Each maps to one
# ASCII ``-`` so character offsets (the unit windows) are unchanged.
_MINUS_SIGNS = str.maketrans({"\u2212": "-", "\ufe63": "-", "\uff0d": "-"})


def _not_a_thousands_group(raw: str, separator: str) -> bool:
    """A SINGLE separator that cannot be thousands grouping, so it is decimal.

    A thousands group is exactly three digits and the leading group has one to
    three: "1,2345" (an es-ES FX rate or 4-decimal price) and "1234,567" (es-ES
    without grouping) were read as 12345 and 1234567, errors of x10.000 and
    x1.000. Only the one-separator case is decided here; repeated separators
    keep their grouping reading.
    """
    if raw.count(separator) != 1:
        return False
    integer, fraction = raw.split(separator)
    return len(fraction) != 3 or len(integer) > 3


def parse_machine_decimal(value: object) -> Decimal | None:
    """Decimal from a machine-shaped value (JSON/XML numbers from APIs).

    The companion to ``parse_localized_number``: that one reads free text with
    locale rules; this one reads values that are already numeric (or numeric
    strings with a machine decimal point) from SEC facts, broker payloads and
    ingestion rows. ``None`` and empty/invalid input mean "no data" and return
    ``None`` - never ``0``, which would be a real figure.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def find_number_tokens(text: object) -> list[str]:
    """Every numeric token in free text, in order of appearance.

    Splitting on a naive ``[\\d.,\\s]+`` run merges the figures of a Spanish
    sentence, because its comma AND its space are both inside that class:
    ``"en 2024, 1.234,5 millones"`` collapses to a single token, and the
    accounting parentheses of ``"(1.250)"`` are lost along the way. This
    tokenizer joins a space only when it is a thousands boundary inside one
    number, and keeps each token's own sign, so every figure stays its own
    parseable token.
    """
    if text is None:
        return []
    joined = _SPACE_THOUSANDS.sub("", str(text).translate(_MINUS_SIGNS))
    return [token.strip() for token in _NUMBER_RUN.findall(joined)]


def parse_localized_number(value: object) -> tuple[Decimal, bool] | None:
    """Parse a number written in en-US or es-ES notation.

    Returns ``(value, is_negative)`` or ``None`` when the token is not a
    number. The sign is returned separately because accounting parentheses and
    a leading minus mean the same thing but are written differently.
    """
    if value is None:
        return None
    raw = str(value).strip().translate(_MINUS_SIGNS)
    if not raw:
        return None
    raw = raw.replace("\u00a0", " ").replace(" ", "")
    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1]
    if not raw or not _NUMERIC.match(raw):
        return None

    sign = ""
    if raw[0] in "+-":
        sign, raw = raw[0], raw[1:]
    if not raw:
        return None

    if "," in raw and "." in raw:
        raw = (
            raw.replace(",", "")
            if raw.rindex(".") > raw.rindex(",")
            else raw.replace(".", "").replace(",", ".")
        )
    elif "," in raw:
        # Parte entera 0 ("0,250"): un grupo de miles nunca empieza por 0, asi
        # que el separador unico es decimal aunque le sigan 3 cifras (antes
        # "0,125 EUR por accion" se leia como 125: error x1000).
        if (
            _DECIMAL_COMMA.match(f"0{raw}")
            or _ZERO_INTEGER.match(raw.replace(",", "."))
            or _not_a_thousands_group(raw, ",")
        ):
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "." in raw:
        # A lone period is treated like a lone comma, which is what makes
        # "(1.250)" thousand come out as -1.250.000 instead of -1.25 (a 1000x
        # error the other way), and it is what keeps es-ES grouping such as
        # "1.234.567" parseable at all instead of raising InvalidOperation.
        groups = raw.split(".")
        # "0.250" es 0,25, nunca 250 (mismo motivo que con la coma).
        if (
            not _ZERO_INTEGER.match(raw)
            and not _not_a_thousands_group(raw, ".")
            and all(len(group) == 3 for group in groups[1:])
        ):
            raw = "".join(groups)
    try:
        parsed = Decimal(f"{sign}{raw}")
    except (InvalidOperation, ValueError):
        return None
    return (-abs(parsed) if negative else parsed), negative


def find_number_tokens_with_units(text: object, window: int = 25) -> list[tuple[str, str]]:
    """Every numeric token paired with the text that follows it.

    The trailing context is where the figure's unit lives ("1.234,5 millones",
    "12,5 %"), and grounding a KPI needs THAT unit, not a scale guessed from
    global tolerance. The window is cut where the next token starts, so one
    figure can never borrow the unit of the figure after it, and capped at
    ``window`` characters so a distant word cannot attach itself either.
    """
    if text is None:
        return []
    joined = _SPACE_THOUSANDS.sub("", str(text).translate(_MINUS_SIGNS))
    matches = list(_NUMBER_RUN.finditer(joined))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        limit = matches[index + 1].start() if index + 1 < len(matches) else len(joined)
        result.append((match.group().strip(), joined[match.end() : min(match.end() + window, limit)]))
    return result
