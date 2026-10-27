"""Divisa de cotizacion por listado y subunidades (peniques, centavos, agorot).

Yahoo y FMP cotizan Londres en peniques (``GBp``/``GBX``), Johannesburgo en
centavos de rand (``ZAc``/``ZAC``) y Tel Aviv en agorot (``ILA``). Guardar ese
numero y compararlo con un valor en libras daba errores x100 (CGEO.L: 4.255
peniques frente a un valor de 42,55 GBP). Nada de lo guardado se reescribe:
``MarketPrice`` conserva el precio tal y como lo da el proveedor y la
conversion a la unidad principal se hace al LEER, en las fronteras de
valoracion y cartera.

Fuentes de las subunidades: ISO 4217 no define codigos para subunidades;
``GBX``/``ZAC``/``ILA`` son la convencion de mercado (Bloomberg, LSEG) y
``GBp``/``ZAc`` la de Yahoo. 1 GBP = 100 peniques, 1 ZAR = 100 centavos,
1 ILS = 100 agorot.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Codigo de subunidad -> (divisa ISO principal, divisor). Las claves en
# minusculas mixtas (``GBp``) se comparan SIN pasar a mayusculas: ``GBP`` en
# mayusculas son libras, ``GBp`` son peniques.
MINOR_UNITS: dict[str, tuple[str, int]] = {
    "GBX": ("GBP", 100),
    "GBp": ("GBP", 100),
    "GBPENCE": ("GBP", 100),
    "ZAC": ("ZAR", 100),
    "ZAc": ("ZAR", 100),
    "ILA": ("ILS", 100),
    "ILa": ("ILS", 100),
    "ILX": ("ILS", 100),
}

# Unidad en la que cotiza cada sufijo de Yahoo. Londres, Johannesburgo y Tel
# Aviv cotizan acciones en subunidad. Solo sufijos con una divisa inequivoca.
SUFFIX_QUOTE_UNIT: dict[str, str] = {
    ".L": "GBX",
    ".JO": "ZAC",
    ".TA": "ILA",
    ".MC": "EUR",
    ".PA": "EUR",
    ".DE": "EUR",
    ".F": "EUR",
    ".AS": "EUR",
    ".BR": "EUR",
    ".MI": "EUR",
    ".LS": "EUR",
    ".VI": "EUR",
    ".HE": "EUR",
    ".IR": "EUR",
    ".SW": "CHF",
    ".T": "JPY",
    ".HK": "HKD",
    ".TO": "CAD",
    ".V": "CAD",
    ".AX": "AUD",
    ".ST": "SEK",
    ".CO": "DKK",
    ".OL": "NOK",
    ".SS": "CNY",
    ".SZ": "CNY",
    ".KS": "KRW",
    ".TW": "TWD",
    ".SA": "BRL",
    ".MX": "MXN",
    ".NS": "INR",
    ".BO": "INR",
    ".SI": "SGD",
    ".WA": "PLN",
}


def normalize_currency(raw: str | None) -> tuple[str | None, int]:
    """``(divisa ISO principal, divisor)`` de un codigo de divisa del proveedor.

    ``"GBp"`` -> ``("GBP", 100)``; ``"usd"`` -> ``("USD", 1)``; vacio -> ``(None, 1)``.
    """
    text = (raw or "").strip()
    if not text:
        return None, 1
    if text in MINOR_UNITS:
        return MINOR_UNITS[text]
    upper = text.upper()
    if upper in MINOR_UNITS:
        return MINOR_UNITS[upper]
    return upper, 1


def _ticker_suffix(ticker: str) -> str | None:
    text = (ticker or "").strip().upper()
    if "." not in text:
        return None
    return "." + text.rsplit(".", 1)[1]


def listing_quote_unit(ticker: str | None, company_currency: str | None = None) -> str:
    """Unidad en la que el proveedor cotiza este listado (puede ser subunidad).

    Precedencia: una subunidad declarada en ``Company.currency`` (``GBX``) >
    el sufijo del ticker (``.L`` -> ``GBX``, ``.MC`` -> ``EUR``) >
    ``Company.currency`` > ``USD``. El sufijo manda sobre ``Company.currency``
    porque el enriquecimiento crea las fichas con ``USD`` por defecto.
    """
    declared = (company_currency or "").strip()
    if declared and (declared in MINOR_UNITS or declared.upper() in MINOR_UNITS):
        return declared
    suffix = _ticker_suffix(ticker or "")
    if suffix and suffix in SUFFIX_QUOTE_UNIT:
        return SUFFIX_QUOTE_UNIT[suffix]
    major, _ = normalize_currency(declared)
    return major or "USD"


def listing_currency(ticker: str | None, company_currency: str | None = None) -> str:
    """Divisa ISO principal del listado (``CGEO.L`` -> ``GBP``)."""
    major, _ = normalize_currency(listing_quote_unit(ticker, company_currency))
    return major or "USD"


@dataclass(frozen=True)
class MajorAmount:
    value: float
    currency: str


def to_major_units(value: float | Decimal, unit: str | None) -> MajorAmount | None:
    """Convierte un importe de ``unit`` (quiza subunidad) a su divisa principal.

    ``to_major_units(4255, "GBX")`` -> ``MajorAmount(42.55, "GBP")``. None si la
    unidad es desconocida: nunca se supone una divisa.
    """
    major, divisor = normalize_currency(unit)
    if major is None:
        return None
    return MajorAmount(value=float(value) / divisor, currency=major)
