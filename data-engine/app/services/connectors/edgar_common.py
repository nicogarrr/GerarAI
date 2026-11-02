"""Transporte SEC EDGAR compartido por form4, form13f y form13dg.

Hasta aqui ``form4.py`` llevaba el transporte EDGAR (submissions JSON,
cabeceras con User-Agent de contacto, backoff ante 403/429/5xx, registro de
salud de la fuente) y ``form13dg.py`` se documentaba como "espejo de
form4.py": la misma logica copiada a mano, con el riesgo de que las dos
copias se desalineasen (``form13f.py`` ya importaba trozos de ``form4.py``,
que era la prueba de que el transporte es comun). Este modulo convierte el
espejo en comparticion por construccion: UN solo transporte, importado por
los tres conectores. La intencion del espejo queda asi preservada y
garantizada por identidad de codigo, no por disciplina manual.

Lo que NO vive aqui (sigue en cada conector, es especifico del formulario):
- el conjunto de formularios aceptados ({"4", "4/A"} vs FORMS_13DG) y el
  patron XSLT renderizado (xslF345Xnn vs xslSCHEDULE_13[DG]_Xnn);
- la validacion del documento (raiz <ownershipDocument> vs <edgarSubmission>
  o texto SGML heredado) y todo el parse de contenido.

Las funciones reciben ``headers``/``throttle``/``sleep`` como parametros y NO
leen los globales del conector, para que los puntos de monkeypatch de cada
modulo sigan funcionando (p. ej. ``form4._throttle`` y ``form4._sleep`` en
tests): cada wrapper resuelve sus propios globales en tiempo de llamada y los
inyecta aqui.

No se anade ninguna dependencia: NO tocar requirements.txt por esto.
"""

from __future__ import annotations

import re
import time

import httpx

from app.core.config import get_settings
from app.services.connectors.base import SEC_MIN_INTERVAL_SECONDS, sec_throttle
from app.services.data_source_health import get_data_source_registry

# Clave compartida con el resto de conectores SEC (sec.py, sec_edgar.py):
# mismo proveedor, mismo circuito. 400/404 (CIK o documento inexistente) son
# dato por emisor y NO degradan; 403/429/5xx/red/no-JSON SI.
_REGISTRY_KEY = "sec_edgar"


def _record_sec_outcome(registry, started: float) -> None:
    registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)


def _record_sec_http_failure(registry, exc) -> None:
    from app.services.connectors.sec_pacing import rate_limited

    rate_limited(exc.response)
    registry.record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")


def _record_sec_transport_failure(registry, exc: Exception) -> None:
    registry.record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

# SEC fair-use: maximo 10 peticiones/segundo.
MIN_INTERVAL_SECONDS = SEC_MIN_INTERVAL_SECONDS

# Alias directo (no un wrapper) para que ``form4._throttle`` y
# ``form13dg._throttle`` sean el MISMO objeto y compartan estado por construccion.
_throttle = sec_throttle


BROWSER_USER_AGENT = "Mozilla/5.0 (compatible; GerarAI/0.1; +mailto:{contact}) GerarAI Research"
DEFAULT_CONTACT = "contact@example.com"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def resolve_user_agent() -> str:
    """User-Agent tipo navegador con contacto.

    La SEC bloquea con 403 los User-Agent de producto aunque lleven contacto
    (verificado en prod: ``<producto>/0.1 <email>`` -> 403; UA tipo navegador ->
    200). Misma politica que ``connectors/sec_edgar.py``: se envuelve el
    contacto en un UA tipo navegador, salvo que el operador ya configure uno.
    """
    candidate = (get_settings().sec_user_agent or "").strip()
    if candidate.startswith("Mozilla/"):
        return candidate
    match = _EMAIL_RE.search(candidate)
    contact = match.group(0) if match else DEFAULT_CONTACT
    # Env historico sin espacio ("<producto>/0.1email@..."): la version queda
    # pegada al local-part del email; se retira un prefijo de version.
    contact = re.sub(r"^\d+(\.\d+)+(?=\D)", "", contact)
    return BROWSER_USER_AGENT.format(contact=contact)


def default_headers() -> dict[str, str]:
    return {
        "User-Agent": resolve_user_agent(),
        "Accept": "application/json, text/xml, */*",
        "Accept-Encoding": "gzip, deflate",
    }


def _pad_cik(cik: str | int) -> str:
    return str(cik).strip().zfill(10)


def filing_index_url(cik: str | int, accession_number: str) -> str:
    cik_number = str(int(str(cik).strip()))
    accession = str(accession_number).replace("-", "")
    return f"{ARCHIVES_URL}/{cik_number}/{accession}/"


