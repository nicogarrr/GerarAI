"""CelesTrak GP snapshot for the AST catalog; no third-party tracker requests."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite

import httpx

from app.services.data_source_health import get_data_source_registry

SOURCE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=ast&FORMAT=json"
_REGISTRY_KEY = "celestrak"


def _record_http_failure(exc: httpx.HTTPStatusError) -> None:
    # 400/404: el GROUP/FILE pedido no existe (parámetro de consulta): neutro.
    if exc.response.status_code in (400, 404):
        return
    get_data_source_registry().record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")


def _record_transport_failure(exc: Exception) -> None:
    get_data_source_registry().record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")


def _record_parse_failure(kind: str) -> None:
    get_data_source_registry().record_failure(_REGISTRY_KEY, f"200 inválido ({kind})")


def _record_success() -> None:
    get_data_source_registry().record_success(_REGISTRY_KEY)


FLOAT_FIELDS = (
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
)


def normalize_catalog(payload: object, *, fetched_at: datetime) -> list[dict]:
    """Reject a bad/partial response wholesale; preserve catalog names verbatim."""
    if fetched_at.tzinfo is None or not isinstance(payload, list) or not payload or len(payload) > 500:
        raise ValueError("Invalid AST GP catalog")
    catalog: list[dict] = []
    seen: set[int] = set()
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("Invalid AST GP object")
        cat_id = row.get("NORAD_CAT_ID")
        name = row.get("OBJECT_NAME")
        if type(cat_id) is not int or cat_id <= 0 or cat_id in seen:
            raise ValueError("Missing or duplicate NORAD ID")
        if (
            not isinstance(name, str)
            or not (name == "BLUEWALKER-3" or name.startswith("SPACEMOBILE-"))
            or len(name) > 100
        ):
            raise ValueError("Unexpected object name in AST group")
        try:
            epoch = datetime.fromisoformat(str(row["EPOCH"]).replace("Z", "+00:00"))
            if epoch.tzinfo is None:
                epoch = epoch.replace(tzinfo=UTC)  # CelesTrak OMM epochs are UTC.
            epoch = epoch.astimezone(UTC)
            if epoch > fetched_at.astimezone(UTC) or (fetched_at.astimezone(UTC) - epoch).days > 30:
                raise ValueError("Implausible GP epoch")
            elements = {field.lower(): float(row[field]) for field in FLOAT_FIELDS}
            if not all(isfinite(value) for value in elements.values()):
                raise ValueError("Nonfinite GP element")
            if not (
                0 < elements["mean_motion"] < 20
                and 0 <= elements["eccentricity"] < 1
                and 0 <= elements["inclination"] <= 180
            ):
                raise ValueError("Out-of-range GP element")
        except (KeyError, TypeError, OverflowError, ValueError) as exc:
            raise ValueError("Invalid AST GP elements") from exc
        seen.add(cat_id)
        catalog.append(
            {
                "norad_cat_id": cat_id,
                "object_name": name,
                "object_id": str(row.get("OBJECT_ID") or ""),
                "epoch": epoch.isoformat(),
                **elements,
            }
        )
    return sorted(catalog, key=lambda item: item["norad_cat_id"])


async def fetch_catalog(
    client: httpx.AsyncClient | None = None, *, fetched_at: datetime | None = None
) -> list[dict]:
    now = fetched_at or datetime.now(UTC)
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as own_client:
                response = await own_client.get(
                    SOURCE_URL, headers={"User-Agent": "GerarAI/1.0 (AST catalog research)"}
                )
        else:
            response = await client.get(SOURCE_URL)
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
        raise ValueError("Oversized AST GP response")
    try:
        payload = response.json()
    except ValueError:
        _record_parse_failure("no JSON")
        raise
    try:
        catalog = normalize_catalog(payload, fetched_at=now)
    except ValueError:
        _record_parse_failure("schema")
        raise
    # Éxito solo tras validar el esquema del catálogo: un 200 no basta.
    _record_success()
    return catalog
