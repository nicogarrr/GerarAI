"""Conector CNMV NOD: notificaciones de operaciones a cuenta propia de directivos.

Registro oficial: Operaciones de directivos (PDMR, equivalente ES del régimen
MAR 596/2014) publicado por la CNMV en
https://www.cnmv.es/portal/consultas/directivos-consulta?lang=es

Sin API: el listado se consulta por GET directo sobre la vista de resultados
(verificado en vivo 2026-11-18: la URL de resultados con fechad/fechah/page
devuelve el HTML paginado sin sesión ni viewstate). La cabecera incluye:
fecha, emisor (con NIF en el enlace datosentidad.aspx), declarante, motivo de
la notificación, número de registro y URL del documento completo. NO incluye
sentido (compra/venta), importe ni moneda: eso solo está dentro del documento
(fase 2). Por tanto los importes persisten como N/D.

Licencia: datos públicos oficiales de la CNMV; reproducción con atribución
(mismo precedente aceptado que el conector OIR, docs/ops/2026-09-22).
Retraso: publicación oficial (hasta 3 días hábiles por reglamento MAR 19).

Degradación honesta: si el HTML no muestra la estructura esperada, lanza
CNMVNODParseError en lugar de inventar campos. Una página sin bloques solo
devuelve vacío si el servidor declara explícitamente «No se han encontrado
resultados»; cualquier otro layout desconocido lanza (deriva silenciosa NO:
un listado vacío inventado presentaría como completo algo que no se midió).

Coste MEDIDO en vivo (auditoría 2026-11-18): la ventana del actor (3 días)
fue 1 GET en total (1 página con 8 cabeceras, 18-nov; en 7 días: 2 GET).
El listado por rango de fechas es idéntico para todos los tenants y cada
tenant lo descarga por separado en su actor diario (queue INGESTA de
Dramatiq, declarada en queue_taxonomy: no compite con la default saturada).
Coste acotado: como mucho ``max_pages`` GET por tenant y día (20 por defecto,
10 cabeceras por página), separados 1 s por el pacer global «cnmv»
(compartido entre procesos vía Redis y, sin Redis, con fallback local
ÚNICO para todo cnmv.es: app/services/connectors/cnmv_pacer.py).
No hay cache compartida entre tenants: el volumen agregado (N tenants x 1
página típica medida) queda muy por debajo de la cortesía del sitio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from app.services.connectors.cnmv_pacer import cnmv_pacer, is_cnmv_url, respect_retry_after
from app.services.public_fetch import PublicSession

FORM = "PDMR-ES"
SOURCE = "CNMV"
LICENCE = "CNMV NOD - datos públicos oficiales, reproducción con atribución"
PARSER_VERSION = "2026-11-18.1"
DELAY_POLICY = "publicación oficial CNMV (hasta 3 días hábiles por MAR 19)"

BASE = "https://www.cnmv.es"
RESULTS_URL = BASE + "/Portal/Consultas/Directivos-Resultado"
USER_AGENT = "GerarAI/1.0 (research; single-user app)"
MIN_INTERVAL_S = 1.0  # 1 petición/s GLOBAL al sitio CNMV (todos los procesos)

_NO_RESULTS = re.compile(r"No se han encontrado resultados", re.IGNORECASE)


# Pacer global «cnmv» COMPARTIDO entre todos los conectores de cnmv.es
# (app/services/connectors/cnmv_pacer.py): una sola instancia por proceso,
# así el fallback local sin Redis también es único para todo el sitio
# (auditoría 2026-11-18, punto 3: dos instancias doblaban el ritmo real).
_pacer = cnmv_pacer

_PAGE_LABEL = re.compile(r"Página\s+(\d+)\s+de\s+(\d+)")
_REGISTRO = re.compile(r"Número de registro:\s*([0-9]+)", re.IGNORECASE)
_NIF = re.compile(r"datosentidad\.aspx\?nif=([^&\"']+)", re.IGNORECASE)
_VERDOC = re.compile(r"webservices/verdocumento/ver\?e=", re.IGNORECASE)


class CNMVNODParseError(RuntimeError):
    """El HTML del registro no muestra la estructura esperada."""


@dataclass
class CNMVNODEntry:
    filing_date: date
    issuer_name: str
    nif: str | None
    declarant: str | None
    motive: str | None
    registry_number: str
    document_url: str | None


def _throttle() -> None:
    _pacer.wait_sync()


class _Getter(Protocol):
    """Lo que NOD necesita de un cliente: ``get(url) -> httpx.Response``.
    En produccion es ``PublicSession`` (app.services.public_fetch: IP publica
    validada y fijada, allowlist https a www.cnmv.es en cada salto, tope de
    bytes); los tests inyectan un ``httpx.Client`` con MockTransport."""

    def get(self, url: str) -> httpx.Response: ...


def _public_session() -> PublicSession:
    return PublicSession(
        allowed_url=is_cnmv_url,
        user_agent=USER_AGENT,
        timeout=30.0,
        extra_headers={"Accept-Language": "es"},
    )


def _get(client: _Getter, url: str, params: dict[str, str]) -> str:
    _throttle()
    response = client.get(f"{url}?{urlencode(params)}" if params else url)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        # Respeta Retry-After: el cooldown se marca en el pacer global para
        # que TODOS los procesos esperen, y el error sube igualmente.
        respect_retry_after(response)
        raise
    return response.text


@dataclass
class CNMVNODFetch:
    """Resultado de una descarga paginada: el truncado viaja explícito."""

    entries: list[CNMVNODEntry] = field(default_factory=list)
    total_pages: int = 0
    fetched_pages: int = 0
    truncated: bool = False

    def __bool__(self) -> bool:
        return bool(self.entries)


def fetch_entries(
    start: date,
    end: date,
    *,
    client: _Getter | None = None,
    max_pages: int = 20,
) -> CNMVNODFetch:
    """Descarga las cabeceras NOD entre ``start`` y ``end`` (ambas incluidas).

    Paginación: el listado muestra 10 por página; el texto «Página X de Y»
    indica el total. Degradación honesta si cambia la estructura.
    ``max_pages`` acota las peticiones: 0 significa NINGUNA petición (ni la
    primera) y devuelve vacío; si el total supera ``max_pages`` el resultado
    llega con ``truncated=True`` (nunca se presenta un listado a medias como
    completo).
    """
    if max_pages < 1:
        return CNMVNODFetch()
    params = {"fechad": start.strftime("%d/%m/%Y"), "fechah": end.strftime("%d/%m/%Y")}
    if client is not None:
        return _fetch_pages(client, params, max_pages)
    with _public_session() as session:
        return _fetch_pages(session, params, max_pages)


def _fetch_pages(client: _Getter, params: dict[str, str], max_pages: int) -> CNMVNODFetch:
    html = _get(client, RESULTS_URL, params)
    entries, total_pages = _parse_page(html)
    fetched = 1
    for page in range(1, min(total_pages, max_pages)):
        page_params = {**params, "page": str(page)}
        page_entries, _ = _parse_page(_get(client, RESULTS_URL, page_params))
        entries.extend(page_entries)
        fetched += 1
    return CNMVNODFetch(
        entries=entries,
        total_pages=total_pages,
        fetched_pages=fetched,
        truncated=total_pages > fetched,
    )


def fetch_latest(days: int = 3) -> CNMVNODFetch:
    end = date.today()
    return fetch_entries(end - timedelta(days=days), end)


def _parse_page(html: str) -> tuple[list[CNMVNODEntry], int]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    match = _PAGE_LABEL.search(text)
    total_pages = int(match.group(2)) if match else 1

    blocks = soup.select("li.blocks-single")
    if not blocks:
        if _NO_RESULTS.search(text):
            return [], 0
        # Fail-closed: cualquier layout sin bloques que el servidor NO declara
        # explícitamente como "sin resultados" es una deriva desconocida. Un
        # vacío inventado aquí presentaría como completo algo no medido.
        raise CNMVNODParseError(
            "resultados NOD sin bloques ni declaración explícita de 'sin resultados': "
            "estructura desconocida, no se inventa un listado vacío"
        )

    entries: list[CNMVNODEntry] = []
    for block in blocks:
        entries.append(_parse_block(block))
    return entries, total_pages


def _parse_block(block) -> CNMVNODEntry:
    fecha_el = block.select_one("li.fecha-no-icon")
    if not fecha_el:
        raise CNMVNODParseError("bloque sin fecha en resultados NOD")
    filing_date = _parse_date(fecha_el.get_text(strip=True))

    nif: str | None = None
    issuer_name = ""
    for anchor in block.select("a[href]"):
        href = anchor.get("href", "")
        nif_match = _NIF.search(href)
        if nif_match:
            nif = nif_match.group(1).strip()
            name_el = anchor.select_one("span.tit-small")
            issuer_name = (
                name_el.get_text(" ", strip=True) if name_el else anchor.get_text(" ", strip=True)
            ).strip()
            break

    declarant: str | None = None
    for el in block.select("span.negrita"):
        value = el.get_text(strip=True)
        if value.lower().startswith("declarante:"):
            declarant = value.split(":", 1)[1].strip()
            break

    motive: str | None = None
    document_url: str | None = None
    for anchor in block.select("a[href]"):
        href = anchor.get("href", "")
        if _VERDOC.search(href):
            document_url = href if href.startswith("http") else BASE + "/" + href.lstrip("/")
            label = anchor.get_text(strip=True)
            if ":" in label:
                motive = label.split(":", 1)[1].strip()
            break

    registry_match = _REGISTRO.search(block.get_text(" ", strip=True))
    if not registry_match:
        raise CNMVNODParseError("bloque sin número de registro en resultados NOD")
    registry_number = registry_match.group(1)

    if not issuer_name and nif is None:
        raise CNMVNODParseError("bloque sin emisor ni NIF en resultados NOD")

    return CNMVNODEntry(
        filing_date=filing_date,
        issuer_name=issuer_name,
        nif=nif,
        declarant=declarant,
        motive=motive,
        registry_number=registry_number,
        document_url=document_url,
    )


def _parse_date(raw: str) -> date:
    try:
        day, month, year = (int(part) for part in raw.split("/"))
        return date(year, month, day)
    except (ValueError, AttributeError) as exc:
        raise CNMVNODParseError(f"fecha NOD no reconocida: {raw!r}") from exc
