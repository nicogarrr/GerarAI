"""Persistencia durable de avisos SEC Form 144 (venta PROPUESTA, Rule 144).

Reglas (las mismas que ``insider_persistence`` y ``schedule13dg_persistence``):
- form144_notices: una fila INMUTABLE por (tenant, accession). Las enmiendas
  (144/A) crean su propia fila; nunca sobrescriben el aviso que corrigen.
- Re-ingestar el mismo filing no duplica filas.
- Lo no parseado queda NULL y status="unparsed": la UI muestra N/D, nunca
  una cifra inventada.
- Un Form 144 es un aviso de venta propuesta: jamas se escribe en
  insider_filings / insider_transactions (esas tablas son operaciones).
- Best-effort para el caller: la persistencia nunca rompe un escaneo.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Form144Notice
from app.services.connectors.form144 import proposed_sale_totals

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"  # 1.0: esquema edgarSubmission (e-144, EDGAR 2023+)


def _ensure_news_best_effort(db: Session, filing: dict, news_payload: dict, *, tenant_id: int | None, accession: str) -> None:
    """Deriva la noticia sin romper la persistencia del aviso.

    Un fallo se registra (accession y clase del error) en vez de tragarse en
    silencio: asi un CIK no numerico u otra rotura de ``ensure_news`` deja rastro
    en logs y el aviso persistido sigue en pie. SIN exc_info: el traceback
    renderizado lleva el mensaje de la excepcion (que puede citar datos del
    filing) y el redactor de logs solo enmascara secretos conocidos.
    """
    from app.services.form144_news import ensure_news

    try:
        ensure_news(db, filing, news_payload, tenant_id=tenant_id)
    except Exception as exc:  # noqa: BLE001 - best-effort: la noticia no puede deshacer el aviso
        logger.warning(
            "form144: no se pudo derivar la noticia accession=%s error=%s",
            accession, type(exc).__name__,
        )


def persist_filing(
    db: Session,
    filing: dict,
    parsed: dict,
    *,
    raw_text: str | None = None,
    tenant_id: int | None = None,
) -> dict:
    """Inserta el aviso de forma idempotente. Devuelve stats."""
    accession = str(filing.get("accession_number") or "")
    form = str(filing.get("form") or parsed.get("submission_type") or "").upper()
    raw_sha = (
        hashlib.sha256(raw_text.encode()).hexdigest() if raw_text is not None else None
    )
    totals = proposed_sale_totals(parsed)
    # El evento de noticias resume con los mismos totales persistidos.
    news_payload = {**parsed, "totals": totals}
    # El tenant puede venir del caller o del scope de la sesion (mismo motivo
    # que insider_persistence: ignorar db.info mezclaba NULL con el tenant del
    # before_flush y el duplicado chocaba con la unique constraint).
    effective_tenant_id = tenant_id if tenant_id is not None else db.info.get("tenant_id")

    record = db.scalar(
        select(Form144Notice).where(
            Form144Notice.tenant_id.is_(None)
            if effective_tenant_id is None
            else Form144Notice.tenant_id == effective_tenant_id,
            Form144Notice.accession_number == accession,
        )
    )
    if record is not None:
        # Best-effort: el aviso ya existe; un fallo al derivar la noticia no
        # debe marcar el filing como no visto en el monitor.
        _ensure_news_best_effort(db, filing, news_payload, tenant_id=effective_tenant_id, accession=accession)
        return {"filing_created": False, "filing_id": record.id, "status": record.status}

    parsed_ok = bool(parsed.get("parsed_ok"))
    record = Form144Notice(
        tenant_id=effective_tenant_id,
        accession_number=accession,
        form=form,
        is_amendment=form.endswith("/A"),
        issuer_cik=str(parsed.get("issuer_cik") or filing.get("issuer_cik") or ""),
        issuer_ticker=(str(filing["issuer_ticker"]).upper() if filing.get("issuer_ticker") else None),
        issuer_name=parsed.get("issuer_name"),
        seller_cik=parsed.get("seller_cik"),
        seller_name=parsed.get("seller_name"),
        relationships=parsed.get("relationships") or [],
        broker_name=totals.get("broker_name"),
        securities_class_title=totals.get("securities_class_title"),
        shares_to_sell=totals.get("shares_to_sell"),
        aggregate_market_value=totals.get("aggregate_market_value"),
        shares_outstanding=totals.get("shares_outstanding"),
        approx_sale_date=totals.get("approx_sale_date"),
        exchange=totals.get("exchange"),
        securities=parsed.get("securities") or [],
        acquisitions=parsed.get("acquisitions") or [],
        sales_past_3m=parsed.get("sales_past_3m") or [],
        nothing_to_report_past_3m=parsed.get("nothing_to_report_past_3m"),
        notice_date=parsed.get("notice_date"),
        plan_adoption_dates=parsed.get("plan_adoption_dates") or [],
        remarks=parsed.get("remarks"),
        filing_date=filing.get("filing_date"),
        source_url=filing.get("document_url"),
        index_url=filing.get("index_url"),
        raw_sha256=raw_sha,
        parser_version=PARSER_VERSION,
        status="parsed" if parsed_ok else "unparsed",
        error=(parsed.get("error") or None) if not parsed_ok else None,
    )
    # Savepoint por filing: si el flush viola una constraint (p. ej. un
    # duplicado concurrente), solo se deshace ESTE aviso y la sesion queda
    # operativa para el resto del escaneo, sin rollback manual del caller.
    with db.begin_nested():
        db.add(record)
        db.flush()
    # Best-effort: el savepoint del aviso ya cerro con exito. Si la noticia
    # derivada falla (p. ej. CIK no numerico), no se propaga: revertir aqui
    # borraria el Form144Notice ya persistido y el monitor volveria a intentar
    # el mismo filing por no haber registrado su accession.
    _ensure_news_best_effort(db, filing, news_payload, tenant_id=effective_tenant_id, accession=accession)
    return {"filing_created": True, "filing_id": record.id, "status": record.status}
