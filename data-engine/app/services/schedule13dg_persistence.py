"""Persistencia durable de filings SC 13D/13G (titulares >5%).

Reglas (las mismas que ``insider_persistence``):
- schedule_13dg_filings: una fila INMUTABLE por (tenant, accession). Las
  enmiendas (…/A) crean su propia fila; nunca sobrescriben la original.
- Re-ingestar el mismo filing no duplica filas.
- Lo no parseado queda NULL y status="unparsed": la UI muestra N/D, nunca
  una cifra inventada.
- Best-effort para el caller: la persistencia nunca rompe un escaneo.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Schedule13DGFiling

PARSER_VERSION = "1.1"  # 1.0: portada XML + SGML; 1.1: CIK emisor/declarante en SGML y enteros no negativos


def persist_filing(
    db: Session,
    filing: dict,
    parsed: dict,
    *,
    raw_text: str | None = None,
    tenant_id: int | None = None,
) -> dict:
    """Inserta el filing de forma idempotente. Devuelve stats."""
    accession = str(filing.get("accession_number") or "")
    form = str(filing.get("form") or parsed.get("form") or "").upper()
    raw_sha = (
        hashlib.sha256(raw_text.encode()).hexdigest() if raw_text is not None else None
    )
    # El tenant puede venir del caller o del scope de la sesion (mismo motivo
    # que insider_persistence: ignorar db.info mezclaba NULL con el tenant del
    # before_flush y el duplicado chocaba con la unique constraint).
    effective_tenant_id = tenant_id if tenant_id is not None else db.info.get("tenant_id")

    record = db.scalar(
        select(Schedule13DGFiling).where(
            Schedule13DGFiling.tenant_id.is_(None)
            if effective_tenant_id is None
            else Schedule13DGFiling.tenant_id == effective_tenant_id,
            Schedule13DGFiling.accession_number == accession,
        )
    )
    if record is not None:
        from app.services.schedule13dg_news import ensure_news
        ensure_news(db, filing, parsed, tenant_id=effective_tenant_id)
        return {"filing_created": False, "filing_id": record.id, "status": record.status}

    parsed_ok = bool(parsed.get("parsed_ok"))
    record = Schedule13DGFiling(
        tenant_id=effective_tenant_id,
        accession_number=accession,
        form=form,
        is_amendment=bool(parsed.get("is_amendment")) or form.endswith("/A"),
        issuer_cik=str(parsed.get("issuer_cik") or filing.get("issuer_cik") or ""),
        issuer_ticker=(str(filing["issuer_ticker"]).upper() if filing.get("issuer_ticker") else None),
        issuer_name=parsed.get("issuer_name"),
        filer_cik=parsed.get("filer_cik"),
        holder_name=parsed.get("holder_name"),
        aggregate_shares=parsed.get("aggregate_shares"),
        percent_of_class=parsed.get("percent_of_class"),
        sole_voting_power=parsed.get("sole_voting_power"),
        shared_voting_power=parsed.get("shared_voting_power"),
        sole_dispositive_power=parsed.get("sole_dispositive_power"),
        shared_dispositive_power=parsed.get("shared_dispositive_power"),
        holders=parsed.get("holders") or [],
        securities_class_title=parsed.get("securities_class_title"),
        snapshot_date=parsed.get("snapshot_date"),
        filing_date=filing.get("filing_date"),
        report_date=filing.get("report_date"),
        signature_date=parsed.get("signature_date"),
        source_url=filing.get("document_url"),
        index_url=filing.get("index_url"),
        raw_sha256=raw_sha,
        parser_version=PARSER_VERSION,
        status="parsed" if parsed_ok else "unparsed",
        error=(parsed.get("error") or None) if not parsed_ok else None,
    )
    # Savepoint por filing: si el flush viola una constraint (p. ej. un
    # duplicado concurrente), solo se deshace ESTE filing y la sesion queda
    # operativa para el resto del escaneo, sin rollback manual del caller.
    with db.begin_nested():
        db.add(record)
        db.flush()
    from app.services.schedule13dg_news import ensure_news
    ensure_news(db, filing, parsed, tenant_id=effective_tenant_id)
    return {"filing_created": True, "filing_id": record.id, "status": record.status}
