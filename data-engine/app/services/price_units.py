"""Read raw provider prices in the ledger's actual monetary unit."""
from decimal import Decimal

from app.valuation.currency import listing_quote_unit, normalize_currency


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
