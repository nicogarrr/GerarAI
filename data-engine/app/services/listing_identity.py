"""Reviewed listing identities, never a ticker-only issuer guess."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ListingIdentity:
    isin: str
    name: str
    ticker: str
    exchange: str
    currency: str
    yahoo: str
    stooq: str
    source: str


BASIC_FIT = ListingIdentity(
    isin="NL0011872650", name="Basic-Fit N.V.", ticker="BFIT.AS",
    exchange="EURONEXT AMSTERDAM", currency="EUR", yahoo="BFIT.AS", stooq="bfit.nl",
    source="https://live.euronext.com/en/search_instruments/BFIT",
)
BY_ISIN = {BASIC_FIT.isin: BASIC_FIT}


def reviewed_listing(isin: str | None) -> ListingIdentity | None:
    return BY_ISIN.get((isin or "").strip().upper())
