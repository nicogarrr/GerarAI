"""Persistencia de las operaciones de directivos CNMV (NOD) en tablas insider.

Una cabecera NOD = una fila insider_filings (form="PDMR-ES") + una fila
insider_transactions. Solo se guardan notificaciones de emisores conocidos por
NIF (cnmv_mapping.issuer_for_nif, tabla revisada): el resto del registro no
nos pertenece. Idempotente por fingerprint (sha256 del número de registro):
re-ingestar no duplica jamas.

La cabecera del registro NO incluye sentido, importe ni moneda (eso solo está
dentro del documento, fase 2). Por tanto code/shares/price/value persisten
como None (N/D) y NUNCA se inventan ni se asume EUR.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, InsiderFiling, InsiderTransaction
from app.services import cnmv_mapping
from app.services.connectors.cnmv_nod import (
    DELAY_POLICY,
    FORM,
    LICENCE,
    PARSER_VERSION,
    SOURCE,
    CNMVNODEntry,
    fetch_entries,
)


def fingerprint(registry_number: str) -> str:
    return hashlib.sha256(f"cnmv-nod:{registry_number}".encode()).hexdigest()[:64]


def _companies_by_isin_and_ticker(db: Session) -> tuple[dict[str, Company], dict[str, Company]]:
    """Universo global de companies (no es tenant-owned) por ISIN y ticker."""
    # .all(): db.scalars devuelve un iterador de UN SOLO USO; materializar
    # antes de recorrerlo dos veces (con el iterador, el segundo dict quedaba
    # siempre vacio y el fallback por ticker no encontraba nunca).
    rows = db.scalars(select(Company)).all()
    by_isin = {company.isin.upper(): company for company in rows if company.isin}
    by_ticker = {company.ticker.upper(): company for company in rows if company.ticker}
    return by_isin, by_ticker


def ingest_cnmv_nod(
    db: Session,
    tenant: int,
    start,
    end,
    *,
    entries: list[CNMVNODEntry] | None = None,
) -> dict[str, int]:
    """Una pasada: descarga cabeceras NOD y guarda lo nuevo de emisores conocidos.

    Si el listado remoto excede el tope de páginas, el resultado llega con
    ``truncated=True``: lo descargado se ingesta igualmente, pero el truncado
    queda señalado en las métricas (nunca se presenta a medias como completo).
    """
    truncated = False
    if entries is None:
        fetched = fetch_entries(start, end)
        entries = fetched.entries
        truncated = fetched.truncated
    by_isin, by_ticker = _companies_by_isin_and_ticker(db)
    known = set(
        db.scalars(select(InsiderTransaction.fingerprint).where(InsiderTransaction.tenant_id == tenant))
    )
    result: dict[str, int] = {
        "received": len(entries),
        "skipped_known": 0,
        "skipped_unknown_nif": 0,
        "skipped_unknown_company": 0,
        "saved": 0,
        "truncated": 1 if truncated else 0,
    }
    for entry in entries:
        fp = fingerprint(entry.registry_number)
        if fp in known:
            result["skipped_known"] += 1
            continue
        issuer = cnmv_mapping.issuer_for_nif(entry.nif) if entry.nif else None
        if issuer is None:
            result["skipped_unknown_nif"] += 1
            continue
        company = by_isin.get(issuer.isin.upper()) or by_ticker.get(issuer.ticker.upper())
        if company is None:
            result["skipped_unknown_company"] += 1
            continue
        filing = InsiderFiling(
            accession_number=f"cnmv-nod-{entry.registry_number}",
            form=FORM,
            issuer_cik=(entry.nif or "")[:20],
            issuer_ticker=company.ticker,
            issuer_name=entry.issuer_name or issuer.legal_name,
            filing_date=entry.filing_date.isoformat(),
            report_date=None,  # la fecha de operación solo está en el documento (fase 2)
            source_url=entry.document_url,
            parser_version=PARSER_VERSION,
            status="parsed",
        )
        db.add(filing)
        db.flush()
        db.add(
            InsiderTransaction(
                fingerprint=fp,
                filing_id=filing.id,
                accession_number=filing.accession_number,
                form=FORM,
                issuer_ticker=company.ticker,
                insider=entry.declarant,
                role=None,
                officer_title=entry.motive,
                code=None,  # sentido (compra/venta) solo en el documento: nunca adivinado
                shares=None,
                price=None,
                value=None,
                tx_date=None,
                source_url=entry.document_url,
                data_quality={
                    "source": SOURCE,
                    "licence": LICENCE,
                    "delay": DELAY_POLICY,
                    "registry_number": entry.registry_number,
                    "nif": entry.nif,
                    "header_only": True,
                    "currency": None,  # la cabecera no declara moneda: nunca se asume EUR
                    "value_unknown": True,
                },
            )
        )
        known.add(fp)
        result["saved"] += 1
    db.commit()
    return result
