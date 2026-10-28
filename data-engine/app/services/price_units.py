"""Read raw provider prices in the ledger's actual monetary unit."""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.valuation.currency import (
    listing_currency,
    listing_quote_unit,
    normalize_currency,
    resolve_fx,
)


def price_in_currency(
    value: Decimal, *, quote_currency: str | None, target_currency: str, company,
) -> Decimal | None:
    """No FX here: only exact major/minor-unit conversion for the same money.

    Legacy rows on potentially minor-unit listings cannot establish their unit.
    Keep ordinary major-unit legacy rows compatible only if listing metadata
    and the ledger agree. Never infer pence from .L, source or price magnitude.
    """
    raw = quote_currency
    if not raw:
        listing_unit = listing_quote_unit(company.ticker, company.currency)
        listing_major, listing_divisor = normalize_currency(listing_unit)
        target_major, target_divisor = normalize_currency(target_currency)
        if listing_divisor != 1 or target_divisor != 1 or listing_major != target_major:
            return None
        raw = target_currency
    major, divisor = normalize_currency(raw)
    target_major, target_divisor = normalize_currency(target_currency)
    if not major or major != target_major:
        return None
    return value * Decimal(target_divisor) / Decimal(divisor)


def listing_price(
    value: Decimal, *, quote_currency: str | None, company,
) -> tuple[Decimal, str] | None:
    """Precio en la divisa principal de SU cotizacion, sin FX.

    La divisa del precio es la que el proveedor declara para la cotizacion
    (``quote_currency``), nunca la de las cuentas de la empresa. Si coincide
    con la divisa del listado deducida del master, se devuelve en esa divisa
    (comportamiento de siempre). Si no coincide (SHEL en Londres: cuentas en
    USD, cotiza en GBp), se devuelve en la divisa principal de la cotizacion
    (GBP, peniques / 100) y el consumidor convierte con FX si lo necesita.
    Sin ``quote_currency`` solo vale la regla legacy de ``price_in_currency``.
    """
    listing = listing_currency(company.ticker, getattr(company, "currency", None))
    same = price_in_currency(value, quote_currency=quote_currency, target_currency=listing, company=company)
    if same is not None:
        return same, listing
    major, divisor = normalize_currency(quote_currency)
    if not major:
        return None
    return value / Decimal(divisor), major


def close_in_company_currency(
    db: Session, value: Decimal, *, quote_currency: str | None, company, on: date,
) -> Decimal | None:
    """Cierre expresado en ``Company.currency`` para ratios contra hechos.

    Sin ``quote_currency`` (o sin divisa de la empresa) se devuelve el cierre
    tal cual (comportamiento previo, sin tocar). Con la misma divisa principal
    solo cambia la unidad, de forma exacta y sin FX: TSCO.L cotiza en GBp y
    reporta en GBP, asi que 250,5 peniques son 2,505 GBP (devolver los
    peniques tal cual inflaba x100 el market cap derivado y el PER). Si la
    cotizacion esta en otra divisa (SHEL.L en GBp con cuentas en USD) se pasa
    a la divisa principal de la cotizacion y se convierte con el tipo FX
    point-in-time; sin tipo valido, None (N/D, nunca un precio en otra divisa).
    """
    quote_major, quote_divisor = normalize_currency(quote_currency)
    company_major, company_divisor = normalize_currency(getattr(company, "currency", None))
    if not quote_major or not company_major:
        return value
    if quote_major == company_major:
        if quote_divisor == company_divisor:
            return value
        return value * Decimal(company_divisor) / Decimal(quote_divisor)
    fx = resolve_fx(db, quote_major, company_major, on)
    if fx is None:
        return None
    major_value = value / Decimal(quote_divisor)
    return major_value * Decimal(str(fx.rate)) * Decimal(company_divisor)
