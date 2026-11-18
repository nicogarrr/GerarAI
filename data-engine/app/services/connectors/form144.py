"""Conector Form 144 (aviso de venta PROPUESTA, Rule 144) sobre SEC EDGAR.

Gratis, sin API key, datos publicos de la SEC (dominio publico, obra del
Gobierno de EE. UU.); mismo transporte EDGAR que ``form4`` (submissions
JSON, backoff 403/429/5xx, rate-limit compartido en ``connectors/base.py``).

Por que es una fuente nueva y no una extension del Form 4: un Form 144 es
un AVISO de venta propuesta de titulos restringidos o de control. Lo
presenta el vendedor (insider) ANTES o en el momento de vender; NUNCA es
una venta ejecutada y no puede sumarse a las operaciones P/S del feed
insider (veracidad: intencion declarada, no hecho). La fecha de venta es
la ``approxSaleDate`` declarada por el filer.

Retraso: el filing es publico en EDGAR el mismo dia de su presentacion
(horario EDGAR); no hay dato mas fresco gratis.

Listado por emisor: los Form 144 aparecen en el submissions JSON del
EMISOR aunque los presente el vendedor o su agente (verificado
2026-11-18 con AURA: el accession 0001997710-26-000007, presentado bajo
el CIK de la vendedora, figura en las submissions del emisor CIK
1501796 y el documento se sirve bajo el directorio del emisor).

Implementacion propia sobre el esquema XML ``edgarSubmission`` (namespace
http://www.sec.gov/edgar/ownership), parseado con defusedxml y nombres
locales (sin prefijo). Referencia de solo lectura: edgartools
``edgar/ownership/form144.py`` (nombres de etiquetas) y el "EDGAR Form
144 XML Technical Specification" de la SEC.

No se anade ninguna dependencia: NO tocar requirements.txt por esto.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET  # nosec B314  # stdlib solo para tipos (Element) y ParseError; el parseo usa defusedxml

import httpx

# XML externo (SEC EDGAR): defusedxml solo para PARSEAR.
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from app.services.connectors import edgar_common

# Transporte EDGAR compartido (ver ``form4``): alias directos para que la
# identidad sea la de edgar_common y los monkeypatch de los tests sigan
# actuando sobre el transporte comun.
SUBMISSIONS_URL = edgar_common.SUBMISSIONS_URL
ARCHIVES_URL = edgar_common.ARCHIVES_URL
MIN_INTERVAL_SECONDS = edgar_common.MIN_INTERVAL_SECONDS
_throttle = edgar_common._throttle  # == base.sec_throttle (test_sec_throttle_shared)
resolve_user_agent = edgar_common.resolve_user_agent
default_headers = edgar_common.default_headers
filing_index_url = edgar_common.filing_index_url
RETRY_STATUSES = edgar_common.RETRY_STATUSES
RETRY_BACKOFF_SECONDS = edgar_common.RETRY_BACKOFF_SECONDS


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _get_text(url: str, client: httpx.Client | None) -> str:
    """GET con backoff ante 403/429/5xx de la SEC (limite por IP): hasta 3 intentos."""
    return edgar_common.get_text(url, client, headers=default_headers(), throttle=_throttle, sleep=_sleep)


FORM144_FAMILY = frozenset({"144", "144/A"})


def recent_form144_filings(
    cik: str | int,
    *,
    limit: int = 40,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Filings Form 144 recientes del EMISOR desde el submissions JSON (sincrono).

    Incluye enmiendas (144/A): corrigen un aviso previo y excluirlas dejaba
    correcciones invisibles. Cada enmienda es un filing propio (fila propia,
    como en Form 4 y 13D/G); nunca sobrescribe el aviso que corrige.
    """
    return edgar_common.recent_filings(
        cik,
        forms=FORM144_FAMILY,
        limit=limit,
        client=client,
        headers=default_headers(),
        throttle=_throttle,
    )


_RENDERED_XSL_RE = re.compile(r"/xsl144X\d+/", re.IGNORECASE)


def raw_document_url(document_url: str) -> str:
    """URL del documento CRUDO a partir de la de EDGAR.

    El submissions JSON apunta ``primaryDocument`` a la version renderizada
    para humanos (…/xsl144Xnn/primary_doc.xml), que es HTML y revienta el
    parser (mismo fallo que F310 en Form 4). El XML crudo vive en el
    directorio del filing con el mismo nombre de archivo. Si la URL no es
    una variante renderizada, se devuelve tal cual.
    """
    return edgar_common.raw_document_url(document_url, _RENDERED_XSL_RE)


def _local(tag: str) -> str:
    """Nombre local de una etiqueta (sin namespace)."""
    return tag.rsplit("}", 1)[-1]


