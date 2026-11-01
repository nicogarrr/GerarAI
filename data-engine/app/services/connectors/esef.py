"""ESEF connector — filings.xbrl.org (XBRL International filing index, free, no key).

Verified 2026-09-24:
- JSON:API at https://filings.xbrl.org/api/filings with
  ?filter[country]=ES&page[number]=N&page[size]=M (meta.count = total; 542 ES
  filings at verification time). Reachable from datacenter IPs (no SEC-style
  block).
- Each filing carries json_url (xBRL-JSON render of the report — no iXBRL
  parsing needed) and/or package_url (zip). Older filings may lack json_url:
  they are reported as unavailable, never skipped silently.
- Entity names are NOT in the filing attributes; they require one extra GET
  per LEI at /api/entities/{lei} (attributes.name is the legal name in the
  same normalized uppercase style as the CNMV registry, so the reviewed
  cnmv_mapping join needs no guessing).
- xBRL-JSON shape: {"documentInfo": ..., "facts": {"fact-N": {"value": str,
  "decimals": int, "dimensions": {"concept": "ifrs-full:X", "entity":
  "scheme:LEI", "period": "instant" | "start/end", "unit": "iso4217:EUR"|
  "pure"|...}}}}. Values stay strings (decimals carried separately); nothing
  is rounded or fabricated.

Failure contract: HTTP errors and schema drift raise EsefError; the caller
converts that into an honest degraded state.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.services.data_source_health import get_data_source_registry

# Clave en el registry de salud de fuentes (filings.xbrl.org). 400/404 son
# dato por filing/consulta y NO degradan; 5xx/red/no-JSON SI.
REGISTRY_KEY = "esef"

ESEF_BASE_URL = "https://filings.xbrl.org"
FILINGS_API = "/api/filings"
ENTITIES_API = "/api/entities"
USER_AGENT = "GerarAI/1.0 (research; contact: single-user app)"
DEFAULT_PAGE_SIZE = 100
# Limites no documentados. 1 s entre peticiones acababa en 429 en /api/filings
# (dead-letter de prod, 1-nov-2026): 2 s deja el build semanal (~200-300
# peticiones) en ~10 min, dentro del time_limit de 30 min del actor.
_MIN_INTERVAL_S = 2.0
_last_request_at = 0.0
# 429: reintentos en linea con el Retry-After del servidor (o backoff
# exponencial con jitter si no lo manda); una ventana mayor que el techo no se
# duerme aqui: sube como EsefRateLimited para que el actor reencole.
_MAX_429_RETRIES = 3
_RETRY_BASE_S = 10.0
_RETRY_CAP_S = 120.0


BASE_DIMENSIONS = frozenset({"concept", "entity", "period", "unit"})


class EsefError(RuntimeError):
    """filings.xbrl.org schema drift or transport failure; degrade honestly."""


class EsefRateLimited(EsefError):
    """filings.xbrl.org sigue respondiendo 429 tras los reintentos en linea."""

    def __init__(self, url: str, retry_after: float) -> None:
        super().__init__(f"GET {url}: limite de filings.xbrl.org (429), reintentar tras {retry_after:.0f}s")
        self.retry_after = retry_after


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _retry_after_header(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 and value != float("inf") else None


def _wait_for_429(attempt: int, server: float | None) -> float:
    """Ventana del servidor si la da; si no, exponencial con jitter."""
    if server is not None and server > 0:
        return server
    expo = min(_RETRY_CAP_S, _RETRY_BASE_S * (2**attempt))
    return expo * (1.0 + 0.2 * random.random())


@dataclass(frozen=True, slots=True)
class EsefFiling:
    fxo_id: str
    lei: str
    country: str
    period_end: str | None
    json_url: str | None  # relative path on ESEF_BASE_URL; None = unavailable
    package_url: str | None
    sha256: str | None
    error_count: int | None
    warning_count: int | None
    entity_name: str | None = field(default=None)  # filled via get_entity_name


def _throttle() -> None:
    global _last_request_at
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _lei_from_filing(fxo_id: str, package_url: str | None, json_url: str | None) -> str | None:
    """LEI is the first path segment of the filing URLs (fxo_id prefix)."""
    for url in (json_url, package_url):
        if url:
            parts = [p for p in url.split("/") if p]
            if parts and len(parts[0]) == 20:
                return parts[0]
    if fxo_id and len(fxo_id) >= 20:
        candidate = fxo_id[:20]
        if candidate.isalnum():
            return candidate
    return None


def parse_filings_page(payload: dict[str, Any]) -> tuple[list[EsefFiling], int]:
    """Parse one JSON:API filings page. Raises EsefError on schema drift.

    Returns (filings, total_count) where total_count is meta.count (all pages).
    """
    try:
        data = payload["data"]
        total = int(payload["meta"]["count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EsefError(f"filings page schema drift: {exc!r}") from exc
    if not isinstance(data, list):
        raise EsefError("filings page schema drift: data is not a list")
    filings: list[EsefFiling] = []
    for row in data:
        try:
            attrs = row["attributes"]
            fxo_id = attrs["fxo_id"]
            country = attrs["country"]
        except (KeyError, TypeError) as exc:
            raise EsefError(f"filing row schema drift: {exc!r}") from exc
        lei = _lei_from_filing(fxo_id, attrs.get("package_url"), attrs.get("json_url"))
        if lei is None:
            raise EsefError(f"cannot resolve LEI for filing {fxo_id!r}")
        filings.append(
            EsefFiling(
                fxo_id=fxo_id,
                lei=lei,
                country=country,
                period_end=attrs.get("period_end"),
                json_url=attrs.get("json_url"),
                package_url=attrs.get("package_url"),
                sha256=attrs.get("sha256"),
                error_count=attrs.get("error_count"),
                warning_count=attrs.get("warning_count"),
            )
        )
    return filings, total


def parse_entity(payload: dict[str, Any]) -> tuple[str, str]:
    """Parse /api/entities/{lei} -> (lei, legal_name). Drift raises EsefError."""
    try:
        attrs = payload["data"]["attributes"]
        return attrs["identifier"], attrs["name"]
    except (KeyError, TypeError) as exc:
        raise EsefError(f"entity schema drift: {exc!r}") from exc


def _inclusive_date(component: str) -> str:
    """Componente de periodo xBRL-JSON -> fecha inclusiva ISO.

    Los instantes xBRL-JSON son timestamps EXCLUSIVOS a medianoche: el
    endDate inclusivo 2025-12-31 del XBRL inline se serializa como
    «2026-01-01T00:00:00» (el instante en que EMPIEZA el dia siguiente), y
    un instant de balance 2025-12-31 igual. Leer [:10] a pelo desplaza
    TODOS los periodos un dia y un ejercicio (caso real prod: Aena FY2024
    etiquetado «2025-01-01:FY» FY2025, ASML FY2025 como «2026-01-01:FY»
    FY2026). Solo se corrige el patron con hora de medianoche explicita,
    firma del instante exclusivo; un componente date-only ya es una fecha
    inclusiva y se respeta.
    """
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T00:00:00(\.\d+)?(Z|[+-]\d{2}:?\d{2})?",
        component.strip(),
    ):
        try:
            return (date.fromisoformat(component[:10]) - timedelta(days=1)).isoformat()
        except ValueError:
            pass
    return component[:10]


def parse_period(period: str) -> dict[str, str]:
    """xBRL-JSON period -> {'instant': ...} or {'start': ..., 'end': ...}.

    Fechas INCLUSIVAS: el start no se toca (medianoche = inicio de ese
    dia); end e instant se convierten de instante exclusivo a fecha
    inclusiva (_inclusive_date).
    """
    if "/" in period:
        start, end = period.split("/", 1)
        return {"start": start[:10], "end": _inclusive_date(end)}
    return {"instant": _inclusive_date(period)}


def normalize_xbrl_json(doc: dict[str, Any]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """xBRL-JSON document -> companyfacts-like layout:
    {concept: {unit: [{start|end|instant, val, decimals, lei}]}}.

    Concepts keep their taxonomy prefix (ifrs-full:...) — ESEF filers mix
    ifrs-full and extension concepts and stripping prefixes would collide.
    Values stay as strings with their declared decimals; nothing is computed.
    Facts without a usable concept/period/unit are dropped (they are
    dimensional breakdowns outside the base scope), never guessed.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("facts"), dict):
        raise EsefError("xBRL-JSON schema drift: missing facts object")
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for fact in doc["facts"].values():
        try:
            dims = fact["dimensions"]
            concept = dims["concept"]
            period = dims["period"]
            unit = dims.get("unit", "pure")
        except (KeyError, TypeError):
            continue  # dimensional fact outside base scope: skip, don't guess
        if not concept or not period:
            continue
        entry: dict[str, Any] = parse_period(period)
        entry["val"] = fact.get("value")
        entry["decimals"] = fact.get("decimals")
        lei_raw = dims.get("entity", "")
        entry["lei"] = lei_raw.split(":")[-1] if lei_raw else None
        # Segment/member breakdowns carry extra dimensions (axes); consolidated
        # base-scope facts have none. Consumers must filter entry["dims"] == []
        # or they would read a member value as the consolidated total.
        entry["dims"] = sorted(k for k in dims if k not in BASE_DIMENSIONS)
        out.setdefault(concept, {}).setdefault(unit, []).append(entry)
    for concepts in out.values():
        for entries in concepts.values():
            entries.sort(key=lambda e: e.get("end") or e.get("instant") or "")
    return out


