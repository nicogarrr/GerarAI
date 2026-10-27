"""Persistencia durable de filings Form 4/4-A y sus transacciones.

Reglas:
- insider_filings: una fila INMUTABLE por accession (tenant, accession).
  Las enmiendas (4/A) crean su propia fila; nunca sobrescriben la original.
- insider_transactions: fingerprint estable (accession + ordinal de fila +
  campos crudos). Re-ingestar el mismo filing no duplica filas.
- Todo es best-effort para el caller: la persistencia nunca rompe la
  lectura de señales (el endpoint devuelve resultados aunque falle).
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import InsiderFiling, InsiderTransaction

PARSER_VERSION = "1.2"  # 1.2: rule_10b5_1 (planes 10b5-1 via notas al pie/checkbox)


def transaction_fingerprint(accession: str, row_index: int, tx: dict) -> str:
    """Fingerprint estable de una fila de transaccion SEC."""
    parts = [
        accession,
        str(row_index),
        str(tx.get("type") or ""),
        str(tx.get("acquired_disposed") or ""),
        str(tx.get("shares") or ""),
        str(tx.get("price") or ""),
        str(tx.get("date") or ""),
        str(tx.get("insider_cik") or ""),
        str(tx.get("is_derivative") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _data_quality(tx: dict) -> dict:
    flags = []
    if tx.get("is_derivative"):
        flags.append("derivative_value_not_cash")
    if tx.get("price") in (None, 0):
        flags.append("missing_or_zero_price")
    if tx.get("multi_reporter"):
        flags.append("joint_filing_attribution")
    quality: dict = {"flags": flags}
    title = str(tx.get("security_title") or "").strip()
    if title:
        quality["security_title"] = title[:120]
    return quality


def persist_filing(
    db: Session,
    filing: dict,
    parsed: dict,
    *,
    xml_text: str | None = None,
    tenant_id: int | None = None,
) -> dict:
    """Inserta filing + transacciones de forma idempotente. Devuelve stats."""
    accession = str(filing.get("accession_number") or "")
    form = str(filing.get("form") or "4").upper()
    raw_sha = (
        hashlib.sha256(xml_text.encode()).hexdigest() if xml_text is not None else None
    )
    # El tenant puede venir del caller o del scope de la sesion. Si se ignora
    # db.info, el SELECT busca tenant_id IS NULL mientras el INSERT recibe el
    # tenant del before_flush: el filing existente no se encuentra y el
    # duplicado choca contra uq_insider_filings_tenant_accession (IntegrityError).
    effective_tenant_id = tenant_id if tenant_id is not None else db.info.get("tenant_id")

    record = db.scalar(
        select(InsiderFiling).where(
            InsiderFiling.tenant_id.is_(None)
            if effective_tenant_id is None
            else InsiderFiling.tenant_id == effective_tenant_id,
            InsiderFiling.accession_number == accession,
        )
    )
    created_filing = False
    if record is None:
        record = InsiderFiling(
            tenant_id=effective_tenant_id,
            accession_number=accession,
            form=form,
            is_amendment=form.endswith("/A"),
            issuer_cik=str(parsed.get("issuer_cik") or ""),
            issuer_ticker=parsed.get("ticker"),
            issuer_name=parsed.get("issuer_name"),
            filing_date=filing.get("filing_date"),
            report_date=filing.get("report_date"),
            period_of_report=parsed.get("period_of_report"),
            source_url=filing.get("document_url"),
            index_url=filing.get("index_url"),
            raw_sha256=raw_sha,
            parser_version=PARSER_VERSION,
            status="parsed",
        )
        db.add(record)
        db.flush()
        created_filing = True

    existing = {
        row.fingerprint
        for row in db.scalars(
            select(InsiderTransaction).where(
                InsiderTransaction.filing_id == record.id
            )
        )
    }
    created_tx = 0
    transactions = parsed.get("transactions", [])
    for row_index, tx in enumerate(transactions):
        fp = transaction_fingerprint(accession, row_index, tx)
        if fp in existing:
            continue
        db.add(
            InsiderTransaction(
                tenant_id=effective_tenant_id,
                fingerprint=fp,
                filing_id=record.id,
                accession_number=accession,
                form=form,
                issuer_ticker=tx.get("ticker"),
                insider=tx.get("insider"),
                insider_cik=tx.get("insider_cik"),
                role=tx.get("role"),
                officer_title=tx.get("officer_title"),
                multi_reporter=bool(tx.get("multi_reporter")),
                attribution=tx.get("attribution"),
                code=tx.get("type"),
                acquired_disposed=tx.get("acquired_disposed"),
                shares=tx.get("shares"),
                price=tx.get("price"),
                value=tx.get("value"),
                tx_date=tx.get("date"),
                is_derivative=bool(tx.get("is_derivative")),
                rule_10b5_1=bool(tx.get("rule_10b5_1")),
                source_url=tx.get("source_url") or filing.get("document_url"),
                data_quality=_data_quality(tx),
            )
        )
        created_tx += 1
    db.commit()
    return {
        "accession_number": accession,
        "filing_created": created_filing,
        "transactions_created": created_tx,
        "transactions_seen": len(transactions),
    }
