"""Conector AMF VAD: posiciones cortas netas publicadas sobre acciones francesas.

Fuente oficial: Autorité des marchés financiers (AMF), dataset open data en
data.gouv.fr «Historique des positions courtes nettes sur actions rendues
publiques depuis le 1er Novembre 2012» (régimen UE 236/2012: toda posición
corta neta >= 0,5% del capital se hace pública CON titular y LEI; Francia no
ha adoptado el régimen agregado del SSR 2025, a diferencia de la FCA).

Dataset: https://www.data.gouv.fr/datasets/historique-des-positions-courtes-nettes-sur-actions-rendues-publiques-depuis-le-1er-novembre-2012
La URL del CSV lleva timestamp de publicación y cambia en cada entrega: se
resuelve SIEMPRE a través de la API de data.gouv (1 GET de JSON + 1 GET de
CSV por corrida). Si la API o el esquema del recurso cambian, lanza
AMFVADParseError: un fallo de resolución NUNCA se presenta como «sin cortos».

Verificado en vivo 18-nov-2026: CSV de 5,2 MB con 41.620 filas (histórico
completo desde 2012; no hay endpoint «solo vigentes»), 2.767 filas
abiertas brutas (antes de deduplicar por titular e ISIN; 207 titulares
vigentes únicos en 81 ISINs, medido por el Auditor), máx. fecha de posición 13-nov con
fichero publicado el 17-nov (retraso T+2 hábil). Formato: punto y coma,
comillas, UTF-8, sin BOM, fechas ISO. Una actualización de posición es una
FILA NUEVA del mismo (titular, ISIN): la posición vigente de un titular es
su última fila publicada sin «Date de fin de publication position».

Licencia: Licence Ouverte v2.0 (Etalab; campo license=lov2 de la API):
reutilización libre con atribución «AMF». Robots: el CSV se sirve desde un
bucket OVH público publicado por la propia AMF para descarga masiva.

Degradación honesta: deriva (cabecera, columnas, ISIN, fecha, ratio) lanza
AMFVADParseError en lugar de inventar campos. El agregado por emisor
(suma de titulares) se etiqueta siempre como DERIVADO; el ratio por
titular es OFICIAL. Sin fila vigente para un ISIN: N/D, nunca 0.

Coste declarado: 2 GET por proceso y ventana de cache (12 h; publicación
diaria hábil): como máximo 2 ventanas/día = 4 GET/día/proceso. Single-flight
por proceso: dos misses concurrentes comparten UNA descarga (lock + recheck). Pacer global
«amf» propio (1 req/s entre procesos vía Redis, fallback local por
proceso). Retry-After se obedece ÍNTEGRO (numérico o HTTP-date), nunca
recortado (mismo criterio que CNMV/FCA, auditoría 18-nov): un Retry-After
grande bloquea las descargas de todos los procesos y la lectura degrada a
N/D hasta el siguiente intento; nada se inventa mientras.
"""

from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from app.services.connectors.global_pacing import GlobalPacer
from app.services.data_source_health import get_data_source_registry
from app.services.public_fetch import fetch_public_url

FORM = "AMF-VAD"
SOURCE = "AMF"
LICENCE = "AMF - Licence Ouverte v2.0"
PARSER_VERSION = "2026-11-18.1"
DELAY_POLICY = "publicación diaria hábil AMF, ~T+2 (última posición 13-nov en fichero del 17-nov, medido 18-nov-2026)"
THRESHOLD_POLICY = "posiciones cortas netas >=0,5% del capital, públicas con titular (UE 236/2012)"

DATASET_API_URL = (
    "https://www.data.gouv.fr/api/1/datasets/"
    "historique-des-positions-courtes-nettes-sur-actions-rendues-publiques-depuis-le-1er-novembre-2012/"
)
USER_AGENT = "GerarAI/1.0 (research; single-user app)"
MIN_INTERVAL_S = 1.0  # 1 petición/s GLOBAL a data.gouv + bucket OVH (todos los procesos)
CACHE_TTL_S = 12 * 3600  # publicación diaria hábil: hasta 2 ventanas/día = 4 GET/día/proceso (2 por ventana)