class EsefClient:
    """Async client for filings.xbrl.org. httpx.AsyncClient is injectable
    (tests pass a MockTransport); throttle keeps polling conservative."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=ESEF_BASE_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.api+json"},
            timeout=30.0,
        )

    async def _get_json(
        self, url: str, params: dict[str, Any] | None = None, accept: str | None = None
    ) -> dict[str, Any]:
        registry = get_data_source_registry()
        headers = {"Accept": accept} if accept else None
        attempt = 0
        while True:
            _throttle()
            started = time.monotonic()
            try:
                resp = await self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                registry.record_failure(REGISTRY_KEY, f"{type(exc).__name__}")
                raise EsefError(f"GET {url} failed: {exc!r}") from exc
            if resp.status_code != 429:
                break
            wait = _wait_for_429(attempt, _retry_after_header(resp))
            if wait > _RETRY_CAP_S or attempt >= _MAX_429_RETRIES:
                registry.record_failure(REGISTRY_KEY, "HTTP 429")
                raise EsefRateLimited(url, wait)
            attempt += 1
            await _pause(wait)
        try:
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in (400, 404):
                # Filing/entidad inexistente: dato por consulta, no fuente caida.
                raise EsefError(f"GET {url} failed: {exc!r}") from exc
            registry.record_failure(REGISTRY_KEY, f"HTTP {exc.response.status_code}")
            raise EsefError(f"GET {url} failed: {exc!r}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            registry.record_failure(REGISTRY_KEY, f"{type(exc).__name__}")
            raise EsefError(f"GET {url} failed: {exc!r}") from exc
        registry.record_success(REGISTRY_KEY, (time.monotonic() - started) * 1000)
        return payload

    async def list_filings_page(
        self, country: str = "ES", page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
    ) -> tuple[list[EsefFiling], int]:
        payload = await self._get_json(
            FILINGS_API,
            params={f"filter[country]": country, "page[number]": page, "page[size]": page_size},
        )
        return parse_filings_page(payload)

    async def list_all_filings(
        self, country: str = "ES", page_size: int = DEFAULT_PAGE_SIZE
    ) -> list[EsefFiling]:
        first, total = await self.list_filings_page(country, page=1, page_size=page_size)
        filings = list(first)
        pages = max(1, -(-total // page_size))
        for page in range(2, pages + 1):
            rows, _ = await self.list_filings_page(country, page=page, page_size=page_size)
            filings.extend(rows)
        return filings

    async def get_entity_name(self, lei: str) -> str:
        payload = await self._get_json(f"{ENTITIES_API}/{lei}")
        _, name = parse_entity(payload)
        return name

    async def fetch_filing_json(self, filing: EsefFiling) -> dict[str, Any]:
        """Download the xBRL-JSON render. Raises EsefError when unavailable —
        older filings only carry the zip package and we do not parse iXBRL."""
        if not filing.json_url:
            raise EsefError(f"filing {filing.fxo_id} has no xBRL-JSON render (json_url null)")
        # The document endpoint 406s the JSON:API media type; ask for plain JSON.
        return await self._get_json(filing.json_url, accept="application/json")


def _esef_snapshot_base() -> Path | None:
    from app.core.config import get_settings

    base = get_settings().esef_snapshot_dir
    return Path(base) if base else None


def read_esef_snapshot(ticker: str) -> dict[str, Any] | None:
    """Snapshot ESEF local para un ticker (normalizado por build_esef_snapshots),
    o None si no hay fichero. El join ticker->LEI sale del manifest (tabla
    reviewed; nunca se adivina)."""
    base = _esef_snapshot_base()
    if base is None:
        return None
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        return None
    import json

    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return None
    # Sufijos de bolsa con snapshot ESEF reviewed: .MC (BME/ES) y .AS
    # (Euronext Amsterdam/NL, ASML).
    normalized = ticker.upper().removesuffix(".MC").removesuffix(".AS")
    for lei, info in manifest.get("issuers", {}).items():
        if str(info.get("ticker", "")).upper() == normalized:
            snap_path = base / "snapshots" / f"{lei}.json"
            if snap_path.exists():
                try:
                    data = json.loads(snap_path.read_text())
                except (OSError, ValueError):
                    return None
                return data if isinstance(data, dict) else None
    return None
