"""Conector SC 13D/13G (titulares >5%) sobre SEC EDGAR. Gratis, sin API key.

Un Schedule 13D/13G declara quien posee mas del 5% de una clase de acciones:
es la fuente primaria de propiedad institucional/activista (p. ej. el 13G de
BlackRock sobre ASTS del 27-oct-2026). Hasta aqui la ingesta SEC de noticias
filtraba 10-K/10-Q/8-K/20-F/6-K y el carril insider solo Form 4/4-A: estos
filings eran invisibles para la app.

Diseno propio, mismo transporte EDGAR que ``form4.py`` (cero dependencias
nuevas, stdlib+httpx). Este conector nacio como "espejo" de form4.py con la
logica copiada a mano; el transporte compartido vive ahora en
``connectors/edgar_common.py`` (submissions JSON, cabeceras, backoff
403/429/5xx, registro de salud) y el espejo es por construccion: mismo
codigo importado, imposible de desalinear. Lo especifico de 13D/13G queda
aqui:
- submissions JSON de data.sec.gov para listar SC 13D/13G y enmiendas (/A) por
  CIK. EDGAR nombra el formulario de dos maneras segun la epoca: familia
  antigua ``SC 13D``/``SC 13G`` y familia nueva ``SCHEDULE 13D``/``SCHEDULE 13G``;
  se aceptan las dos.
- parse del documento primario en DOS formatos:
  * XML estructurado (esquema schedule13d/schedule13g, obligatorio para
    filings nuevos): namespaces tolerantes, campos de portada e Item 4.
  * texto SGML/htm heredado (filings antiguos): extraccion conservadora por
    los rotulos fijos de la portada. Lo que no se lee con certeza queda en
    None: la app muestra N/D y NUNCA inventa cifras.
- ritmo SEC: mismo reloj de proceso que form4/form13f (``connectors/base.py``);
  la SEC limita por IP, no por modulo.

No se anade ninguna dependencia: NO tocar requirements.txt por esto.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from xml.etree import ElementTree as ET  # nosec B314  # stdlib solo para tipos (Element) y ParseError: defusedxml no los exporta; el parseo usa defusedxml

import httpx

# XML externo (SEC EDGAR): defusedxml solo para PARSEAR.
from defusedxml import ElementTree as DefusedET

from app.core.errors import redact_secrets
from app.services.connectors import edgar_common
from app.services.data_source_health import get_data_source_registry

# Transporte EDGAR compartido (ver la docstring de cabecera): alias directos,
# NO wrappers, para que la identidad sea la de edgar_common.
SUBMISSIONS_URL = edgar_common.SUBMISSIONS_URL
ARCHIVES_URL = edgar_common.ARCHIVES_URL
MIN_INTERVAL_SECONDS = edgar_common.MIN_INTERVAL_SECONDS
_throttle = edgar_common._throttle  # == base.sec_throttle
default_headers = edgar_common.default_headers
filing_index_url = edgar_common.filing_index_url
RETRY_STATUSES = edgar_common.RETRY_STATUSES
RETRY_BACKOFF_SECONDS = edgar_common.RETRY_BACKOFF_SECONDS
_record_sec_outcome = edgar_common._record_sec_outcome
_record_sec_http_failure = edgar_common._record_sec_http_failure
_record_sec_transport_failure = edgar_common._record_sec_transport_failure
_looks_like_xml = edgar_common._looks_like_xml
resolve_user_agent = edgar_common.resolve_user_agent


# Formularios aceptados: las dos familias de EDGAR y sus enmiendas (/A).
# Una enmienda corrige un filing previo; excluirla dejaba correcciones
# invisibles, igual que con los Form 4/A.
FORMS_13DG: frozenset[str] = frozenset(
    {
        "SC 13D",
        "SC 13D/A",
        "SC 13G",
        "SC 13G/A",
        "SCHEDULE 13D",
        "SCHEDULE 13D/A",
        "SCHEDULE 13G",
        "SCHEDULE 13G/A",
    }
)


def recent_form13dg_filings(
    cik: str | int,
    *,
    limit: int = 40,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Filings SC 13D/13G (y /A) recientes desde el submissions JSON (sincrono)."""
    return edgar_common.recent_filings(
        cik,
        forms=FORMS_13DG,
        limit=limit,
        client=client,
        headers=default_headers(),
        throttle=_throttle,
    )