_REGISTRY_KEY = "amf"

_HEADER = [
    "Detenteur de la position courte nette",
    "Legal Entity Identifier detenteur",
    "Emetteur / issuer",
    "Ratio",
    "code ISIN",
    "Date de debut position",
    "Date de debut de publication position",
    "Date de fin de publication position",
]
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_LEI = re.compile(r"^[A-Z0-9]{20}$")


class AMFVADParseError(RuntimeError):
    """El dataset o la API de data.gouv no muestran la estructura esperada."""


@dataclass
class AMFVADRow:
    holder_name: str
    holder_lei: str | None  # N/D si la celda no es un LEI válido; nunca inventado
    issuer_name: str
    ratio_pct: float
    isin: str
    position_start: date
    publication_start: date
    publication_end: date | None  # None = publicación vigente


def _amf_redis_client():
    try:
        import redis as _redis

        from app.core.config import get_settings
        from app.core.redis_retry import no_retry

        url = get_settings().redis_url
        if not url:
            return None
        return _redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=1.0, retry=no_retry())
    except Exception:  # noqa: BLE001 - sin Redis: pacing local por proceso
        return None


# Pacer global «amf» (clave propia, como «fca»): serializa hilos (lock local)
# y procesos (slots Redis, mismo mecanismo que finnhub/gdelt).
_pacer = GlobalPacer(
    "amf",
    min_interval_seconds=MIN_INTERVAL_S,
    redis_client_factory=_amf_redis_client,
)


def _throttle() -> None:
    _pacer.wait_sync()


def _respect_retry_after(response: httpx.Response) -> None:
    """Retry-After se obedece ÍNTEGRO via cooldown GLOBAL extend-only (todos
    los procesos); NUNCA se acorta (auditoría CNMV 18-nov, mismo criterio)."""
    value = response.headers.get("Retry-After")
    if not value:
        return
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            seconds = max((when.timestamp() - time.time()), 0.0)
        except (TypeError, ValueError):
            seconds = 60.0
    _pacer.cool_down(seconds)


# Descarga por app.services.public_fetch (camino aprobado por seguridad: valida
# IP publica, fija la IP validada, sigue redirecciones a mano revalidando cada
# salto y corta por tamano). La politica de hosts es una ALLOWLIST estricta:
# la API de data.gouv y el bucket OVH de la propia AMF. Un recurso que apunte a
# otro host (o a http) se rechaza: fail-closed, no se descarga.
_ALLOWED_HOSTS = frozenset({"www.data.gouv.fr", "amf.s3.sbg.io.cloud.ovh.net"})
MAX_BYTES = 32 * 1024 * 1024  # CSV medido 5,2 MB (41.620 filas) el 18-nov-2026; crece despacio
FETCH_TIMEOUT_S = 60.0


def _allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "") in _ALLOWED_HOSTS


def _public_get(url: str) -> str:
    """GET acotado via public_fetch. Rechazo de politica/tamano/IP = deriva
    (AMFVADParseError); HTTP >=400 propaga HTTPStatusError de httpx (con su
    cabecera Retry-After); un cuerpo no UTF-8 tambien es deriva."""
    try:
        content, _content_type, _final_url = fetch_public_url(
            url,
            max_bytes=MAX_BYTES,
            timeout=FETCH_TIMEOUT_S,
            allowed_url=_allowed_url,
            user_agent=USER_AGENT,
        )
    except ValueError as exc:
        raise AMFVADParseError(f"descarga rechazada por public_fetch: {exc}") from exc
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AMFVADParseError("respuesta no UTF-8 (deriva del fichero)") from exc


