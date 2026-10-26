"""Provenance envelope for every surfaced datum.

Product standard: no surfaced datum without real provenance, freshness and
coverage state; missing or delayed data is explicit, never filled.

source_kind tiers (do not blur them):
- official:   regulator/official statistics body (SEC, CNMV, FRED, ECB, Eurostat)
- issuer:     published by the company itself (IR pages, press releases)
- exchange:   provided by a trading venue
- unofficial: aggregators / unofficial APIs (Yahoo, stooq) — never authoritative
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum


class SourceKind(StrEnum):
    OFFICIAL = "official"
    ISSUER = "issuer"
    EXCHANGE = "exchange"
    UNOFFICIAL = "unofficial"
    # computed from GerarAI-persisted data whose upstream rows carry their own
    # provenance; used for derived views (risk, summaries, histories)
    INTERNAL = "internal"


class Coverage(StrEnum):
    OK = "ok"                    # fresh, complete for the requested scope
    STALE = "stale"              # served past its freshness threshold
    PARTIAL = "partial"          # some items missing/failed
    UNAVAILABLE = "unavailable"  # nothing servable; consumer must show an honest state


def provenance(
    source: str,
    source_kind: SourceKind | str,
    *,
    source_url: str | None = None,
    fetched_at: datetime | None = None,
    coverage: Coverage | str = Coverage.OK,
    note: str | None = None,
) -> dict:
    """Standard provenance block attached to data responses.

    Additive: endpoints keep their existing fields and add this block under
    the ``provenance`` key. ``fetched_at`` is the real fetch time, never a
    request-time fabrication when the data was cached — callers serving from
    cache must pass the original fetch time.
    """
    kind = SourceKind(source_kind)
    cov = Coverage(coverage)
    block = {
        "source": source,
        "source_kind": kind.value,
        "source_url": source_url,
        "fetched_at": (fetched_at or datetime.now(UTC)).isoformat(),
        "coverage": cov.value,
    }
    if note:
        block["note"] = note
    return block


# Freshness thresholds (seconds) by source family, used to mark STALE honestly.
FRESHNESS_THRESHOLDS_S: dict[str, int] = {
    "sec_edgar": 24 * 3600,        # filings: daily freshness is fine
    "sec_form4": 20 * 60,          # insider monitor cadence is 15 min
    "yahoo_finance": 15 * 60,      # unofficial quotes: short
    "fred": 7 * 24 * 3600,         # macro series update weekly/monthly
    "ecb": 7 * 24 * 3600,
    "cnmv": 24 * 3600,
    "default": 6 * 3600,
}


def coverage_for_age(source_family: str, fetched_at: datetime, *, partial: bool = False, empty: bool = False) -> Coverage:
    """Compute the honest coverage state for data fetched at ``fetched_at``."""
    if empty:
        return Coverage.UNAVAILABLE
    if partial:
        return Coverage.PARTIAL
    threshold = FRESHNESS_THRESHOLDS_S.get(source_family, FRESHNESS_THRESHOLDS_S["default"])
    age = (datetime.now(UTC) - fetched_at).total_seconds()
    return Coverage.STALE if age > threshold else Coverage.OK