_RENDERED_XSL_RE = re.compile(r"/xslschedule_13[dg]_x\d+/", re.IGNORECASE)


def raw_document_url(document_url: str) -> str:
    """URL del documento CRUDO a partir de la de EDGAR.

    Igual que F310 en Form 4: el submissions JSON apunta ``primaryDocument``
    a la version renderizada para humanos (…/xslSCHEDULE_13G_X02/primary_doc.xml),
    que es HTML y revienta el parser XML. El documento crudo vive en el
    directorio del filing con el mismo nombre de archivo. Si la URL no es una
    variante renderizada, se devuelve tal cual.
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(document_url)
    match = _RENDERED_XSL_RE.search(parsed.path)
    if not match:
        return document_url
    raw_path = parsed.path[: match.start()] + "/" + parsed.path[match.end() :]
    return urlunparse(parsed._replace(path=raw_path))


def _is_13dg_xml(text: str) -> bool:
    """Parseo real: solo vale XML bien formado con raíz <edgarSubmission>
    (esquema schedule13d/13g). `<div>AccessDenied</div>` no pasa."""
    try:
        root = DefusedET.fromstring(text)
    except ET.ParseError:
        return False
    return root.tag.rsplit("}", 1)[-1] == "edgarSubmission"


def _get_text(url: str, client: httpx.Client | None) -> str:
    """GET con backoff ante 403/429/5xx de la SEC (limite por IP): hasta 3 intentos."""
    return edgar_common.get_text(url, client, headers=default_headers(), throttle=_throttle, sleep=time.sleep)


def fetch_filing_document(
    document_url: str,
    *,
    client: httpx.Client | None = None,
) -> str:
    """Descarga el documento primario (solo hosts sec.gov).

    Devuelve XML (esquema nuevo) o texto SGML/htm (filings heredados): el
    parse decide el formato. Si la URL servida es la version renderizada en
    HTML (xslSCHEDULE_13[DG]_Xnn), se reintenta con el documento crudo del
    mismo directorio (mismo motivo que F310 en Form 4).
    """
    from urllib.parse import urlparse

    hostname = (urlparse(document_url).hostname or "").lower()
    if hostname not in {"sec.gov", "www.sec.gov"}:
        raise ValueError("SC 13D/13G document URL must use sec.gov")
    registry = get_data_source_registry()
    started = time.perf_counter()
    text = _get_text(document_url, client)
    if not _RENDERED_XSL_RE.search(urlparse(document_url).path):
        # Documento primario: puede ser XML (esquema nuevo) o HTML heredado
        # (un 13D/G antiguo cuyo primario ES un .htm legitimo). Un 200 que no
        # es ni XML ni lleva la marca de tipo SC 13D/G (un challenge HTML de
        # WAF no la lleva) no es un documento: deriva de formato, no éxito.
        if (
            not _is_13dg_xml(text)
            and _SGML_TYPE_RE.search(text) is None
            and _LEGACY_DOC_RE.search(text) is None
        ):
            registry.record_failure(
                edgar_common._REGISTRY_KEY, "200 sin documento 13D/G válido (parse failed)"
            )
            raise ValueError("SC 13D/13G document is neither XML nor a recognizable 13D/G text")
        _record_sec_outcome(registry, started)
        return text
    # URL renderizada (…/xslSCHEDULE_13[DG]_Xnn/fichero): es HTML para
    # humanos; el documento crudo vive en el directorio del filing.
    raw_url = raw_document_url(document_url)
    raw_text = _get_text(raw_url, client)
    if (
        not _is_13dg_xml(raw_text)
        and _SGML_TYPE_RE.search(raw_text) is None
        and _LEGACY_DOC_RE.search(raw_text) is None
    ):
        registry.record_failure(edgar_common._REGISTRY_KEY, "200 sin documento 13D/G válido (parse failed)")
        raise ValueError("SC 13D/13G raw document is rendered HTML too")
    _record_sec_outcome(registry, started)
    return raw_text


# ---------------- Parse del documento primario ----------------

# XML nuevo: <edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g" …>
# (y schedule13d). Los tags llevan namespace; se compara por nombre local.
# Portadas HTML heredadas llevan "SCHEDULE 13D/G" o "SC 13D/G" como texto
# visible (sin la cabecera SGML): un challenge HTML de WAF no lleva ninguna.
_LEGACY_DOC_RE = re.compile(r"(?:SCHEDULE|SC)\s+13[DG](?:/A)?", re.IGNORECASE)
_SGML_TYPE_RE = re.compile(
    r"(?:CONFORMED\s+SUBMISSION\s+TYPE|<TYPE>)\s*:?\s*(SC\s*13[DG](?:/A)?|SCHEDULE\s+13[DG](?:/A)?)",
    re.IGNORECASE,
)
_INT_RE = re.compile(r"^[\d,]+$")
_PERCENT_RE = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*%?$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_local(elem: ET.Element | None, name: str) -> ET.Element | None:
    if elem is None:
        return None
    for child in elem:
        if _local(child.tag) == name:
            return child
    return None


def _text_local(elem: ET.Element | None, name: str) -> str | None:
    node = _find_local(elem, name)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _parse_int(raw: str | None) -> int | None:
    """Entero SEC con comas de miles; None ante cualquier duda (nunca inventar).

    Acciones y poder de voto son siempre >= 0: un negativo es un error de
    parseo y queda N/D, igual que un valor ilegible.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not _INT_RE.match(text):
        return None
    try:
        value = int(text.replace(",", ""))
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _parse_percent(raw: str | None) -> float | None:
    """Porcentaje de clase. Fuera de (0, 100] es un error de parseo: None."""
    if raw is None:
        return None
    match = _PERCENT_RE.match(raw.strip())
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    if value <= 0 or value > 100:
        return None
    return value