def _get_text(fetch: Callable[[str], str], url: str) -> str:
    _throttle()
    try:
        return fetch(url)
    except httpx.HTTPStatusError as exc:
        _respect_retry_after(exc.response)
        raise


def resolve_resource_url(fetch: Callable[[str], str]) -> str:
    """URL vigente del CSV vía API de data.gouv. Fail-closed: si la API no
    ofrece exactamente un recurso CSV reconocible, es deriva, no «sin cortos»."""
    payload = _get_text(fetch, DATASET_API_URL)
    try:
        dataset = json.loads(payload)
        resources = dataset["resources"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AMFVADParseError("API data.gouv sin JSON de dataset reconocible") from exc
    csv_urls = [
        resource.get("url", "")
        for resource in resources
        if isinstance(resource, dict) and str(resource.get("format", "")).lower() == "csv"
    ]
    csv_urls = [url for url in csv_urls if url]
    if len(csv_urls) != 1:
        raise AMFVADParseError(
            f"API data.gouv: {len(csv_urls)} recursos CSV (esperado 1): esquema del dataset cambiado"
        )
    if not _allowed_url(csv_urls[0]):
        raise AMFVADParseError("recurso CSV fuera de la allowlist de hosts (https, data.gouv/OVH AMF)")
    return csv_urls[0]


def _parse_iso(raw: str, line_no: int, campo: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise AMFVADParseError(f"fila {line_no} con {campo} no ISO: {raw!r}") from exc


def parse_csv(text: str, *, now: datetime | None = None) -> list[AMFVADRow]:
    """Parsea el CSV histórico completo. Fail-closed: deriva -> AMFVADParseError."""
    try:
        # strict=True: comillas mal cerradas o basura tras comillas lanzan en
        # vez de alterar nombres en silencio (auditoria FCA 18-nov, misma leccion).
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";", quotechar='"', strict=True))
    except csv.Error as exc:
        raise AMFVADParseError(f"CSV malformado: {exc}") from exc
    if not rows or rows[0] != _HEADER:
        raise AMFVADParseError("cabecera VAD no reconocida (deriva del CSV)")
    today = (now or datetime.now(UTC)).date()
    out: list[AMFVADRow] = []
    for line_no, row in enumerate(rows[1:], start=2):
        if not row or all(not cell for cell in row):
            continue  # línea vacía final del fichero
        if len(row) != 8:
            raise AMFVADParseError(f"fila {line_no} con {len(row)} columnas (esperadas 8)")
        holder, lei, issuer, raw_ratio, isin, raw_pos, raw_pub, raw_end = (
            cell.strip() for cell in row
        )
        if not holder:
            raise AMFVADParseError(f"fila {line_no} sin titular")
        if not issuer:
            raise AMFVADParseError(f"fila {line_no} sin emisor")
        if not _ISIN.match(isin):
            raise AMFVADParseError(f"fila {line_no} con ISIN invalido: {isin!r}")
        try:
            ratio = float(raw_ratio)
        except ValueError as exc:
            raise AMFVADParseError(f"fila {line_no} con ratio no numerico: {raw_ratio!r}") from exc
        if not 0.0 <= ratio <= 100.0:
            raise AMFVADParseError(f"fila {line_no} con ratio fuera de rango: {ratio}")
        position_start = _parse_iso(raw_pos, line_no, "fecha de posicion")
        if position_start > today:
            raise AMFVADParseError(f"fila {line_no} con fecha de posicion futura: {raw_pos!r}")
        publication_start = _parse_iso(raw_pub, line_no, "fecha de publicacion")
        if publication_start > today:
            raise AMFVADParseError(f"fila {line_no} con fecha de publicacion futura: {raw_pub!r}")
        publication_end = _parse_iso(raw_end, line_no, "fecha fin de publicacion") if raw_end else None
        out.append(
            AMFVADRow(
                holder_name=holder,
                holder_lei=lei if _LEI.match(lei) else None,
                issuer_name=issuer,
                ratio_pct=ratio,
                isin=isin,
                position_start=position_start,
                publication_start=publication_start,
                publication_end=publication_end,
            )
        )
    if not out:
        # Un fichero solo con cabecera no es «mercado sin cortos»: es deriva.
        raise AMFVADParseError("CSV VAD sin filas: deriva, no mercado vacio")
    return out


