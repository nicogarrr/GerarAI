"""Offline identity handoff. Validates supplied evidence, never proves its truth.

No database, HTTP, broker or account imports. Output is a review plan only,
not authorization to add a watchlist entry or overwrite an existing identity.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

FIELDS = ("ticker", "name", "isin", "mic", "quote_unit")
QUOTE_UNITS = frozenset({"EUR", "GBP", "GBX", "GBp", "MXN", "USD", "CAD", "CHF", "SEK", "NOK", "DKK"})


def _valid_isin(value: str) -> bool:
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value) is None:
        return False
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in value)
    total = 0
    for index, digit in enumerate(reversed(digits)):
        n = int(digit) * (2 if index % 2 else 1)
        total += n // 10 + n % 10
    return total % 10 == 0


def _has_evidence(item: dict, field: str) -> bool:
    evidence = item.get("evidence", {}).get(field, {})
    parsed = urlsplit(str(evidence.get("url") or ""))
    return bool(evidence.get("kind") == "primary" and parsed.scheme == "https" and parsed.hostname
                and evidence.get("checked_at") and evidence.get("quote"))


def build_plan(rows: list[dict], snapshot: dict) -> dict[str, Any]:
    """Cross-check an explicit manifest against a supplied read-only export.

    A complete evidence record means ready for HUMAN/OPERATOR review, not
    authenticated identity. This routine does not fetch or verify a source.
    """
    companies = {str(c.get("ticker") or "").upper(): c for c in snapshot.get("companies", [])}
    counts: dict[str, int] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        counts[ticker] = counts.get(ticker, 0) + 1
    items = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        gaps = [f"missing_primary_evidence:{field}" for field in FIELDS if not _has_evidence(row, field)]
        if not ticker or not str(row.get("name") or "").strip():
            gaps.append("missing_ticker_or_name")
        if not _valid_isin(str(row.get("isin") or "")):
            gaps.append("invalid_or_missing_isin")
        if re.fullmatch(r"[A-Z0-9]{4}", str(row.get("mic") or "")) is None:
            gaps.append("invalid_or_missing_mic")
        if row.get("quote_unit") not in QUOTE_UNITS:
            gaps.append("unsupported_or_missing_quote_unit")
        if counts[ticker] != 1:
            gaps.append("duplicate_manifest_ticker")
        existing = companies.get(ticker)
        if existing and existing.get("isin") and existing["isin"] != row.get("isin"):
            gaps.append("existing_isin_conflict")
        items.append({
            "ticker": ticker,
            "proposed_identity": {field: row.get(field) for field in FIELDS},
            "evidence": row.get("evidence", {}),
            "status": "blocked" if gaps else "evidence_complete_for_review",
            "gaps": gaps,
            "existing_company_id": existing.get("id") if existing else None,
            "next_step": "hold_for_evidence" if gaps else (
                "existing_company_refresh_by_pilot_after_review" if existing
                else "normal_watchlist_add_by_pilot_after_review"),
        })
    return {"mode": "offline_read_only", "writes_performed": 0, "network_requests": 0,
            "snapshot_as_of": snapshot.get("as_of"), "items": items,
            "warning": "Evidence metadata is supplied, not authenticated here. No financial completeness claim; no account action authorized by this output."}
