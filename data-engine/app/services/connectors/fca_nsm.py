"""Conector NSM de la FCA (National Storage Mechanism del Reino Unido).

El NSM es el archivo oficial donde las emisoras con valores admitidos en
mercados del Reino Unido depositan su informacion regulada (DTR 6.3): informe
anual, semestral, resultados (RNS). Gratis, sin clave ni registro.

Por que hace falta ademas de filings.xbrl.org (medido 2026-11-08):
- el indice de XBRL International va con un ano de retraso para el Reino
  Unido: Associated British Foods deposito su ESEF FY2026 (cierre
  2026-09-12) en el NSM el 2026-11-05 y el indice solo llega a 2025-09-13;
  BATM, Nanoco o Endeavour Mining igual (lo ultimo del indice es 2024);
- hay emisoras que el indice no tiene en absoluto (Georgia Capital PLC,
  LEI 213800Q65T5GNBOW7H65: 0 entidades, 1.182 documentos en el NSM).

API (la misma que usa https://data.fca.org.uk/#/nsm/nationalstoragemechanism):
POST https://api.data.fca.org.uk/search?index=nsm-search con un JSON
``{"from", "size", "sortorder", "criteriaObj": {"criteria": [...]}}``. Cada
hit trae ``lei``, ``company``, ``type`` («Annual Financial Report»...),
``document_format`` («Tagged» = paquete ESEF con iXBRL; «Untagged» = xhtml
convertido de PDF sin etiquetas; «PDF»; «Plain text» = anuncio RNS),
``submitted_date`` y ``download_link`` relativo a
https://data.fca.org.uk/artefacts/. El nombre del paquete etiquetado lleva el
cierre del ejercicio: ``..._{LEI}-{AAAA-MM-DD}.zip|.xbri``.

robots.txt de data.fca.org.uk: ``User-agent: * Allow: /`` con
``Content-Signal: search=yes, ai-train=no, use=reference``. Aqui solo se
leen hechos declarados para citarlos con su URL (referencia); nada se usa
para entrenar. Ritmo: 1 peticion cada 2 s como minimo y User-Agent propio.

Contrato de veracidad: solo hechos iXBRL declarados en el documento (mismo
parser que los paquetes ESEF del emisor, ``esef_ixbrl``), y solo si el LEI
declarado DENTRO del documento es el del emisor pedido. Un paquete
ilegible, sin informe o de otra entidad se descarta con su motivo, nunca se
adivina. Nunca escribe en la BD.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import time
import zipfile
from dataclasses import dataclass
from typing import Any

import httpx

NSM_SEARCH_URL = "https://api.data.fca.org.uk/search"
NSM_INDEX = "nsm-search"
NSM_ARTEFACTS_BASE = "https://data.fca.org.uk/artefacts/"
NSM_SOURCE = "FCA National Storage Mechanism (registro oficial del Reino Unido), consulta por LEI"
USER_AGENT = "GerarAI/1.0 (investigacion de emisoras; contacto: tab@tab.bot)"
ANNUAL_REPORT_TYPE = "Annual Financial Report"
# Un paquete ESEF real ronda 20-40 MB (ABF FY2026: 21 MB zip, informe de
# 36 MB). Por encima de esto no se descarga: motivo explicito.
MAX_PACKAGE_BYTES = 150 * 1024 * 1024
_MIN_INTERVAL_S = 2.0
_last_request_at = 0.0

_PERIOD_IN_LINK = re.compile(r"([0-9A-Z]{20})-(\d{4}-\d{2}-\d{2})\.(?:zip|xbri|xhtml|html)$", re.I)
_REPORT_SUFFIXES = (".xhtml", ".html", ".htm")


class NsmError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NsmFiling:
    disclosure_id: str
    lei: str
    company: str
    filing_type: str
    document_format: str
    submitted_date: str  # AAAA-MM-DD
    download_link: str
    period_end: str | None  # cierre del ejercicio leido del nombre del paquete

    @property
    def url(self) -> str:
        return NSM_ARTEFACTS_BASE + self.download_link.lstrip("/")

    @property
    def tagged(self) -> bool:
        return self.document_format.strip().lower() == "tagged"


async def _throttle() -> None:
    global _last_request_at
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request_at = time.monotonic()


def search_body(lei: str, *, filing_type: str | None = ANNUAL_REPORT_TYPE, size: int = 50) -> dict[str, Any]:
    criteria: list[dict[str, Any]] = [
        {"name": "company_lei", "value": ["", lei, "disclose_org", "related_org"]},
    ]
    if filing_type:
        criteria.append({"name": "type", "value": [filing_type]})
    return {
        "from": 0,
        "size": size,
        "sort": "submitted_date",
        "sortorder": "desc",
        "criteriaObj": {
            "criteria": criteria,
            "dateCriteria": [{"name": "submitted_date", "value": {"from": None, "to": None}}],
        },
    }


def parse_search_hits(payload: Any, *, lei: str | None = None) -> list[NsmFiling]:
    """Filas del NSM; una fila sin LEI, enlace o fecha se descarta.

    El campo ``lei`` de un documento con varias emisoras viene como
    «LEI1;LEI2»: cuenta si ``lei`` es una de ellas."""
    hits = ((payload or {}).get("hits") or {}).get("hits") if isinstance(payload, dict) else None
    out: list[NsmFiling] = []
    for hit in hits if isinstance(hits, list) else []:
        src = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(src, dict):
            continue
        leis = [p.strip().upper() for p in str(src.get("lei") or "").split(";") if p.strip()]
        link = str(src.get("download_link") or "").strip()
        submitted = str(src.get("submitted_date") or src.get("publication_date") or "")[:10]
        if not leis or not link or not submitted:
            continue
        if lei and lei.upper() not in leis:
            continue
        match = _PERIOD_IN_LINK.search(link)
        period_lei = match.group(1).upper() if match else None
        out.append(
            NsmFiling(
                disclosure_id=str(src.get("disclosure_id") or hit.get("_id") or ""),
                lei=(lei or leis[0]).upper(),
                company=str(src.get("company") or "").strip().rstrip(";"),
                filing_type=str(src.get("type") or ""),
                document_format=str(src.get("document_format") or src.get("tag_esef") or ""),
                submitted_date=submitted,
                download_link=link,
                period_end=match.group(2) if match and (period_lei == (lei or leis[0]).upper()) else None,
            )
        )
    return out


def tagged_annual_reports(filings: list[NsmFiling], max_filings: int = 5) -> list[NsmFiling]:
    """Un paquete etiquetado por ejercicio (el ultimo depositado gana: una
    reexpresion o un redeposito sustituye al anterior), mas reciente primero."""
    by_period: dict[str, NsmFiling] = {}
    for f in filings:
        if not f.tagged or not f.period_end or f.filing_type != ANNUAL_REPORT_TYPE:
            continue
        prev = by_period.get(f.period_end)
        if prev is None or f.submitted_date > prev.submitted_date:
            by_period[f.period_end] = f
    return [by_period[p] for p in sorted(by_period, reverse=True)][:max_filings]


def report_from_package(blob: bytes) -> tuple[bytes, str]:
    """(bytes del informe iXBRL, ruta dentro del paquete).

    Un paquete ESEF/UKSEF es un zip (``.zip`` o ``.xbri``) con el informe en
    ``reports/`` (``.xhtml`` o ``.html``); algunos depositos son el xhtml
    suelto. Varios informes: el mayor (el resto son anexos)."""
    if blob[:2] != b"PK":
        head = blob[:4096].lower()
        if b"<html" in head or b"<?xml" in head:
            return blob, ""
        raise NsmError("el deposito no es un paquete zip ni un xhtml")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(_REPORT_SUFFIXES)]
            in_reports = [n for n in names if "/reports/" in f"/{n.lower()}"]
            candidates = in_reports or names
            if not candidates:
                raise NsmError("paquete sin informe xhtml")
            name = max(candidates, key=lambda n: zf.getinfo(n).file_size)
            return zf.read(name), name
    except zipfile.BadZipFile as exc:
        raise NsmError(f"paquete ilegible: {exc}") from exc


class NsmClient:
    """Cliente asincrono del NSM. ``client`` inyectable (tests: MockTransport)."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(60.0, read=180.0)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_filings_for_lei(
        self, lei: str, *, filing_type: str | None = ANNUAL_REPORT_TYPE, size: int = 50
    ) -> list[NsmFiling]:
        await _throttle()
        try:
            resp = await self._client.post(
                NSM_SEARCH_URL,
                params={"index": NSM_INDEX},
                json=search_body(lei, filing_type=filing_type, size=size),
                headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise NsmError(f"busqueda NSM fallida: {type(exc).__name__}") from exc
        return parse_search_hits(payload, lei=lei)

    async def fetch_document(self, filing: NsmFiling) -> tuple[bytes, str]:
        """(bytes, sha256) del documento depositado."""
        await _throttle()
        try:
            async with self._client.stream(
                "GET", filing.url, headers={"User-Agent": USER_AGENT},
                timeout=httpx.Timeout(60.0, read=180.0),
            ) as resp:
                resp.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_PACKAGE_BYTES:
                        raise NsmError(f"documento mayor de {MAX_PACKAGE_BYTES // (1024 * 1024)} MB: no se descarga")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise NsmError(f"descarga NSM fallida: {type(exc).__name__}") from exc
        blob = b"".join(chunks)
        return blob, hashlib.sha256(blob).hexdigest()

    async def fetch_tagged_facts(self, filing: NsmFiling) -> dict[str, Any]:
        """Hechos normalizados (mismo layout que ``normalize_xbrl_json``) de un
        paquete etiquetado, con su procedencia. NsmError si no es del LEI."""
        from app.services.connectors.esef_ixbrl import parse_ixbrl_facts

        blob, sha = await self.fetch_document(filing)
        report, path = report_from_package(blob)
        parsed = parse_ixbrl_facts(io.BytesIO(report))
        declared = (parsed.get("entity_lei") or "").strip().upper()
        if not declared:
            raise NsmError("el documento no declara un LEI: descartado")
        if declared != filing.lei.strip().upper():
            raise NsmError(f"el documento declara el LEI {declared}, no {filing.lei}: descartado")
        if not parsed.get("facts"):
            raise NsmError("paquete sin hechos iXBRL")
        return {
            "facts": parsed["facts"],
            "dropped": parsed.get("dropped", 0),
            "sha256": sha,
            "report_path": path,
            "source_url": filing.url,
            "submitted_date": filing.submitted_date,
            "period_end": filing.period_end,
            "disclosure_id": filing.disclosure_id,
        }