def _looks_like_xml(text: str) -> bool:
    """XML con o sin declaracion `<?xml`; la version renderizada XSLT es HTML
    (<!DOCTYPE html> / <html) y eso es lo unico que hay que descartar."""
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        return False
    return head.startswith("<")


RETRY_STATUSES = {403, 429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (2.0, 6.0)


def get_text(
    url: str,
    client: httpx.Client | None,
    *,
    headers: dict[str, str],
    throttle,
    sleep,
) -> str:
    """GET con backoff ante 403/429/5xx de la SEC (limite por IP): hasta 3 intentos.

    ``throttle`` y ``sleep`` los inyecta el conector llamante (sus globales,
    resueltos en tiempo de llamada) para que los monkeypatch de los tests
    sigan actuando sobre el modulo del conector, no sobre este.
    """
    attempt = 0
    while True:
        throttle()
        try:
            if client is not None:
                response = client.get(url, headers=headers)
            else:
                with httpx.Client(timeout=30, headers=headers) as owned:
                    response = owned.get(url)
        except httpx.TransportError as exc:
            _record_sec_transport_failure(get_data_source_registry(), exc)
            raise
        from app.services.connectors.sec_pacing import rate_limited

        rate_limited(response)
        if getattr(response, "status_code", 200) in RETRY_STATUSES and attempt < len(RETRY_BACKOFF_SECONDS):
            sleep(RETRY_BACKOFF_SECONDS[attempt])
            attempt += 1
            continue
        registry = get_data_source_registry()
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 404):
                raise  # documento inexistente: dato por emisor
            _record_sec_http_failure(registry, exc)
            raise
        # Sin éxito aquí: un 200 no basta (puede ser un challenge HTML). El
        # éxito lo registra el consumidor tras validar el formato.
        return response.text


def recent_filings(
    cik: str | int,
    *,
    forms: frozenset[str] | set[str],
    limit: int,
    client: httpx.Client | None,
    headers: dict[str, str],
    throttle,
) -> list[dict]:
    """Filings recientes de un CIK filtrados por ``forms`` (submissions JSON).

    Cuerpo comun de ``form4.recent_form4_filings`` y
    ``form13dg.recent_form13dg_filings``: mismo listado, mismo orden de
    columnas y mismas URLs; solo cambia el conjunto de formularios aceptados
    y el ``limit`` por defecto, que fija cada wrapper.
    """
    url = SUBMISSIONS_URL.format(cik=_pad_cik(cik))
    # Cabeceras ANTES del throttle: el sello del intervalo se fija justo antes de
    # salir a la red. Preparar despues (el primer ``get_settings()`` cuesta
    # ~15 ms) se comia parte del hueco y acortaba la separacion real entre
    # peticiones, que es justo lo que la SEC mide. Por eso ``headers`` llega
    # ya construido desde el wrapper.
    registry = get_data_source_registry()
    started = time.perf_counter()
    throttle()
    try:
        if client is not None:
            response = client.get(url, headers=headers)
        else:
            with httpx.Client(timeout=30, headers=headers) as owned:
                response = owned.get(url)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 404):
            raise  # CIK sin datos: dato por emisor, no fuente caida
        _record_sec_http_failure(registry, exc)
        raise
    except httpx.TransportError as exc:
        _record_sec_transport_failure(registry, exc)
        raise
    except ValueError:
        registry.record_failure(_REGISTRY_KEY, "respuesta no JSON")
        raise
    _record_sec_outcome(registry, started)
    recent = (payload.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber", []) or []
    cik_number = str(int(str(cik).strip()))
    items: list[dict] = []

    def _col(name: str, index: int):
        values = recent.get(name, []) or []
        return values[index] if index < len(values) else None

    for index, accession in enumerate(accessions):
        form = str(_col("form", index) or "").strip().upper()
        # Las enmiendas (/A) corrigen un filing previo; excluirlas dejaba
        # correcciones invisibles. Que cuenten o no lo decide ``forms``.
        if form not in forms:
            continue
        primary = _col("primaryDocument", index)
        accession_nodash = str(accession).replace("-", "")
        index_url = f"{ARCHIVES_URL}/{cik_number}/{accession_nodash}/"
        items.append(
            {
                "form": form,
                "accession_number": accession,
                "filing_date": _col("filingDate", index),
                "report_date": _col("reportDate", index),
                "primary_document": primary,
                "index_url": index_url,
                "document_url": f"{index_url}{primary}" if primary else index_url,
            }
        )
        if len(items) >= limit:
            break
    return items