def _is_form144_xml(text: str) -> bool:
    """Parseo real: solo vale XML bien formado con raiz <edgarSubmission>.

    `<div>AccessDenied</div>` o un AccessDenied XML de la SEC no pasan.
    """
    try:
        root = DefusedET.fromstring(text)
    except ET.ParseError:
        return False
    except DefusedXmlException:
        # Entidades/DTD rechazadas por defusedxml: el documento ES XML de
        # EDGAR (no un AccessDenied HTML); la decision de seguridad la toma
        # parse_form144_xml, que lo marca unparsed y se conserva. Devolver
        # False aqui lo convertia en ValueError y el monitor lo redescargaba
        # cada tick en lugar de dejarlo N/D.
        return True
    return _local(root.tag) == "edgarSubmission"


def fetch_filing_xml(
    document_url: str,
    *,
    client: httpx.Client | None = None,
) -> str:
    """Descarga el XML del documento primario (solo hosts sec.gov).

    Si la URL servida es la version renderizada en HTML (xsl144Xnn), se
    reintenta con el documento crudo del mismo directorio.
    """
    from urllib.parse import urlparse

    hostname = (urlparse(document_url).hostname or "").lower()
    if hostname not in {"sec.gov", "www.sec.gov"}:
        raise ValueError("Solo se descargan filings de sec.gov")
    text = _get_text(document_url, client)
    if _is_form144_xml(text):
        return text
    raw_url = raw_document_url(document_url)
    if raw_url != document_url:
        raw_text = _get_text(raw_url, client)
        if _is_form144_xml(raw_text):
            return raw_text
    raise ValueError("El documento no es un Form 144 XML valido")


