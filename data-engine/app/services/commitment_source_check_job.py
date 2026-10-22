"""Job offline de comprobacion de fuentes oficiales (NO HTTP sincrono, NO escrituras de tenant).

Recorre los activos EXACTOS registrados (comunicados financieros y transcripciones con fecha de
llamada leida), los descarga con la politica segura existente y registra por activo:
ultimo chequeo, resultado (extraido / abstencion / error), motivo y hashes. No guarda texto
completo ni emite veredictos de cumplimiento ni toca promesas/posiciones de ningun usuario.

Procedencia: todo es "emisor_reportado" (independiente=False). Un comunicado y una transcripcion
del mismo emisor son contraste documental, no verificacion externa. Las medidas ajustadas (moneda
constante) se etiquetan como tales y no se mezclan con las reportadas.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from app.services.commitment_financial_release import (
    FINANCIAL_ASSETS,
    ISSUER_REPORTED,
    extract_gross_bookings,
)
from app.services.commitment_primary_pipeline import (
    PrimarySourceError,
    fetch_registered_document_isolated,
)
from app.services.public_fetch import fetch_public_url
from app.services.transcript_source_registry import all_entries

MAX_RECORDS = 200
HTML_MAX_BYTES = 4_000_000
HTML_TIMEOUT = 25.0


@dataclass(frozen=True)
class SourceCheckRecord:
    ticker: str
    url: str
    kind: str  # press_release | transcript
    period: str
    checked_on: str  # ISO date del chequeo
    outcome: str  # extraido | abstencion | error
    reason: str
    content_sha256: str | None = None  # bytes (transcript) o HTML (comunicado)
    facts: tuple[dict, ...] = ()  # resumen de hechos extraidos (sin texto completo)
    provenance: str = ISSUER_REPORTED
    independent: bool = False
    note: str = field(default="contraste_documental_mismo_emisor_no_verificacion_independiente")


def _fetch_html(url: str) -> bytes:
    content, ctype, final_url = fetch_public_url(
        url, max_bytes=HTML_MAX_BYTES, timeout=HTML_TIMEOUT, allowed_url=lambda u: u == url
    )
    if final_url != url or (ctype or "").split(";")[0].strip().lower() != "text/html":
        raise PrimarySourceError("Respuesta distinta de la registrada (URL o tipo)")
    return content


def check_financial_assets(
    *, today: date, fetch_html: Callable[[str], bytes] = _fetch_html,
) -> list[SourceCheckRecord]:
    out: list[SourceCheckRecord] = []
    for asset in FINANCIAL_ASSETS:
        base = dict(ticker=asset.ticker, url=asset.url, kind=asset.kind, period=asset.period,
                    checked_on=today.isoformat())
        try:
            html = fetch_html(asset.url)
        except Exception as exc:  # error acotado, sin detalle interno
            out.append(SourceCheckRecord(**base, outcome="error", reason=type(exc).__name__))
            continue
        facts, why = extract_gross_bookings(asset=asset, html=html, today=today)
        digest = facts[0].html_sha256 if facts else None
        if not facts:
            out.append(SourceCheckRecord(**base, outcome="abstencion", reason=why))
            continue
        summary = tuple(
            {"metric": f.metric, "value": str(f.value), "unit": f.unit, "reported": f.is_reported,
             "adjusted": f.is_adjusted} for f in facts)
        out.append(SourceCheckRecord(**base, outcome="extraido", reason=why,
                                     content_sha256=digest, facts=summary))
    return out


def check_transcripts(
    *, today: date, fetch=fetch_registered_document_isolated,
) -> list[SourceCheckRecord]:
    out: list[SourceCheckRecord] = []
    for entry in all_entries():
        for asset in entry.assets:
            if not asset.call_date:
                continue
            base = dict(ticker=entry.ticker, url=asset.url, kind="transcript", period=asset.period,
                        checked_on=today.isoformat())
            try:
                doc, meta = fetch(entry.ticker, asset.url, today=today)
            except PrimarySourceError as exc:
                out.append(SourceCheckRecord(**base, outcome="abstencion", reason=str(exc)[:120]))
                continue
            except Exception as exc:
                out.append(SourceCheckRecord(**base, outcome="error", reason=type(exc).__name__))
                continue
            facts = ({"pages": doc.text.count("\f") + 1, "bytes": doc.byte_size,
                      "extractor": doc.extractor, "cache_hit": meta["cache_hit"],
                      "bytes_changed": meta["bytes_changed"]},)
            out.append(SourceCheckRecord(**base, outcome="extraido", reason="texto_obtenido",
                                         content_sha256=doc.bytes_sha256, facts=facts))
    return out


class JsonSourceCheckStore:
    """Ultimo chequeo por URL en un JSON acotado (sin BD ni migracion; fichero explicito)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, records: list[SourceCheckRecord]) -> dict[str, dict]:
        data = self.load()
        for rec in records:
            previous = data.get(rec.url)
            item = asdict(rec)
            item["previous_content_sha256"] = previous.get("content_sha256") if previous else None
            item["content_changed"] = (
                None if not previous or not rec.content_sha256 or not previous.get("content_sha256")
                else previous["content_sha256"] != rec.content_sha256)
            data[rec.url] = item
        while len(data) > MAX_RECORDS:
            data.pop(next(iter(data)))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
        tmp.replace(self.path)
        return data


def run_job(store: JsonSourceCheckStore, *, today: date, **kwargs) -> list[SourceCheckRecord]:
    records = check_financial_assets(today=today, **{k: v for k, v in kwargs.items() if k == "fetch_html"})
    records += check_transcripts(today=today, **{k: v for k, v in kwargs.items() if k == "fetch"})
    store.save(records)
    return records
