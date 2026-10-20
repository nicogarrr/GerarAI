"""Persistencia de insiders de Canada (Yahoo, fuente NO OFICIAL) en insider_*.

Una pasada por ticker: quoteSummary insiderTransactions -> 1 filing + 1 tx por
movimiento nuevo (fingerprint de contenido; Yahoo no da id). Solo tickers con
Company en base. Idempotente: re-ingestar no duplica.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, InsiderFiling, InsiderTransaction
from app.services.connectors.ca_insider_yahoo import (
    CA_TICKERS,
    FORM,
    PARSER_VERSION,
    PAUSE_SECONDS,
    SEDI_URL,
    SOURCE_NAME,
    fetch_insider_transactions,
    map_transaction,
    yahoo_session,
)


async def ingest_ca_insiders(
    db: Session, tenant: int, *, client: Any = None, crumb: str | None = None
) -> dict[str, Any]:
    """Una pasada por los tickers canadienses curados. Fallos por ticker = ausencia con causa."""
    owned, crumb = yahoo_session(client) if crumb is None else (client, crumb)
    tickers = {
        row.ticker.upper(): row
        for row in db.scalars(select(Company).where(Company.ticker.in_(list(CA_TICKERS))))
    }
    known = set(db.scalars(
        select(InsiderTransaction.fingerprint).where(InsiderTransaction.tenant_id == tenant)
    ))
    result: dict[str, Any] = {"saved": 0, "skipped_known": 0, "skipped_incomplete": 0,
                              "tickers": {}, "missing_companies": sorted(set(CA_TICKERS) - set(tickers))}
    for ticker, symbol in CA_TICKERS.items():
        company = tickers.get(ticker)
        if company is None:
            continue
        try:
            raw_txs = fetch_insider_transactions(symbol, owned, crumb)
        except Exception as exc:  # noqa: BLE001 - un ticker caido no frena al resto
            result["tickers"][ticker] = {"error": type(exc).__name__}
            continue
        saved = 0
        for raw in raw_txs:
            mapped = map_transaction(ticker, raw) if isinstance(raw, dict) else None
            if mapped is None:
                result["skipped_incomplete"] += 1
                continue
            if mapped["fingerprint"] in known:
                result["skipped_known"] += 1
                continue
            filing = InsiderFiling(
                accession_number=mapped["fingerprint"],
                form=FORM,
                issuer_cik=ticker,  # no es emisor SEC: se guarda el ticker, nunca un CIK inventado
                issuer_ticker=ticker,
                issuer_name=company.name,
                filing_date=mapped["tx_date"],
                report_date=mapped["tx_date"],
                source_url=mapped["source_url"],
                parser_version=PARSER_VERSION,
                status="parsed",
            )
            db.add(filing)
            db.flush()
            db.add(InsiderTransaction(
                fingerprint=mapped["fingerprint"],
                filing_id=filing.id,
                accession_number=mapped["fingerprint"],
                form=FORM,
                issuer_ticker=ticker,
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
                    "unofficial": True,
                    "official_source": SEDI_URL,
                    "currency": mapped["currency"],
                    "transaction_nature": mapped["transaction_nature"],
                    "ownership": mapped["ownership"],
                },
            ))
            known.add(mapped["fingerprint"])
            saved += 1
        result["saved"] += saved
        result["tickers"][ticker] = {"received": len(raw_txs), "saved": saved}
        await asyncio.sleep(PAUSE_SECONDS)
    db.commit()
    return result
