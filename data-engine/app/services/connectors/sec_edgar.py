"""Fundamentales gratuitos de SEC EDGAR (10-K/10-Q). Sin API key: solo User-Agent de contacto.

Idea originada en TauricResearch/TradingAgents
``tradingagents/dataflows/sec_edgar.py`` (Apache-2.0): EDGAR no pide clave,
pero la SEC exige un User-Agent que identifique al llamante con un contacto y
rechaza las peticiones sin el. Implementacion propia para GerarAI: cliente
``httpx`` asincrono (inyectable en tests), tolerante a 429 con backoff
exponencial y respeto a ``Retry-After``, y normalizacion minima de conceptos
us-gaap de 10-K (anual) y 10-Q (trimestral).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.data_source_health import get_data_source_registry

# Clave compartida con connectors/sec.py: mismo proveedor, mismo circuito.
# 400/404 son dato por documento/CIK y NO degradan; 401/403 van al mirror HF
# (fallback declarado): si el mirror sirve cuenta como exito, si falla, fallo.
_REGISTRY_KEY = "sec_edgar"

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

DEFAULT_CONTACT = "contact@example.com"
# Cabecera tipo navegador + contacto: la SEC bloquea User-Agents sin contacto.
BROWSER_USER_AGENT = "Mozilla/5.0 (compatible; GerarAI/0.1; +mailto:{contact}) GerarAI Research"

ANNUAL_FORMS = {"10-K", "20-F"}
QUARTERLY_FORMS = {"10-Q"}

# Metrica -> tags us-gaap por orden de preferencia (el primero que informa gana;
# nunca se suman tags: un mismo ingreso bajo dos tags se contaria dos veces).
METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "total_assets": ("Assets",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
}


def resolve_user_agent() -> str:
    """User-Agent con contacto: env ``SEC_EDGAR_USER_AGENT`` > settings > defecto."""
    configured = os.getenv("SEC_EDGAR_USER_AGENT", "").strip()
    candidate = configured or get_settings().sec_user_agent.strip() or ""
    if "@" not in candidate:
        candidate = BROWSER_USER_AGENT.format(contact=DEFAULT_CONTACT)
    elif candidate.startswith(("CavaAI/", "GerarAI/")) and "Mozilla" not in candidate:
        candidate = BROWSER_USER_AGENT.format(contact=candidate.split()[-1].strip("()"))
    return candidate


def default_headers(user_agent: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": user_agent or resolve_user_agent(),
        "Accept": "application/json, text/html, */*",
        "Accept-Encoding": "gzip, deflate",
    }


def _pad_cik(cik: str | int) -> str:
    return str(cik).strip().zfill(10)


def _snapshot_path_for(url: str) -> Path | None:
    """Ruta del snapshot local para una URL EDGAR, o None si no aplica.

    Layout: $SEC_SNAPSHOT_DIR/company_tickers.json,
    $SEC_SNAPSHOT_DIR/companyfacts/CIK##########.json y
    $SEC_SNAPSHOT_DIR/submissions/CIK##########.json (mismo formato JSON
    que la API oficial, con fetched_at real en manifest.json).
    """
    import re

    from app.core.config import get_settings

    base = get_settings().sec_snapshot_dir
    if not base:
        return None
    root = Path(base)
    if url == TICKER_MAP_URL:
        return root / "company_tickers.json"
    match = re.search(r"(?:companyfacts|submissions)/(CIK\d{10}(?:-submissions-\d+)?)\.json$", url)
    if match:
        kind = "companyfacts" if "companyfacts" in url else "submissions"
        return root / kind / f"{match.group(1)}.json"
    return None


def _mirror_path_for(url: str) -> str | None:
    """Path del documento dentro del dataset mirror, o None si esa URL de la
    SEC no tiene equivalente en el mirror."""
    if url == TICKER_MAP_URL:
        return "company_tickers.json"
    match = re.search(r"(?:companyfacts|submissions)/(CIK\d{10}(?:-submissions-\d+)?)\.json$", url)
    if not match:
        return None
    kind = "companyfacts" if "companyfacts" in url else "submissions"
    return f"{kind}/{match.group(1)}.json"


def _mirror_url_for(url: str) -> str | None:
    """URL del mirror HF para una URL de la SEC, o None si no hay mirror.

    Mismo layout que el snapshot local: companyfacts/CIK##########.json,
    submissions/CIK##########(-submissions-NNN)?.json, company_tickers.json.
    """
    from app.core.config import get_settings

    dataset = get_settings().sec_hf_mirror_dataset
    path = _mirror_path_for(url)
    if not dataset or path is None:
        return None
    return f"https://huggingface.co/datasets/{dataset}/resolve/main/{path}"


def _read_snapshot(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    import json

    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else None


async def _get_json(
    url: str,
    client: httpx.AsyncClient | None = None,
    *,
    max_retries: int = 4,
    base_delay: float = 1.0,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """GET JSON tolerante a 429: backoff exponencial + cabecera ``Retry-After``.

    Si hay snapshot local para la URL (SEC_SNAPSHOT_DIR), se usa en vez de la
    red: la SEC bloquea las IPs de datacenter y el dato es igual de oficial.
    """
    snapshot = _read_snapshot(_snapshot_path_for(url))
    if snapshot is not None:
        return snapshot
    mirror_url = _mirror_url_for(url)
    headers = default_headers(user_agent)
    direct_error: Exception | None = None
    delay = base_delay
    last_error: Exception | None = None
    registry = get_data_source_registry()
    started = time.perf_counter()
    for attempt in range(max_retries + 1):
        try:
            if client is not None:
                response = await client.get(url, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as owned:
                    response = await owned.get(url)
        except httpx.TransportError as exc:
            registry.record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
            raise
        if response.status_code == 429 and attempt < max_retries:
            retry_after = response.headers.get("retry-after")
            try:
                wait = float(retry_after) if retry_after else delay
            except (TypeError, ValueError):
                wait = delay
            await asyncio.sleep(max(0.0, min(wait, 60.0)))
            delay *= 2
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # La SEC bloquea las IPs de datacenter con 403: el mirror HF
            # sirve el mismo JSON oficial. 404 en la SEC no se enmascara:
            # un documento inexistente lo es tambien en el mirror, pero el
            # 403 es un fallo de transporte, no de dato.
            if response.status_code in {401, 403} and mirror_url is not None:
                direct_error = exc
                break
            if response.status_code not in (400, 404):
                # 400/404: documento inexistente, dato por emisor (neutral).
                registry.record_failure(_REGISTRY_KEY, f"HTTP {response.status_code}")
            raise RuntimeError(f"SEC EDGAR request failed ({response.status_code} {url})") from exc
        last_error = None
        try:
            data = response.json()
        except ValueError:
            registry.record_failure(_REGISTRY_KEY, "respuesta no JSON")
            raise
        if not isinstance(data, dict):
            registry.record_failure(_REGISTRY_KEY, "JSON no objeto")
            raise RuntimeError(f"SEC EDGAR returned non-object JSON ({url})")
        registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
        return data
    if direct_error is None:
        registry.record_failure(_REGISTRY_KEY, "HTTP 429: rate limit agotado")
        raise RuntimeError(f"SEC EDGAR rate-limited (429 {url}) after {max_retries} retries") from last_error
    try:
        mirrored = await mirror_get_json(url, direct_error=direct_error)
    except Exception as exc:
        registry.record_failure(_REGISTRY_KEY, f"HTTP 401/403 (IP) y mirror fallo: {type(exc).__name__}")
        raise
    registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
    return mirrored


MIRROR_MAX_AGE = timedelta(hours=48)
_MANIFEST_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MANIFEST_TTL_SECONDS = 300.0
_MIRROR_SERVES: ContextVar[list[dict[str, Any]] | None] = ContextVar("cavaai_mirror_serves", default=None)


def drain_mirror_serves() -> list[dict[str, Any]]:
    """Servicios de mirror de ESTA corrida (la ingesta los declara en su
    resultado: que se sirvio del mirror y de que fecha de sync).

    ContextVar por corrida: dos ingestas concurrentes nunca se mezclan ni se
    pierden registros de procedencia. La corrida llama a drain al inicio para
    abrir su registro y al final para recogerlo."""
    serves = _MIRROR_SERVES.get()
    _MIRROR_SERVES.set([])
    return list(serves) if serves else []


def _record_mirror_serve(entry: dict[str, Any]) -> None:
    serves = _MIRROR_SERVES.get()
    if serves is not None:
        serves.append(entry)


async def _mirror_manifest(dataset: str) -> dict[str, Any]:
    """Manifest del mirror con frescura verificada. Cache de 5 minutos: la
    ingesta pide varios documentos por emisor y el manifest no cambia entre
    ellas. Fail closed: sin manifest valido o con synced_at > 48h, el mirror
    entero se considera caducado y NO se sirve dato viejo como fresco."""
    now = time.monotonic()
    cached = _MANIFEST_CACHE.get(dataset)
    if cached and now - cached[0] < _MANIFEST_TTL_SECONDS:
        return cached[1]
    manifest_url = f"https://huggingface.co/datasets/{dataset}/resolve/main/manifest.json"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(manifest_url)
    response.raise_for_status()
    manifest = response.json()
    if not isinstance(manifest, dict):
        raise RuntimeError(f"Mirror HF manifest no es objeto JSON ({manifest_url})")
    synced_raw = manifest.get("synced_at")
    try:
        synced_at = datetime.fromisoformat(str(synced_raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Mirror HF sin synced_at valido ({synced_raw!r}): fail closed") from exc
    age = datetime.now(UTC) - synced_at
    if age > MIRROR_MAX_AGE:
        raise RuntimeError(
            f"Mirror HF caducado: synced_at {synced_raw} tiene {age.days} dias "
            f"(max {MIRROR_MAX_AGE}). Fail closed: no se sirve dato viejo como fresco."
        )
    _MANIFEST_CACHE[dataset] = (now, manifest)
    return manifest


async def mirror_get_json(url: str, *, direct_error: Exception | None = None) -> dict[str, Any]:
    """Lee el documento SEC desde el mirror HF (dataset publico, sin
    credenciales). Error claro si no hay mirror configurado, el manifest
    esta caducado o el mirror no tiene el documento: nunca se enmascara un
    fallo de dato como de transporte."""
    mirror_url = _mirror_url_for(url)
    if mirror_url is None:
        raise RuntimeError(f"SEC bloqueada y sin mirror HF configurado ({url})") from direct_error
    from app.core.config import get_settings

    manifest = await _mirror_manifest(get_settings().sec_hf_mirror_dataset or "")
    # Integridad: un manifest fresco no basta. El documento pedido debe estar
    # declarado en manifest["files"] (un archivo huerfano de un sync anterior
    # no se sirve) y su sha1 debe casar con el declarado (una subida parcial
    # que dejo mezcla de versiones no se sirve). Fail closed en ambos casos.
    path = _mirror_path_for(url)
    declared_files = manifest.get("files")
    declared_hash = declared_files.get(path) if isinstance(declared_files, dict) else None
    if declared_hash is None:
        raise RuntimeError(
            f"Mirror HF: {path} no esta declarado en el manifest "
            f"(fail closed: no se sirve un documento sin proveniencia declarada)"
        ) from direct_error
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as mirror_client:
        mirror_response = await mirror_client.get(mirror_url)
    try:
        mirror_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"SEC bloqueada ({direct_error}) y mirror HF sin el documento "
            f"({mirror_response.status_code} {mirror_url})"
        ) from exc
    raw = mirror_response.content
    actual_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
    if actual_hash != declared_hash:
        raise RuntimeError(
            f"Mirror HF: sha1 de {path} no casa con el manifest "
            f"({actual_hash} != {declared_hash}): fail closed, posible "
            f"mezcla de versiones de un sync parcial"
        ) from direct_error
    import json as _json

    data = _json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"Mirror HF returned non-object JSON ({mirror_url})")
    _record_mirror_serve({"url": url, "synced_at": manifest.get("synced_at")})
    return data


def _manifest_cik(ticker: str) -> str | None:
    """CIK desde el manifest del snapshot (evita el company_tickers de 2MB)."""
    import json

    from app.core.config import get_settings

    base = get_settings().sec_snapshot_dir
    if not base:
        return None
    manifest = Path(base) / "manifest.json"
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_text())
    tickers = data.get("tickers", {}) if isinstance(data, dict) else {}
    cik = tickers.get(ticker.strip().upper())
    return _pad_cik(cik) if cik else None


async def cik_for_ticker(ticker: str, client: httpx.AsyncClient | None = None) -> str | None:
    """CIK a 10 digitos para un ticker US, o None si no es filer EDGAR."""
    from_manifest = _manifest_cik(ticker)
    if from_manifest is not None:
        return from_manifest
    table = await _get_json(TICKER_MAP_URL, client)
    # Mismo criterio que SECClient.cik_for_ticker: exacto primero y, si no,
    # comparación sin separadores de clase con match único (BRK.B == BRK-B).
    from app.services.sec_ticker import match_cik

    return match_cik(
        (
            (str(entry.get("ticker", "")), _pad_cik(entry["cik_str"]))
            for entry in table.values()
            if isinstance(entry, dict) and entry.get("cik_str") is not None
        ),
        ticker,
    )


async def company_facts(cik: str | int, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Hechos XBRL (companyfacts) tal como fueron fileados, sin normalizar."""
    return await _get_json(COMPANYFACTS_URL.format(cik=_pad_cik(cik)), client)


