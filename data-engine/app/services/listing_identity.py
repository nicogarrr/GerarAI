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


def ambiguous_bare_symbol(symbol: str | None, currency: str | None) -> ListingIdentity | None:
    """Listado verificado al que podría referirse un símbolo «a secas» sin ISIN.

    «BFIT» en EUR sin ISIN puede ser Basic-Fit (BFIT.AS) o el BFIT de EE. UU.:
    ni el símbolo ni la divisa bastan para decidirlo, así que la fila va a
    revisión en vez de asignarse en silencio al homónimo de EE. UU.
    """
    bare = (symbol or "").strip().upper()
    money = (currency or "").strip().upper()
    if not bare or not money:
        return None
    for listing in BY_ISIN.values():
        if listing.ticker.split(".", 1)[0] == bare and listing.currency == money:
            return listing
    return None


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