def _parse_date(raw: str | None) -> str | None:
    """Fecha SEC (MM/DD/YYYY habitual, tambien YYYY-MM-DD) -> ISO YYYY-MM-DD."""
    if not raw:
        return None
    text = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _empty_parse(form: str | None = None) -> dict:
    return {
        "format": "unknown",
        "parsed_ok": False,
        "error": None,
        "form": form,
        "is_amendment": bool(form and form.endswith("/A")),
        "filer_cik": None,
        "issuer_cik": None,
        "issuer_name": None,
        "cusip": None,
        "securities_class_title": None,
        "rule": None,
        "holder_name": None,
        "aggregate_shares": None,
        "percent_of_class": None,
        "sole_voting_power": None,
        "shared_voting_power": None,
        "sole_dispositive_power": None,
        "shared_dispositive_power": None,
        "holders": [],
        "snapshot_date": None,
        "signature_date": None,
    }


def _parse_xml(text: str) -> dict:
    """Portada del esquema schedule13d/schedule13g (namespaces tolerantes)."""
    root = DefusedET.fromstring(text)
    if _local(root.tag) != "edgarSubmission":
        raise ValueError("root element is not edgarSubmission")

    header = _find_local(root, "headerData")
    form_data = _find_local(root, "formData")
    cover = _find_local(form_data, "coverPageHeader")
    issuer = _find_local(cover, "issuerInfo")
    cusips = _find_local(issuer, "issuerCusips")
    rules = _find_local(cover, "designateRulesPursuantThisScheduleFiled")

    form = (_text_local(header, "submissionType") or "").strip().upper() or None

    holders: list[dict] = []
    if form_data is not None:
        person_details = [
            elem for elem in form_data if _local(elem.tag) == "coverPageHeaderReportingPersonDetails"
        ]
    else:
        person_details = []
    # coverPageHeaderReportingPersonDetails puede repetirse (varios declarantes).
    for elem in person_details:
        powers = _find_local(elem, "reportingPersonBeneficiallyOwnedNumberOfShares")
        holders.append(
            {
                "name": _text_local(elem, "reportingPersonName"),
                "aggregate_shares": _parse_int(
                    _text_local(elem, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares")
                ),
                "percent_of_class": _parse_percent(_text_local(elem, "classPercent")),
                "sole_voting_power": _parse_int(_text_local(powers, "soleVotingPower")),
                "shared_voting_power": _parse_int(_text_local(powers, "sharedVotingPower")),
                "sole_dispositive_power": _parse_int(_text_local(powers, "soleDispositivePower")),
                "shared_dispositive_power": _parse_int(_text_local(powers, "sharedDispositivePower")),
            }
        )

    # Item 4 como respaldo cuando la portada no trae agregado/porcentaje.
    item4 = None
    items = _find_local(form_data, "items")
    if items is not None:
        for elem in items:
            if _local(elem.tag) == "item4":
                item4 = elem
                break

    primary = holders[0] if holders else {}
    filer = _find_local(_find_local(_find_local(header, "filerInfo"), "filer"), "filerCredentials")
    signature = _find_local(_find_local(form_data, "signatureInformation"), "signatureDetails")

    aggregate = primary.get("aggregate_shares")
    if aggregate is None and item4 is not None:
        aggregate = _parse_int(_text_local(item4, "amountBeneficiallyOwned"))
    percent = primary.get("percent_of_class")
    if percent is None and item4 is not None:
        percent = _parse_percent(_text_local(item4, "classPercent"))

    return {
        "format": "xml",
        "parsed_ok": True,
        "error": None,
        "form": form,
        "is_amendment": bool(form and form.endswith("/A")),
        "filer_cik": (_text_local(filer, "cik") or "").lstrip("0") or _text_local(filer, "cik"),
        "issuer_cik": (_text_local(issuer, "issuerCik") or "").lstrip("0")
        or _text_local(issuer, "issuerCik"),
        "issuer_name": _text_local(issuer, "issuerName"),
        "cusip": _text_local(cusips, "issuerCusipNumber"),
        "securities_class_title": _text_local(cover, "securitiesClassTitle"),
        "rule": _text_local(rules, "designateRulePursuantThisScheduleFiled"),
        "holder_name": primary.get("name"),
        "aggregate_shares": aggregate,
        "percent_of_class": percent,
        "sole_voting_power": primary.get("sole_voting_power"),
        "shared_voting_power": primary.get("shared_voting_power"),
        "sole_dispositive_power": primary.get("sole_dispositive_power"),
        "shared_dispositive_power": primary.get("shared_dispositive_power"),
        "holders": holders,
        "snapshot_date": _parse_date(_text_local(cover, "eventDateRequiresFilingThisStatement")),
        "signature_date": _parse_date(_text_local(signature, "date")),
    }


def _legacy_value_after(
    text: str,
    labels: tuple[str, ...],
    *,
    valid: re.Pattern | None = None,
) -> str | None:
    """Primera linea valida tras un rotulo fijo de la portada SGML.

    Conservador por diseño: con ``valid`` (p. ej. entero o porcentaje) las
    lineas que no cuadran se descartan — el propio numero de fila del rotulo
    («ROW 11») no puede hacerse pasar por el valor — y si ninguna linea
    cercana valida, devuelve None (N/D), nunca un inventado.
    """
    for label in labels:
        match = re.search(label, text, flags=re.IGNORECASE)
        if not match:
            continue
        for line in text[match.end() :].splitlines()[0:6]:
            # Las portadas .htm heredadas llevan tags inline (<TD>, </P>...):
            # se retiran para que el valor real quede visible; en SGML plano
            # no hay tags y esto no cambia nada.
            candidate = re.sub(r"<[^>]+>", " ", line)
            candidate = re.sub(r"\s+", " ", candidate).strip().strip(":")
            if not candidate:
                continue
            # La linea IRS del bloque 1 no es el nombre del declarante.
            if re.match(r"(?i)i\.?r\.?s\.?\s", candidate):
                continue
            if valid is not None and not valid.match(candidate):
                continue
            return candidate
    return None


_SGML_ISSUER_CIK_RE = re.compile(
    r"SUBJECT\s+COMPANY.*?CENTRAL\s+INDEX\s+KEY\s*:\s*0*(\d{1,10})",
    re.IGNORECASE | re.DOTALL,
)
_SGML_ISSUER_NAME_RE = re.compile(
    r"SUBJECT\s+COMPANY.*?COMPANY\s+CONFORMED\s+NAME\s*:\s*([^\n]+)",
    re.IGNORECASE | re.DOTALL,
)
_SGML_FILER_CIK_RE = re.compile(
    r"FILER:.*?CENTRAL\s+INDEX\s+KEY\s*:\s*0*(\d{1,10})",
    re.IGNORECASE | re.DOTALL,
)


def _parse_legacy(text: str, form: str | None) -> dict:
    """Portada heredada SGML/htm: extraccion por rotulos fijos, fail-closed."""
    result = _empty_parse(form)
    result["format"] = "legacy-text"

    # La cabecera SGML (<SEC-HEADER>) identifica al emisor (SUBJECT COMPANY)
    # y al declarante (FILER) con su CIK: es lo que permite verificar que el
    # filing es del emisor pedido antes de persistirlo.
    header = text[:8000]
    issuer_cik = _SGML_ISSUER_CIK_RE.search(header)
    if issuer_cik:
        result["issuer_cik"] = issuer_cik.group(1)
    issuer_name = _SGML_ISSUER_NAME_RE.search(header)
    if issuer_name:
        result["issuer_name"] = issuer_name.group(1).strip() or None
    filer_cik = _SGML_FILER_CIK_RE.search(header)
    if filer_cik:
        result["filer_cik"] = filer_cik.group(1)

    holder = _legacy_value_after(text, (r"NAME\s+OF\s+REPORTING\s+PERSONS?",))
    if holder and len(holder) <= 300:
        result["holder_name"] = holder
        result["holders"] = [{"name": holder}]

    aggregate = _legacy_value_after(
        text,
        (r"AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED\s+BY\s+EACH\s+REPORTING\s+PERSON",),
        valid=_INT_RE,
    )
    parsed_aggregate = _parse_int(aggregate)
    if parsed_aggregate is not None:
        result["aggregate_shares"] = parsed_aggregate

    percent = _legacy_value_after(
        text,
        (r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW\s*(?:NO\.?\s*)?\d*",),
        valid=_PERCENT_RE,
    )
    parsed_percent = _parse_percent(percent)
    if parsed_percent is not None:
        result["percent_of_class"] = parsed_percent

    snapshot = _legacy_value_after(
        text,
        (
            r"Date\s+of\s+Event\s+Which\s+Requires\s+Filing\s+of\s+this\s+Statement",
            r"Date\s+of\s+Event\s+Requiring\s+Filing",
        ),
    )
    result["snapshot_date"] = _parse_date(snapshot)

    cusip_match = re.search(r"CUSIP\s+(?:No\.?|Number)\s*[:\s]*([0-9A-Z]{6,9})", text, re.IGNORECASE)
    if cusip_match:
        result["cusip"] = cusip_match.group(1)

    result["parsed_ok"] = any(
        value is not None
        for value in (result["holder_name"], result["aggregate_shares"], result["percent_of_class"])
    )
    if not result["parsed_ok"]:
        result["error"] = "legacy cover page labels not found"
    return result


def parse_schedule13dg(text: str) -> dict:
    """Parse del documento primario de un SC 13D/13G. Nunca lanza.

    Campos no legibles = None (la app los muestra N/D); ``parsed_ok`` dice si
    se extrajo algo con certeza. Un documento roto o en un formato desconocido
    devuelve ``parsed_ok=False`` con ``error``, nunca cifras inventadas.
    """
    if not text or not text.strip():
        return {**_empty_parse(), "error": "empty document"}

    # El sobre SGML (<SEC-DOCUMENT>/<SEC-HEADER>) tambien empieza por "<":
    # sin esta guarda se intentaria parsear como XML y fallaria.
    head = text.lstrip()[:500].lower()
    is_sgml = head.startswith(("<sec-document", "<sec-header")) or bool(_SGML_TYPE_RE.search(text[:4000]))
    if _looks_like_xml(text) and not is_sgml:
        try:
            return _parse_xml(text)
        except (ET.ParseError, ValueError) as exc:
            return {
                **_empty_parse(),
                "format": "xml",
                "error": redact_secrets(f"{type(exc).__name__}: {exc}")[:300],
            }

    sgml_form = None
    match = _SGML_TYPE_RE.search(text)
    if match:
        sgml_form = re.sub(r"\s+", " ", match.group(1).strip().upper())
    return _parse_legacy(text, sgml_form)
