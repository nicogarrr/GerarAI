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


# Names the app already uses for Euronext Amsterdam: IBKR Flex venue codes
# (AEB, XAMS), our canonical label and Finnhub's labels (see
# propicks_price_service._EXCHANGE_YAHOO_SUFFIX and wacc_input_service).
_VENUE_ALIASES = {
    "EURONEXT AMSTERDAM": frozenset({
        "EURONEXT AMSTERDAM",
        "NYSE EURONEXT - EURONEXT AMSTERDAM",
        "NYSE EURONEXT - AMSTERDAM",
        "AEB",
        "XAMS",
    }),
}
# Exchange values written by stubs before the venue is known.
PLACEHOLDER_EXCHANGES = frozenset({"", "UNKNOWN"})


def same_venue(listing: ListingIdentity, exchange: str | None) -> bool:
    """True when ``exchange`` is one of the known names of the listing's venue."""
    value = (exchange or "").strip().upper()
    return value in _VENUE_ALIASES.get(listing.exchange, frozenset({listing.exchange}))
