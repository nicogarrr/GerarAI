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

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache

from sqlalchemy.orm import Session

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


@lru_cache(maxsize=512)
def normalize_currency(raw: str | None) -> tuple[str | None, int]:
    """``(divisa ISO principal, divisor)`` de un codigo de divisa del proveedor.

    ``"GBp"`` -> ``("GBP", 100)``; ``"usd"`` -> ``("USD", 1)``; vacio -> ``(None, 1)``.
    Pura y con un puñado de codigos distintos: se memoriza (la reconstruccion
    de la cartera la llama decenas de miles de veces por vista).
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


def canonical_currency_code(raw: str | None) -> str:
    """Codigo de divisa listo para guardar, sin perder la subunidad.

    ``.upper()`` a secas convierte ``GBp`` (peniques) en ``GBP`` (libras) y
    multiplica el importe por 100. Aqui una subunidad conocida conserva su
    forma (``GBp``, ``ZAc``, ``ILa``, ``GBX``) y el resto va en mayusculas.
    """
    text = (raw or "").strip()
    if text in MINOR_UNITS:
        return text
    return text.upper()


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


# ---------------------------------------------------------------------------
# Divisa de los hechos y conversion FX point-in-time
# ---------------------------------------------------------------------------

_NON_MONETARY_UNITS = frozenset({"SHARES", "DECIMAL", "PURE", "RATIO", "PERCENT", "PCT", "X", "%", "BPS"})

# Antiguedad maxima del tipo de cambio respecto a la fecha del precio. El BCE
# publica cada dia habil: un fin de semana largo con festivo son 4-5 dias.
FX_MAX_AGE_DAYS = 7


def fact_currency(unit: str | None) -> str | None:
    """Divisa de un hecho monetario segun su unidad; None si no es monetario.

    ``"CNY"`` -> ``"CNY"``; ``"USD/share"`` -> ``"USD"``; ``"shares"``,
    ``"decimal"`` -> None.
    """
    text = (unit or "").strip()
    if not text:
        return None
    head = text.split("/", 1)[0].strip()
    if head.upper() in _NON_MONETARY_UNITS:
        return None
    major, _ = normalize_currency(head)
    if major is None or len(major) != 3 or not major.isalpha():
        return None
    return major


def reporting_currencies(units: Iterable[str | None]) -> set[str]:
    """Divisas monetarias distintas presentes en un conjunto de unidades."""
    found: set[str] = set()
    for unit in units:
        code = fact_currency(unit)
        if code is not None:
            found.add(code)
    return found


@dataclass(frozen=True)
class FxQuote:
    """``amount_from * rate = amount_to`` a la fecha ``rate_date`` (<= ``on``)."""

    from_currency: str
    to_currency: str
    rate: float
    rate_date: date | None
    source: str | None
    path: tuple[str, ...]

    def as_trace(self) -> dict:
        return {
            "from": self.from_currency,
            "to": self.to_currency,
            "rate": self.rate,
            "rate_date": self.rate_date.isoformat() if self.rate_date else None,
            "source": self.source,
            "path": list(self.path),
        }


def _leg(db: Session, from_ccy: str, to_ccy: str, on: date) -> tuple[float, date | None, str | None] | None:
    from app.services.portfolio_fx_service import PortfolioFXService

    found = PortfolioFXService().rate_with_provenance(
        db, quote_currency=from_ccy, base_currency=to_ccy, as_of=on
    )
    if not found or found.get("rate") is None:
        return None
    rate = float(found["rate"])
    if not rate > 0:
        return None
    return rate, found.get("rate_date"), found.get("source")


def resolve_fx(
    db: Session,
    from_currency: str,
    to_currency: str,
    on: date,
    *,
    max_age_days: int = FX_MAX_AGE_DAYS,
    pivots: Iterable[str] = ("EUR", "USD"),
) -> FxQuote | None:
    """Tipo de cambio POINT-IN-TIME de ``fx_rates``; None si no hay uno valido.

    Solo filas con ``rate_date <= on`` (nunca un tipo futuro) y con como mucho
    ``max_age_days`` de antiguedad: un tipo de hace meses no se usa como si
    fuera el del dia. Directo o inverso primero; si no, cruzado por una divisa
    pivote (la tabla del BCE es EUR->X, asi que CNY->USD = CNY->EUR->USD).
    Nunca se inventa un tipo.
    """
    # ``.upper()`` a secas convertiria ``GBp`` (peniques) en ``GBP`` (libras):
    # tipo x100. La subunidad se conserva y el servicio FX aplica su divisor.
    src = canonical_currency_code(from_currency)
    dst = canonical_currency_code(to_currency)
    src_major, src_divisor = normalize_currency(src)
    dst_major, dst_divisor = normalize_currency(dst)
    if src_major == dst_major:
        # Misma divisa (quiza subunidad): conversion exacta, sin tabla FX.
        path = (src,) if src == dst else (src, dst)
        return FxQuote(src, dst, dst_divisor / src_divisor, None, None, path)

    def fresh(rate_date: date | None) -> bool:
        return rate_date is not None and (on - rate_date).days <= max_age_days

    direct = _leg(db, src, dst, on)
    if direct is not None and fresh(direct[1]):
        return FxQuote(src, dst, direct[0], direct[1], direct[2], (src, dst))
    for pivot in pivots:
        pivot = pivot.upper()
        if pivot in {src_major, dst_major}:
            continue
        first = _leg(db, src, pivot, on)
        second = _leg(db, pivot, dst, on)
        if first is None or second is None:
            continue
        if not (fresh(first[1]) and fresh(second[1])):
            continue
        dates = [d for d in (first[1], second[1]) if d is not None]
        oldest = min(dates) if dates else None
        source = first[2] if first[2] == second[2] else f"{first[2]}+{second[2]}"
        return FxQuote(src, dst, first[0] * second[0], oldest, source, (src, pivot, dst))
    return None


# Campos por accion del resultado de un motor, en la divisa del motor.
_PER_SHARE_FIELDS = ("bear_value", "base_value", "bull_value", "expected_value")


def scale_per_share_outputs(result: dict, factor: float) -> None:
    """Multiplica por ``factor`` los importes por accion del resultado (in situ).

    Ratios (margen de seguridad, crecimiento implicito, WACC) son invariantes
    a la divisa y no se tocan.
    """

    def scaled(value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        return value * factor

    for key in _PER_SHARE_FIELDS:
        if key in result:
            result[key] = scaled(result[key])
    listed = result.get("listed_share_values")
    if isinstance(listed, dict):
        result["listed_share_values"] = {k: scaled(v) for k, v in listed.items()}
    sensitivity = result.get("sensitivity")
    if isinstance(sensitivity, dict):
        for row in sensitivity.get("rows") or []:
            if not isinstance(row, dict):
                continue
            for cell in row.get("values") or []:
                if isinstance(cell, dict) and "value_per_share" in cell:
                    cell["value_per_share"] = scaled(cell["value_per_share"])
    reverse = result.get("reverse_dcf")
    if isinstance(reverse, dict):
        for key in ("market_price", "solved_value_per_share"):
            if key in reverse:
                reverse[key] = scaled(reverse[key])
    scenarios = result.get("scenarios")
    if isinstance(scenarios, dict):
        for data in scenarios.values():
            if isinstance(data, dict) and "value_per_share" in data:
                data["value_per_share"] = scaled(data["value_per_share"])
