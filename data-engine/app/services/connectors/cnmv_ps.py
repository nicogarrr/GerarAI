"""Conector CNMV: participaciones significativas y autocartera (PS).

Registro oficial de participaciones significativas de la CNMV (Real Decreto
1362/2007 y Circular 2/2022):
https://www.cnmv.es/portal/consultas/busqueda?id=7&lang=es

Sin API y sin atajo por NIF directo (verificado en vivo 2026-11-18: la vista
de notificaciones exige un qS de sesion). Flujo por corrida, en una sesion:
1. GET del buscador (viewstate) -> POST fecha_desde/fecha_hasta -> NIFs de
   los emisores con notificaciones en el rango.
2. Por cada emisor: POST de seleccion (con el viewstate de la pagina de
   resultados) -> qS de sesion.
3. GET de Notificaciones-Participaciones?qS={qS} -> tabla de accionistas
   significativos actuales: denominacion, % de derechos atribuidos a acciones
   (total/directo/indirecto), % via instrumentos financieros, (A+B) total y
   F.Registro Entrada CNMV con enlace al documento.

La tabla declara porcentajes y fecha; NO declara numero de acciones del
titular (nunca se deriva: N/D). Los porcentajes llevan formato espanol
(3,000 = 3.0).

Licencia: datos publicos oficiales de la CNMV; reproduccion con atribucion
(mismo precedente aceptado que el conector OIR, docs/ops/2026-09-22).
Retraso: publicacion oficial de la CNMV.

Degradacion honesta: si el HTML no muestra la estructura esperada lanza
CNMVPSParseError en lugar de inventar campos (una lista de emisores solo es
vacia cuando el servidor declara "encontrados: 0 resultados"; una ficha sin
tabla solo cuando declara "No hay datos para mostrar"). Respeta Retry-After
(cooldown global) y el throttle de 1 peticion/segundo GLOBAL via pacer
«cnmv» compartido con el conector NOD.

Coste declarado (auditoria 2026-11-18): el actor corre en la queue INGESTA
(queue_taxonomy) y cada tenant descarga el mismo registro por separado:
acotado a 2 + 2*max_issuers peticiones por tenant y dia (52 por defecto) a
1 req/s global entre TODOS los procesos. Sin cache compartida entre tenants.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

import httpx
from bs4 import BeautifulSoup

from app.services.connectors.cnmv_pacer import cnmv_pacer, is_cnmv_url, respect_retry_after
from app.services.public_fetch import PublicSession

FORM = "PS-ES"
SOURCE = "CNMV"
LICENCE = "CNMV participaciones significativas - datos públicos oficiales, reproducción con atribución"
PARSER_VERSION = "2026-11-18.1"
DELAY_POLICY = "publicación oficial CNMV (RD 1362/2007, Circular 2/2022)"

BASE = "https://www.cnmv.es"
SEARCH_URL = BASE + "/portal/consultas/busqueda?id=7&lang=es"
NOTIF_PATH = BASE + "/Portal/consultas/DerechosVoto/Notificaciones-Participaciones"
USER_AGENT = "GerarAI/1.0 (research; single-user app)"
MIN_INTERVAL_S = 1.0  # 1 peticion por sitio de llamada, como el conector OIR
# Tope de emisores por corrida (auditoria: nada que parezca evasion de
# limites): 2 + 2*25 peticiones como maximo por corrida diaria.
DEFAULT_MAX_ISSUERS = 25

_QS = re.compile(r"Notificaciones-Participaciones\.aspx\?qS=(\{[^}\"']+\})", re.IGNORECASE)
_TOTAL_DERECHOS = re.compile(
    r"mero total de derechos de voto \(incluidos[^)]*\):\s*([0-9.]+)", re.IGNORECASE
)
_LEALTAD = re.compile(r"adicionales otorgados por acciones por lealtad:\s*([0-9.]+)", re.IGNORECASE)


class CNMVPSParseError(RuntimeError):
    """El HTML del registro no muestra la estructura esperada."""


@dataclass
class PSHolder:
    holder_name: str
    pct_shares_total: float | None  # (A) atribuidos a acciones
    pct_direct: float | None
    pct_indirect: float | None
    pct_instruments: float | None  # (B) via instrumentos financieros
    pct_total: float | None  # (A+B)
    registry_date: date | None  # F.Registro Entrada CNMV
    document_url: str | None


@dataclass
class PSIssuerReport:
    nif: str
    issuer_name: str
    total_voting_rights: int | None = None
    loyalty_voting_rights: int | None = None
    holders: list[PSHolder] = field(default_factory=list)
    page_url: str | None = None


# Pacer global «cnmv» COMPARTIDO entre todos los conectores de cnmv.es
# (app/services/connectors/cnmv_pacer.py): una sola instancia por proceso.
# Auditoría 2026-11-18 (3): con instancias separadas, el fallback local sin
# Redis NO se compartía entre NOD y PS y el ritmo real sobre el sitio se
# doblaba; ahora el fallback local también es único para todo cnmv.es.
_pacer = cnmv_pacer


def _throttle() -> None:
    _pacer.wait_sync()


def _respect_retry_after(response: httpx.Response) -> None:
    """Retry-After se obedece INTEGRO via cooldown GLOBAL extend-only (todos
    los procesos); nunca se reintenta en caliente y NUNCA se acorta.

    Auditoría 2026-11-18 (2): el tope de 300 s anterior recortaba un
    Retry-After: 3600 a 5 min y el sitio nos volvía a ver 55 min antes de
    lo que pidió. Efecto declarado de no recortar: un Retry-After grande
    (p. ej. 3600 s) bloquea TODAS las llamadas a cnmv.es (NOD y PS, todos
    los procesos) durante ese tiempo; la corrida del actor falla con su
    HTTPStatusError, reintenta por backoff de Dramatiq (30 s, 2 veces) y la
    corrida diaria siguiente ya encuentra el cooldown expirado. Ningún dato
    se inventa mientras tanto: la ventana de 3 días absorbe el retraso.
    """
    respect_retry_after(response)


class _Session(Protocol):
    """Lo que PS necesita de un cliente: GET y POST de formulario que devuelven
    ``httpx.Response`` con cookies de sesion conservadas entre llamadas. En
    produccion es ``PublicSession`` (app.services.public_fetch: IP publica
    validada y fijada, allowlist https a www.cnmv.es en cada salto, cookies
    solo del host emisor, tope de bytes); los tests inyectan un
    ``httpx.Client`` con MockTransport."""

    def get(self, url: str) -> httpx.Response: ...

    def post(self, url: str, data: dict[str, str]) -> httpx.Response: ...


def _get(client: _Session, url: str) -> httpx.Response:
    _throttle()
    response = client.get(url)
    _respect_retry_after(response)
    response.raise_for_status()
    return response


def _post(client: _Session, url: str, data: dict[str, str]) -> httpx.Response:
    _throttle()
    response = client.post(url, data=data)
    _respect_retry_after(response)
    response.raise_for_status()
    return response


def _session(client: _Session | None) -> AbstractContextManager[_Session]:
    if client is not None:
        return nullcontext(client)
    return PublicSession(
        allowed_url=is_cnmv_url,
        user_agent=USER_AGENT,
        timeout=30.0,
        extra_headers={"Accept-Language": "es"},
    )


def _viewstate(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, str] = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        el = soup.select_one(f'input[name="{name}"]')
        if el is not None:
            out[name] = el.get("value", "")
    if "__VIEWSTATE" not in out:
        raise CNMVPSParseError("pagina sin __VIEWSTATE (estructura del portal cambiada)")
    return out


def _result_issuers(results_html: str) -> list[tuple[str, str]]:
    """(nif, denominacion) de los emisores con notificaciones en el rango."""
    soup = BeautifulSoup(results_html, "html.parser")
    select = soup.select_one('select[name$="lstSeleccion"]')
    if select is None:
        text = soup.get_text(" ", strip=True)
        if re.search(r"encontrados:\s*0\s+resultados", text, re.IGNORECASE):
            return []
        raise CNMVPSParseError("resultados PS sin lista de emisores")
    return [
        (option.get("value", "").strip(), option.get_text(strip=True))
        for option in select.select("option")
        if option.get("value", "").strip()
    ]


def fetch_reports(
    start: date,
    end: date,
    *,
    is_known: Callable[[str], bool] | None = None,
    client: _Session | None = None,
    max_issuers: int = DEFAULT_MAX_ISSUERS,
) -> tuple[list[PSIssuerReport], int, bool]:
    """Corrida completa: (informes por emisor, emisores vistos, truncado).

    Solo descarga la tabla de los emisores que pasan ``is_known`` (cuando se
    da): el resto del registro no nos pertenece y no se visita.
    ``max_issuers`` acota las peticiones por corrida: 0 significa NINGUNA
    petición (ni la búsqueda) y devuelve ([], 0, False). Si el tope frena la
    descarga con emisores conocidos aún pendientes, ``truncado=True``: la
    corrida a medias nunca se presenta como completa.
    """
    if max_issuers < 1:
        return [], 0, False
    with _session(client) as client:
        search_html = _get(client, SEARCH_URL).text
        state = _viewstate(search_html)
        results = _post(
            client,
            SEARCH_URL,
            data={
                **state,
                "ctl00$wBusqueda$txtBusqueda": "",
                "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion": "",
                "ctl00$ContentPrincipal$wFechas$fecha_desde": start.strftime("%d/%m/%Y"),
                "ctl00$ContentPrincipal$wFechas$fecha_hasta": end.strftime("%d/%m/%Y"),
                "ctl00$ContentPrincipal$btnOk": "Buscar",
            },
        ).text
        issuers = _result_issuers(results)
        reports: list[PSIssuerReport] = []
        fetched = 0
        truncated = False
        for nif, name in issuers:
            if is_known is not None and not is_known(nif):
                continue
            if fetched >= max_issuers:
                # Quedan emisores conocidos sin visitar: señalado, no silencioso.
                truncated = True
                break
            select_state = _viewstate(results)
            landing = _post(
                client,
                SEARCH_URL,
                data={
                    **select_state,
                    "ctl00$ContentPrincipal$wbusqueda$lstSeleccion": nif,
                    "ctl00$ContentPrincipal$wbusqueda$btnSeleccionar": "Seleccionar",
                },
            ).text
            qs_match = _QS.search(landing)
            if not qs_match:
                raise CNMVPSParseError(f"sin qS de sesion para {nif}")
            url = f"{NOTIF_PATH}?qS={qs_match.group(1)}"
            page = _get(client, url).text
            reports.append(parse_issuer_page(page, nif, name, page_url=url))
            fetched += 1
        return reports, len(issuers), truncated


def parse_issuer_page(
    html: str, nif: str, issuer_name: str, *, page_url: str | None = None
) -> PSIssuerReport:
    """Parsea la vista de notificaciones: tabla actual de accionistas significativos."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    report = PSIssuerReport(nif=nif, issuer_name=issuer_name, page_url=page_url)

    subtitle = soup.select_one("#ctl00_lblSubtitulo")
    if subtitle and subtitle.get_text(strip=True).upper() != issuer_name.upper():
        # La pagina no es del emisor pedido: identidad no cuadrada, degrada.
        raise CNMVPSParseError(
            f"identidad no cuadrada: pagina de {subtitle.get_text(strip=True)!r}, esperada {issuer_name!r}"
        )

    total = _TOTAL_DERECHOS.search(text)
    if total:
        report.total_voting_rights = _parse_int(total.group(1))
        loyalty = _LEALTAD.search(text)
        if loyalty:
            report.loyalty_voting_rights = _parse_int(loyalty.group(1))

    table = soup.select_one('table[id$="gridAccionistasSignificativos"]')
    if table is None:
        if "No hay datos para mostrar" in text:
            return report
        raise CNMVPSParseError("vista PS sin tabla de accionistas significativos")

    rows = table.select("tbody tr")
    if not rows:
        # Auditoría 2026-11-18 (1): una tabla sin filas tbody es HTML válido y
        # antes devolvía 0 titulares en silencio (deriva: presentaría como
        # «sin titulares significativos» algo nunca medido). Vacío SOLO si el
        # servidor declara explícitamente «No hay datos para mostrar».
        if "No hay datos para mostrar" in text:
            return report
        raise CNMVPSParseError(
            "tabla de accionistas significativos sin filas tbody (estructura cambiada)"
        )

    for row in rows:
        cells = {td.get("data-th", "").strip(): td for td in row.select("td[data-th]")}
        name_el = cells.get("Denominación")
        if name_el is None:
            raise CNMVPSParseError("fila de accionista sin denominacion")
        holder = PSHolder(
            holder_name=name_el.get_text(" ", strip=True),
            pct_shares_total=_parse_pct(_cell_text(cells.get("% Total (A)"))),
            pct_direct=_parse_pct(_cell_text(cells.get("% Directo"))),
            pct_indirect=_parse_pct(_cell_text(cells.get("% Indirecto"))),
            pct_instruments=_parse_pct(_cell_text(cells.get("%  (B)"))),
            pct_total=_parse_pct(_cell_text(cells.get("(A+B)"))),
            registry_date=None,
            document_url=None,
        )
        reg_el = cells.get("F.Registro Entrada CNMV")
        if reg_el is not None:
            anchor = reg_el.select_one("a[href]")
            raw = (anchor or reg_el).get_text(" ", strip=True)
            holder.registry_date = _parse_date(raw) if raw else None
            if anchor is not None:
                href = anchor.get("href", "")
                holder.document_url = href if href.startswith("http") else BASE + "/" + href.lstrip("/")
        report.holders.append(holder)
    return report


def _cell_text(el) -> str:
    return el.get_text(" ", strip=True) if el is not None else ""


def _parse_pct(raw: str) -> float | None:
    """Formato espanol: '18,958' -> 18.958. Vacio/ilegible -> None (N/D)."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _parse_int(raw: str) -> int | None:
    """Miles con punto: '249.335.371' -> 249335371."""
    try:
        return int(raw.replace(".", ""))
    except ValueError:
        return None


def _parse_date(raw: str) -> date | None:
    try:
        day, month, year = (int(part) for part in raw.split("/"))
        return date(year, month, day)
    except (ValueError, AttributeError):
        return None


def recent_window(days: int = 3) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=days), end
