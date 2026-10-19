"""Persistencia de movimientos PDMR (UK) en las tablas insider existentes.

Un filingId de tracefour = una fila insider_filings (form="PDMR") + una fila
insider_transactions. Solo se guardan movimientos de empresas conocidas por
ISIN (companies.isin): el resto del feed no nos pertenece. Idempotente por
fingerprint (sha256 del filingId): re-ingestar no duplica jamas.

La divisa viaja en data_quality["currency"] y NUNCA se asume: sin divisa, el
precio se guarda pero la UI lo declara N/D de divisa.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, InsiderFiling, InsiderTransaction
from app.services.connectors.uk_pdmr_tracefour import (
    FORM,
    LICENCE,
    PARSER_VERSION,
    SOURCE_NAME,
    fetch_pdmr_feed,
    fingerprint,
    map_entry,
)


def _companies_by_isin(db: Session) -> dict[str, Company]:
    """Universo global de companies (no es tenant-owned) indexado por ISIN."""
    rows = db.scalars(select(Company).where(Company.isin.is_not(None)))
    return {company.isin.upper(): company for company in rows if company.isin}


def _publication_date(value: Any) -> str | None:
    """'2026-10-19T15:53:00Z' -> '2026-10-19' (los campos fecha del modelo son texto)."""
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


async def ingest_uk_pdmr(db: Session, tenant: int, *, client: Any = None) -> dict[str, int]:
    """Una pasada: 1 GET, guarda solo lo nuevo de empresas conocidas."""
    entries = await fetch_pdmr_feed(client=client)
    by_isin = _companies_by_isin(db)
    known = set(
        db.scalars(select(InsiderTransaction.fingerprint).where(InsiderTransaction.tenant_id == tenant))
    )
    result = {
        "received": len(entries),
        "skipped_known": 0,
        "skipped_unknown_isin": 0,
        "skipped_incomplete": 0,
        "saved": 0,
    }
    for raw in entries:
        if not isinstance(raw, dict):
            result["skipped_incomplete"] += 1
            continue
        mapped = map_entry(raw)
        if mapped is None:
            result["skipped_incomplete"] += 1
            continue
        fp = fingerprint(mapped["filing_id"])
        if fp in known:
            result["skipped_known"] += 1
            continue
        company = by_isin.get(mapped["isin"])
        if company is None:
            result["skipped_unknown_isin"] += 1
            continue
        filing = InsiderFiling(
            accession_number=mapped["accession_number"],
            form=FORM,
            issuer_cik=mapped["isin"],
            issuer_ticker=company.ticker,
            issuer_name=mapped["issuer_name"],
            filing_date=_publication_date(mapped["publication_at"]),
            report_date=mapped["tx_date"],
            source_url=mapped["source_url"],
            parser_version=PARSER_VERSION,
            status="parsed",
        )
        db.add(filing)
        db.flush()
        db.add(
            InsiderTransaction(
                fingerprint=fp,
                filing_id=filing.id,
                accession_number=mapped["accession_number"],
                form=FORM,
                issuer_ticker=company.ticker,
                insider=mapped["insider"],
                role=mapped["role"],
                officer_title=mapped["officer_title"],
                code=mapped["code"],
                shares=mapped["shares"],
                price=mapped["price"],
                value=mapped["value"],
                tx_date=mapped["tx_date"],
                source_url=mapped["source_url"],
                data_quality={
                    "source": SOURCE_NAME,
                    "licence": LICENCE,
                    "currency": mapped["currency"],
                    "transaction_nature": mapped["transaction_nature"],
                    "value_unknown": mapped["value_unknown"],
                    **({"price_from_pence": True} if mapped["price_from_pence"] else {}),
                **({"value_raw_gbx_unverified": mapped["value_raw"]}
                   if mapped["value_raw"] is not None else {}),
                },
            )
        )
        known.add(fp)
        result["saved"] += 1
    db.commit()
    return result
