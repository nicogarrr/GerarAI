"""CelesTrak owner/operator-derived supplemental GP for AST (not telemetry)."""

from __future__ import annotations

from datetime import datetime

import httpx

from app.services.connectors.celestrak_ast import (
    _record_http_failure,
    _record_parse_failure,
    _record_success,
    _record_transport_failure,
    normalize_catalog,
)

SUPGP_URL = "https://celestrak.org/NORAD/elements/supplemental/sup-gp.php?FILE=ast&FORMAT=json"


def normalize_supgp(
    payload: object, *, fetched_at: datetime, gp_catalog: list[dict] | None = None
) -> list[dict]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("Invalid AST SupGP payload")
    # SupGP can be available when GP is down or a new object has not yet
    # appeared in GP. Validate the feed's own identity and provenance, but
    # never assert cross-source identity merely from a similar label.
    normalized = normalize_catalog(payload, fetched_at=fetched_at)
    for raw in payload:
        if (
            not isinstance(raw, dict)
            or raw.get("CLASSIFICATION_TYPE") != "C"
            or raw.get("DATA_SOURCE") != "AST-E"
        ):
            raise ValueError("Unexpected AST SupGP provenance")
        if gp_catalog is not None:
            reference = next(
                (item for item in gp_catalog if item["norad_cat_id"] == raw["NORAD_CAT_ID"]), None
            )
            if reference and (
                reference["object_name"] != raw["OBJECT_NAME"]
                or reference["object_id"] != str(raw.get("OBJECT_ID") or "")
            ):
                raise ValueError("Conflicting AST object identity across GP and SupGP")
    return normalized


async def fetch_supgp(
    gp_catalog: list[dict] | None = None, client: httpx.AsyncClient | None = None, *, fetched_at: datetime
) -> list[dict]:
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as own:
                response = await own.get(
                    SUPGP_URL, headers={"User-Agent": "GerarAI/1.0 (AST catalog research)"}
                )
        else:
            response = await client.get(SUPGP_URL)
    except httpx.TransportError as exc:
        _record_transport_failure(exc)
        raise
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _record_http_failure(exc)
        raise
    if len(response.content) > 2_000_000:
        _record_parse_failure("oversized")
        raise ValueError("Oversized AST SupGP response")
    try:
        payload = response.json()
    except ValueError:
        _record_parse_failure("no JSON")
        raise
    try:
        normalized = normalize_supgp(payload, fetched_at=fetched_at, gp_catalog=gp_catalog)
    except ValueError:
        _record_parse_failure("schema")
        raise
    # Éxito solo tras validar esquema y procedencia: un 200 no basta.
    _record_success()
    return normalized