def current_positions(rows: list[AMFVADRow]) -> list[AMFVADRow]:
    """Posición vigente por (titular, ISIN): la ÚLTIMA fila publicada que no
    tiene fecha fin de publicación. Las actualizaciones son filas nuevas del
    mismo par; un cierre deja fecha fin en todas sus filas."""
    latest: dict[tuple[str, str], AMFVADRow] = {}
    for row in rows:
        if row.publication_end is not None:
            continue
        key = (row.holder_name.upper(), row.isin)
        current = latest.get(key)
        if current is None or (row.publication_start, row.position_start) > (
            current.publication_start,
            current.position_start,
        ):
            latest[key] = row
    return sorted(latest.values(), key=lambda r: (r.isin, r.holder_name))


def aggregate_by_isin(rows: list[AMFVADRow]) -> dict[str, float]:
    """Suma de ratios por ISIN. DERIVADO: se etiqueta como tal en el payload;
    el dato oficial es el ratio por titular."""
    out: dict[str, float] = {}
    for row in rows:
        out[row.isin] = round(out.get(row.isin, 0.0) + row.ratio_pct, 6)
    return out


# Cache por proceso: el fichero es el mismo para todas las empresas y su
# cadencia es diaria hábil. TTL 12 h: máx. 4 GET/día/proceso (declarado).
_CACHE: dict[str, tuple[float, list[AMFVADRow]]] = {}
_FETCH_LOCK = threading.Lock()  # single-flight por proceso


def reset_cache() -> None:
    """Solo para tests."""
    _CACHE.clear()


def fetch_current(
    *,
    fetch: Callable[[str], str] | None = None,
    cache: dict[str, tuple[float, list[AMFVADRow]]] | None = None,
    monotonic=time.monotonic,
) -> list[AMFVADRow]:
    """Histórico VAD completo (el dataset no ofrece «solo vigentes»).
    Una resolución + una descarga por proceso y ventana de cache."""
    cache = _CACHE if cache is None else cache
    cached = cache.get("current")
    if cached is not None and monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1]
    with _FETCH_LOCK:
        # Recheck: otro hilo pudo rellenar la cache mientras esperabamos el lock.
        cached = cache.get("current")
        if cached is not None and monotonic() - cached[0] < CACHE_TTL_S:
            return cached[1]
        return _download(cache, fetch or _public_get, monotonic)


def _download(cache, fetch, monotonic) -> list[AMFVADRow]:
    registry = get_data_source_registry()
    try:
        try:
            url = resolve_resource_url(fetch)
            text = _get_text(fetch, url)
        except httpx.HTTPError as exc:
            registry.record_failure(_REGISTRY_KEY, f"error de red o HTTP: {type(exc).__name__}")
            raise
        rows = parse_csv(text)
    except AMFVADParseError as exc:
        registry.record_failure(_REGISTRY_KEY, f"parseo: {type(exc).__name__}")
        raise
    registry.record_success(_REGISTRY_KEY)
    cache["current"] = (monotonic(), rows)
    return rows


def rows_for_isin(rows: list[AMFVADRow], isin: str | None) -> list[AMFVADRow]:
    """Posiciones vigentes de un ISIN (titulares). Vacío = sin cortos
    públicos vigentes DECLARADOS por la AMF para ese ISIN (N/D en payload)."""
    if not isin:
        return []
    normalized = isin.strip().upper()
    return [row for row in current_positions(rows) if row.isin == normalized]
