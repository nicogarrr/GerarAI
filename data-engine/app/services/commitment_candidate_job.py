"""Job: candidatos de compromisos desde transcripciones oficiales REGISTRADAS (cartera + watchlist).

Solo crea CANDIDATOS sin revisar (status="candidate"). No aprueba criterios, no emite veredictos, no
toca lo que una persona ya reviso. Idempotente: un activo (empresa, URL) ya extraido se salta.
Cada empresa del universo recibe un resultado explicito; nada se omite en silencio.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ManagementPromise
from app.services.commitment_coverage import dynamic_universe
from app.services.company_resolver import resolve_company
from app.services.management_credibility_service import ManagementCredibilityService
from app.services.transcript_source_registry import OFFICIAL_TRANSCRIPT_PDF, get_entry

MAX_NEW_ASSETS_PER_RUN = 12


def _already_extracted(db: Session, company_id: int, url: str) -> bool:
    rows = db.scalars(select(ManagementPromise).where(
        ManagementPromise.company_id == company_id, ManagementPromise.source_url == url))
    return any((r.metadata_ or {}).get("source") == "extraction_candidate" for r in rows)


def extract_registry_candidates(
    db: Session,
    *,
    today: date,
    fetch: Callable | None = None,
    max_new_assets: int = MAX_NEW_ASSETS_PER_RUN,
) -> dict:
    """Devuelve {ticker: [{url, outcome, created}]} con resultado explicito por empresa/activo."""
    if fetch is None:
        from app.services.commitment_primary_pipeline import fetch_registered_document_isolated as fetch
    universe, _flags = dynamic_universe(db)
    results: dict[str, list[dict]] = {}
    budget = max_new_assets
    svc = ManagementCredibilityService()
    for ticker in universe:
        entry = get_entry(ticker)
        if entry is None or entry.status != OFFICIAL_TRANSCRIPT_PDF:
            results[ticker] = [{"outcome": "sin_transcripcion_registrada", "created": 0}]
            continue
        company = resolve_company(db, ticker)
        if company is None:
            results[ticker] = [{"outcome": "empresa_no_resuelta", "created": 0}]
            continue
        rows: list[dict] = []
        for asset in entry.assets:
            item = {"url": asset.url, "created": 0}
            if asset.kind != "transcript" or not asset.call_date:
                item["outcome"] = "activo_no_apto"
            elif _already_extracted(db, company.id, asset.url):
                item["outcome"] = "ya_extraido"
            elif budget <= 0:
                item["outcome"] = "pendiente_por_limite_de_ejecucion"
            else:
                budget -= 1
                try:
                    doc, _meta = fetch(ticker, asset.url, today=today)
                    new = svc.register_extracted_candidates(
                        db, company, transcript_text=doc.text, call_date=doc.asset.published_on,
                        source_url=doc.url, source_check="registro_oficial_exacto",
                        date_basis="call_date",
                    )
                    item["created"] = len(new)
                    item["outcome"] = "candidatos_creados" if new else "sin_candidatos_detectados"
                except ValueError as exc:  # fuente rechazada/limite: visible, no se traga
                    db.rollback()
                    item["outcome"] = "fallo_fuente_o_limite"
                    item["detail"] = str(exc)[:160]
            rows.append(item)
        results[ticker] = rows
    return results