async def recent_filings(
    cik: str | int,
    forms: tuple[str, ...] = ("10-K", "10-Q"),
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Filings recientes filtrados por formulario (por defecto 10-K/10-Q)."""
    payload = await _get_json(SUBMISSIONS_URL.format(cik=_pad_cik(cik)), client)
    recent = payload.get("filings", {}).get("recent", {})
    allowed = {form.upper() for form in forms}
    cik_number = str(int(str(cik).strip()))
    items: list[dict[str, Any]] = []
    accessions = recent.get("accessionNumber", [])
    for index, accession in enumerate(accessions):
        form = str(recent.get("form", [None])[index] if index < len(recent.get("form", [])) else None or "")
        if form.upper() not in allowed:
            continue

        def _col(name: str) -> Any:
            values = recent.get(name, [])
            return values[index] if index < len(values) else None

        primary = _col("primaryDocument")
        accession_nodash = str(accession).replace("-", "")
        index_url = f"{ARCHIVES_URL}/{cik_number}/{accession_nodash}/"
        items.append(
            {
                "form": form,
                "accession_number": accession,
                "filing_date": _col("filingDate"),
                "report_date": _col("reportDate"),
                "primary_document": primary,
                "index_url": index_url,
                "document_url": f"{index_url}{primary}" if primary else index_url,
            }
        )
        if len(items) >= limit:
            break
    return items


def extract_metric_values(
    us_gaap: dict[str, Any],
    tags: tuple[str, ...],
    *,
    forms: set[str] | None = None,
    unit: str = "USD",
) -> dict[str, Any] | None:
    """Ultimo valor fileado para una metrica.

    Los alias de tag se fusionan antes de elegir (no "gana el primero que
    informe"): los filers migran de tag y el antiguo queda congelado en el
    pasado; el valor actual vive en el tag nuevo.
    """
    wanted_forms = forms or (ANNUAL_FORMS | QUARTERLY_FORMS)
    candidates: list[tuple[str, dict]] = []
    for tag in tags:
        entries = ((us_gaap.get(tag) or {}).get("units", {}) or {}).get(unit, [])
        candidates.extend(
            (tag, e)
            for e in entries
            if isinstance(e, dict)
            and str(e.get("form", "")).upper() in wanted_forms
            and e.get("val") is not None
        )
    if not candidates:
        return None
    candidates.sort(key=lambda te: (str(te[1].get("filed", "")), str(te[1].get("end", ""))))
    tag, latest = candidates[-1]
    return {
        "concept": tag,
        "value": latest["val"],
        "unit": unit,
        "end": latest.get("end"),
        "filed": latest.get("filed"),
        "form": latest.get("form"),
        "periods": len({str(e.get("end")) for _, e in candidates}),
    }


async def get_fundamentals(
    ticker: str,
    cik: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Snapshot de fundamentales gratuitos: metricas + ultimos 10-K/10-Q."""
    resolved_cik = cik or await cik_for_ticker(ticker, client)
    if not resolved_cik:
        return {
            "status": "unavailable",
            "ticker": ticker.upper(),
            "reason": "not a US SEC filer",
        }
    facts = await company_facts(resolved_cik, client)
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    metrics: dict[str, Any] = {}
    for metric, tags in METRIC_CONCEPTS.items():
        found = extract_metric_values(us_gaap, tags)
        if found:
            metrics[metric] = found
    return {
        "status": "ok",
        "ticker": ticker.upper(),
        "cik": _pad_cik(resolved_cik),
        "company_name": facts.get("entityName"),
        "metrics": metrics,
        "recent_filings": await recent_filings(resolved_cik, client=client),
    }


# Alias publicos para el cliente async (connectors/sec.py).
manifest_cik = _manifest_cik


def read_snapshot_for(url: str) -> dict[str, Any] | None:
    """Snapshot local para una URL EDGAR, o None si no hay fichero."""
    return _read_snapshot(_snapshot_path_for(url))