def _child(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    for child in el:
        if _local(child.tag) == name:
            return child
    return None


def _children(el: ET.Element | None, name: str) -> list[ET.Element]:
    if el is None:
        return []
    return [child for child in el if _local(child.tag) == name]


def _text(el: ET.Element | None, name: str) -> str | None:
    if el is None:
        return None
    child = _child(el, name)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _texts(el: ET.Element | None, name: str) -> list[str]:
    if el is None:
        return []
    return [
        child.text.strip()
        for child in _children(el, name)
        if child.text and child.text.strip()
    ]


_INT_RE = re.compile(r"[^0-9.-]")


def _to_int(value: str | None) -> int | None:
    """Entero tolerante (comas de miles, espacios). Ausente o ilegible: None."""
    if not value:
        return None
    cleaned = _INT_RE.sub("", value)
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = _INT_RE.sub("", value)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _yes_no(value: str | None) -> bool | None:
    """Bandera Y/N de la SEC: ausente o irreconocible queda None, jamas False."""
    if value is None:
        return None
    flag = value.strip().upper()
    if flag == "Y":
        return True
    if flag == "N":
        return False
    return None


def _parse_securities_information(el: ET.Element) -> dict:
    broker_el = _child(el, "brokerOrMarketmakerDetails")
    return {
        "securities_class_title": _text(el, "securitiesClassTitle"),
        "broker_name": _text(broker_el, "name"),
        "shares": _to_int(_text(el, "noOfUnitsSold")),
        "market_value": _to_float(_text(el, "aggregateMarketValue")),
        "shares_outstanding": _to_int(_text(el, "noOfUnitsOutstanding")),
        "approx_sale_date": _text(el, "approxSaleDate"),
        "exchange": _text(el, "securitiesExchangeName"),
    }


def _parse_acquisition(el: ET.Element) -> dict:
    return {
        "securities_class_title": _text(el, "securitiesClassTitle"),
        "acquired_date": _text(el, "acquiredDate"),
        "nature_of_acquisition": _text(el, "natureOfAcquisitionTransaction"),
        "acquired_from": _text(el, "nameOfPersonfromWhomAcquired"),
        "is_gift": _yes_no(_text(el, "isGiftTransaction")),
        "shares_acquired": _to_int(_text(el, "amountOfSecuritiesAcquired")),
        "payment_date": _text(el, "paymentDate"),
        "nature_of_payment": _text(el, "natureOfPayment"),
    }


def _parse_sale_past_3m(el: ET.Element) -> dict:
    seller_el = _child(el, "sellerDetails")
    return {
        "seller_name": _text(seller_el, "name"),
        "securities_class_title": _text(el, "securitiesClassTitle"),
        "sale_date": _text(el, "saleDate"),
        "shares_sold": _to_int(_text(el, "amountOfSecuritiesSold")),
        "gross_proceeds": _to_float(_text(el, "grossProceeds")),
    }


def parse_form144_xml(text: str) -> dict:
    """Parsea un Form 144 XML. Nunca lanza: lo ilegible queda parsed_ok=False.

    Los campos que el filer no declaro quedan None (N/D), nunca inventados.
    """
    result: dict = {
        "parsed_ok": False,
        "submission_type": None,
        "seller_cik": None,
        "seller_name": None,
        "relationships": [],
        "issuer_cik": None,
        "issuer_name": None,
        "sec_file_number": None,
        "securities": [],
        "acquisitions": [],
        "sales_past_3m": [],
        "nothing_to_report_past_3m": None,
        "notice_date": None,
        "plan_adoption_dates": [],
        "remarks": None,
        "error": None,
    }
    try:
        root = DefusedET.fromstring(text)
    except ET.ParseError as exc:
        result["error"] = f"xml_invalido: {type(exc).__name__}"
        return result
    except DefusedXmlException as exc:
        # Entidades/DTD/referencias externas rechazadas por defusedxml: N/D,
        # nunca una excepcion al monitor (EntitiesForbidden y familia).
        result["error"] = f"xml_rechazado: {type(exc).__name__}"
        return result
    if _local(root.tag) != "edgarSubmission":
        result["error"] = f"raiz_inesperada: {_local(root.tag)}"
        return result

    header = _child(root, "headerData")
    result["submission_type"] = _text(header, "submissionType")
    if result["submission_type"] not in ("144", "144/A"):
        # Otro edgarSubmission (SC 13D, Form 4, ...) no es un Form 144 aunque
        # comparta etiquetas (issuerCik, ...): no se publica como aviso 144.
        result["error"] = f"tipo_inesperado: {result['submission_type']!r}"
        return result
    filer_info = _child(header, "filerInfo")
    filer = _child(filer_info, "filer")
    credentials = _child(filer, "filerCredentials")
    result["seller_cik"] = _text(credentials, "cik")

    form_data = _child(root, "formData")
    if form_data is None:
        result["error"] = "sin_formData"
        return result
    issuer = _child(form_data, "issuerInfo")
    result["issuer_cik"] = _text(issuer, "issuerCik")
    result["issuer_name"] = _text(issuer, "issuerName")
    if not result["issuer_cik"]:
        # Sin emisor declarado no hay atribucion verificable: queda unparsed
        # (N/D), nunca publicado como aviso verificado del emisor del listado.
        result["error"] = "sin_issuer_cik"
        return result
    result["sec_file_number"] = _text(issuer, "secFileNumber")
    # El vendedor puede repetirse (varios bloques): primer nombre no vacio.
    seller_names = _texts(issuer, "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold")
    result["seller_name"] = seller_names[0] if seller_names else None
    result["relationships"] = _texts(_child(issuer, "relationshipsToIssuer"), "relationshipToIssuer")

    result["securities"] = [
        _parse_securities_information(el) for el in _children(form_data, "securitiesInformation")
    ]
    result["acquisitions"] = [
        _parse_acquisition(el) for el in _children(form_data, "securitiesToBeSold")
    ]
    result["nothing_to_report_past_3m"] = _yes_no(
        _text(form_data, "nothingToReportFlagOnSecuritiesSoldInPast3Months")
    )
    result["sales_past_3m"] = [
        _parse_sale_past_3m(el) for el in _children(form_data, "securitiesSoldInPast3Months")
    ]

    signature = _child(form_data, "noticeSignature")
    result["notice_date"] = _text(signature, "noticeDate")
    result["plan_adoption_dates"] = _texts(
        _child(signature, "planAdoptionDates"),
        "planAdoptionDate",
    )
    result["remarks"] = _text(form_data, "remarks")
    result["parsed_ok"] = True
    return result


def proposed_sale_totals(parsed: dict) -> dict:
    """Totales de los bloques securitiesInformation de un Form 144 parseado.

    Las sumas son DERIVADAS de cifras declaradas: un total solo se publica
    cuando TODOS los bloques lo tienen; si falta alguno, None (nunca un
    subtotal presentado como total).
    """
    securities = parsed.get("securities") or []

    def _sum(field: str) -> float | None:
        values = [row.get(field) for row in securities]
        if not values or any(v is None for v in values):
            return None
        return float(sum(values))

    first = securities[0] if securities else {}
    return {
        "shares_to_sell": (lambda v: int(v) if v is not None else None)(_sum("shares")),
        "aggregate_market_value": _sum("market_value"),
        "shares_outstanding": first.get("shares_outstanding"),
        "approx_sale_date": first.get("approx_sale_date"),
        "exchange": first.get("exchange"),
        "broker_name": first.get("broker_name"),
        "securities_class_title": first.get("securities_class_title"),
    }
