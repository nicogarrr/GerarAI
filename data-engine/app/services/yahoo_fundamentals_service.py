"""Fundamentales anuales no oficiales (Yahoo Finance) para emisores sin SEC/ESEF.

Solo para tickers de un mapa REVISADO (p.ej. KRKNF -> PNG.V, TSXV, CAD). Reglas
de veracidad: source_type propio (YAHOO_FUNDAMENTALS), etiqueta "fuente no
oficial", nunca sobrescribe SEC/ESEF (se rechaza si la Company ya tiene hechos
de esas fuentes), cada cifra enlaza al documento con su origen y fecha, y no se
inventa ninguna cifra que Yahoo no devuelva.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Document, FinancialFact
from app.services.fact_chunk_service import sync_company_fact_chunks
from app.services.fact_deletion import (
    delete_financial_facts,
    drop_shadowed_facts,
    tenant_condition,
)
from app.services.financial_ingestion_service import _name_identity_ok

SOURCE_TYPE = "YAHOO_FUNDAMENTALS"

# Mapa revisado a mano: ticker de la Company -> simbolo Yahoo, divisa declarada
# y nombres aceptados para la prueba de identidad.
REVIEWED_MAP: dict[str, dict[str, Any]] = {
    "KRKNF": {"symbol": "PNG.V", "currency": "CAD", "names": ["Kraken Robotics"]},
}

# metric -> (statement, [filas Yahoo por orden de preferencia], es_por_accion)
YAHOO_METRIC_MAP: list[tuple[str, str, list[str], bool]] = [
    ("revenue", "income", ["Total Revenue", "Operating Revenue"], False),
    ("gross_profit", "income", ["Gross Profit"], False),
    ("operating_income", "income", ["Operating Income"], False),
    ("net_income", "income", ["Net Income", "Net Income Common Stockholders"], False),
    ("income_before_tax", "income", ["Pretax Income"], False),
    ("income_tax_expense", "income", ["Tax Provision"], False),
    ("interest_expense", "income", ["Interest Expense"], False),
    ("depreciation_amortization", "cashflow", ["Depreciation And Amortization", "Depreciation Amortization Depletion"], False),
    ("eps_diluted", "income", ["Diluted EPS"], True),
    ("shares_diluted", "income", ["Diluted Average Shares"], False),
    ("total_assets", "balance", ["Total Assets"], False),
    ("total_liabilities", "balance", ["Total Liabilities Net Minority Interest"], False),
    ("total_equity", "balance", ["Stockholders Equity", "Common Stock Equity"], False),
    ("cash_and_equivalents", "balance", ["Cash And Cash Equivalents"], False),
    ("total_debt", "balance", ["Total Debt"], False),
    ("operating_cash_flow", "cashflow", ["Operating Cash Flow"], False),
    ("capital_expenditure", "cashflow", ["Capital Expenditure"], False),
    ("free_cash_flow", "cashflow", ["Free Cash Flow"], False),
]

NON_OFFICIAL_SOURCE_TYPES = ("SEC", "ESEF", "CNMV")


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _row_by_period(frame: Any, labels: list[str]) -> dict[str, Decimal]:
    """Primera fila disponible entre `labels`; periodo -> valor (sin NaN)."""
    if frame is None or getattr(frame, "empty", True):
        return {}
    for label in labels:
        if label in frame.index:
            out: dict[str, Decimal] = {}
            for col, raw in frame.loc[label].items():
                val = _dec(raw)
                if val is None:
                    continue
                out[str(col)[:10]] = val
            if out:
                return out
    return {}


def _fetch_yahoo(symbol: str) -> dict[str, Any]:
    import yfinance as yf  # import perezoso: dependencia ya instalada, red solo aqui

    ticker = yf.Ticker(symbol)
    info = ticker.get_info() or {}
    return {
        "name": info.get("longName") or info.get("shortName"),
        "currency": info.get("financialCurrency") or info.get("currency"),
        "income": ticker.income_stmt,
        "balance": ticker.balance_sheet,
        "cashflow": ticker.cashflow,
    }


def refresh_from_yahoo(
    db: Session, company: Company, *, fetcher: Any = _fetch_yahoo
) -> dict[str, Any]:
    ticker = company.ticker.upper()
    entry = REVIEWED_MAP.get(ticker)
    if entry is None:
        raise RuntimeError(f"Sin mapa Yahoo revisado para {ticker}")

    official = db.scalar(
        select(FinancialFact.id).where(
            FinancialFact.company_id == company.id,
            FinancialFact.source_type.in_(NON_OFFICIAL_SOURCE_TYPES),
        ).limit(1)
    )
    if official is not None:
        raise RuntimeError(
            f"{ticker} ya tiene hechos SEC/ESEF/CNMV: la fuente no oficial no los sustituye"
        )

    data = fetcher(entry["symbol"])
    yname = data.get("name")
    if not (
        _name_identity_ok(company.name, yname)
        and any(_name_identity_ok(n, yname) for n in entry["names"])
    ):
        raise RuntimeError(
            f"company_mismatch: la Company {company.name!r} no acredita identidad con "
            f"{yname!r} ({entry['symbol']})"
        )
    currency = entry["currency"]
    declared = (data.get("currency") or "").upper()
    if declared and declared != currency:
        raise RuntimeError(
            f"currency_mismatch: Yahoo declara {declared}, el mapa revisado dice {currency}"
        )

    symbol = entry["symbol"]
    title = f"Yahoo Finance fundamentals (fuente no oficial) - {symbol}"
    tenant_id = db.info.get("tenant_id")
    document = db.scalar(
        select(Document).where(
            Document.company_id == company.id,
            Document.source_type == SOURCE_TYPE,
            Document.title == title,
        )
    )
    if document is None:
        document = Document(
            company_id=company.id,
            title=title,
            source_type=SOURCE_TYPE,
            source_url=f"https://finance.yahoo.com/quote/{symbol}/financials",
            metadata_={"provider": "Yahoo Finance", "official": False},
        )
        db.add(document)
        db.flush()

    delete_financial_facts(
        db,
        FinancialFact.company_id == company.id,
        FinancialFact.source_id == document.id,
        FinancialFact.tenant_id == tenant_id
        if tenant_id is not None
        else FinancialFact.tenant_id.is_(None),
    )

    imported = 0
    coverage: dict[str, list[str]] = {}
    for metric, statement, labels, per_share in YAHOO_METRIC_MAP:
        by_period = _row_by_period(data.get(statement), labels)
        if by_period:
            coverage[metric] = sorted(by_period, reverse=True)
        for period_date, val in sorted(by_period.items(), reverse=True)[:10]:
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=val,
                    unit=f"{currency}/share" if per_share else currency,
                    period=f"{period_date}:FY",
                    fiscal_year=int(period_date[:4]),
                    fiscal_quarter="FY",
                    source_id=document.id,
                    source_type=SOURCE_TYPE,
                    is_reported=True,
                    confidence=Decimal("0.6"),
                )
            )
            imported += 1

    document.metadata_ = {
        **(document.metadata_ or {}),
        "provider": "Yahoo Finance",
        "official": False,
        "symbol": symbol,
        "currency": currency,
        "yahoo_name": data.get("name"),
        "metrics_covered": sorted(coverage),
        "last_refreshed_at": datetime.now(UTC).isoformat(),
    }
    drop_shadowed_facts(db, company.id, document.id, tenant_condition(db))
    sync_company_fact_chunks(db, company)
    db.commit()
    return {
        "status": "ingested",
        "ticker": ticker,
        "provider": "YAHOO_FUNDAMENTALS",
        "official": False,
        "symbol": symbol,
        "currency": currency,
        "source_document_id": document.id,
        "facts_imported": imported,
        "metrics_covered": sorted(coverage),
    }
