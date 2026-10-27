"""Fundamentales anuales no oficiales (Yahoo Finance) para emisores sin SEC/ESEF.

Solo para tickers de un mapa REVISADO (p.ej. KRKNF -> PNG.V, TSXV, CAD). Reglas
de veracidad: source_type propio (YAHOO_FUNDAMENTALS), etiqueta "fuente no
oficial", nunca sobrescribe SEC/ESEF/CNMV, cada cifra enlaza al documento con
su origen y fecha, y no se inventa ninguna cifra que Yahoo no devuelva.

Complemento, nunca sustituto: si la Company YA tiene hechos oficiales
(SEC/ESEF/CNMV), Yahoo solo escribe los pares (metrica, ejercicio FY) sin
hecho oficial — un emisor con cobertura oficial parcial (p.ej. BN, cuyo 40-F
aporta unos pocos hechos) se completa sin tocar lo oficial. Si no hay nada
que complementar, se rechaza. En lectura, SOURCE_PRIORITY ya da preferencia
al hecho oficial a igual metrica y ejercicio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
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
    "KRKNF": {
        "symbol": "PNG.V",
        "currency": "CAD",
        "names": ["Kraken Robotics"],
        # Cotejo a mano (2026-10-27) contra las notas de resultados del emisor:
        # FY2025 ingresos 102,2 M CAD, beneficio neto 2.860 k, activos 313,7 M,
        # caja 120,5 M; FY2024 91,3 M / 20.089 k / 162,6 M / 58,5 M. Yahoo
        # devuelve exactamente esas cifras.
        "verified_against": [
            "https://www.krakenrobotics.com/news-releases/kraken-robotics-reports-2025-financial-results/",
            "https://www.theglobeandmail.com/investing/markets/stocks/KRKNF/pressreleases/32080072/kraken-robotics-reports-2024-financial-results/",
        ],
    },
    # BN: Brookfield Corporation (40-F con cobertura oficial parcial; reporta
    # en USD: BN y BN.TO declaran los mismos fundamentales en USD).
    "BN": {"symbol": "BN", "currency": "USD", "names": ["Brookfield"]},
    # CGEO.L: Georgia Capital PLC (LSE). Sin SEC y sin XBRL utilizable: el
    # informe anual que deposita en el NSM de la FCA va marcado "Untagged"
    # (xhtml de pdf2htmlEX, 0 hechos iXBRL), filings.xbrl.org no lo indexa y
    # Companies House solo tiene PDF. Reporta en GEL (cotiza en GBp). Es una
    # entidad de inversion (NIIF 10): el patrimonio ES el NAV. Cotejo a mano
    # (2026-10-27) contra el Annual Report 2025 depositado en el NSM: NAV
    # 5.194.527 k GEL, activos 5.198.380, caja 13.495, beneficio 1.892.642,
    # BPA diluido 54,0296, acciones diluidas medias 35.029.723, flujo de
    # explotacion -5.838; FY2024 3.609.013 / 3.611.317 / 3.521 / 362.274.
    # La "Total Revenue" de Yahoo (1.900.030 k en FY2025) NO aparece en el
    # informe: ingresos, margen bruto y resultado de explotacion quedan fuera.
    "CGEO.L": {
        "symbol": "CGEO.L",
        "currency": "GEL",
        "names": ["Georgia Capital"],
        "metrics": (
            "net_income",
            "income_before_tax",
            "eps_diluted",
            "shares_diluted",
            "total_assets",
            "total_liabilities",
            "total_equity",
            "cash_and_equivalents",
            "operating_cash_flow",
            "free_cash_flow",
        ),
        "verified_against": [
            "https://data.fca.org.uk/artefacts/NSM/DirectUpload/NI-000143657/NI-000143657_213800Q65T5GNBOW7H65-2025-12-31.xhtml",
            "https://data.fca.org.uk/artefacts/NSM/Portal/NI-000115718/NI-000115718_213800Q65T5GNBOW7H65-2024-12-31.xhtml",
        ],
    },
}

# metric -> (statement, [filas Yahoo por orden de preferencia], es_por_accion)
YAHOO_METRIC_MAP: list[tuple[str, str, list[str], bool | str]] = [
    ("revenue", "income", ["Total Revenue", "Operating Revenue"], False),
    ("gross_profit", "income", ["Gross Profit"], False),
    ("operating_income", "income", ["Operating Income"], False),
    ("net_income", "income", ["Net Income", "Net Income Common Stockholders"], False),
    ("income_before_tax", "income", ["Pretax Income"], False),
    ("income_tax_expense", "income", ["Tax Provision"], False),
    ("interest_expense", "income", ["Interest Expense"], False),
    ("depreciation_amortization", "cashflow", ["Depreciation And Amortization", "Depreciation Amortization Depletion"], False),
    ("eps_diluted", "income", ["Diluted EPS"], True),
    ("shares_diluted", "income", ["Diluted Average Shares"], "shares"),
    ("total_assets", "balance", ["Total Assets"], False),
    ("total_liabilities", "balance", ["Total Liabilities Net Minority Interest"], False),
    ("total_equity", "balance", ["Stockholders Equity", "Common Stock Equity"], False),
    ("cash_and_equivalents", "balance", ["Cash And Cash Equivalents"], False),
    ("total_debt", "balance", ["Total Debt"], False),
    ("operating_cash_flow", "cashflow", ["Operating Cash Flow"], False),
    ("capital_expenditure", "cashflow", ["Capital Expenditure"], False),
    ("free_cash_flow", "cashflow", ["Free Cash Flow"], False),
]

# Fuentes OFICIALES que Yahoo nunca sustituye (el nombre historico del
# modulo era confuso: son las que bloquean/complementan, no las no oficiales).
OFFICIAL_SOURCE_TYPES = ("SEC", "ESEF", "CNMV")


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


def _metric_rows(entry: dict[str, Any]) -> list[tuple[str, str, list[str], bool | str]]:
    """Filas del mapa que aplican al emisor: una lista blanca revisada
    (``metrics``) deja fuera lo que Yahoo sintetiza y el informe no publica."""
    allowed = entry.get("metrics")
    if not allowed:
        return YAHOO_METRIC_MAP
    return [row for row in YAHOO_METRIC_MAP if row[0] in allowed]


def refresh_from_yahoo(
    db: Session, company: Company, *, fetcher: Any = _fetch_yahoo, commit: bool = True
) -> dict[str, Any]:
    """Ingesta Yahoo del mapa revisado.

    ``commit=False`` solo hace flush: la generacion de tesis corre dentro de
    un SAVEPOINT y un commit intermedio lo romperia."""
    ticker = company.ticker.upper()
    entry = REVIEWED_MAP.get(ticker)
    if entry is None:
        raise RuntimeError(f"Sin mapa Yahoo revisado para {ticker}")

    # Pares (metrica, ejercicio) con hecho OFICIAL anual: Yahoo no los toca.
    official_pairs = {
        (metric, fiscal_year)
        for metric, fiscal_year in db.execute(
        select(FinancialFact.metric, FinancialFact.fiscal_year).where(
            FinancialFact.company_id == company.id,
            FinancialFact.source_type.in_(OFFICIAL_SOURCE_TYPES),
            FinancialFact.fiscal_quarter == "FY",
            *tenant_filters(db, FinancialFact),
        )
        ).all()
    }

    data = fetcher(entry["symbol"])
    yname = data.get("name")
    # Una ficha recien creada lleva el ticker como nombre (ensure_company_stub
    # sin enriquecer): no aporta identidad, asi que manda la prueba contra los
    # nombres REVISADOS del mapa. Un nombre real distinto sigue bloqueando.
    placeholder_name = (company.name or "").strip().upper() in {"", ticker}
    if not (
        (placeholder_name or _name_identity_ok(company.name, yname))
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
    retrieved_at = datetime.now(UTC).isoformat()
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

    # Cobertura de Yahoo por metrica, antes de escribir nada.
    coverage: dict[str, list[str]] = {}
    periods_by_metric: dict[str, dict[str, Decimal]] = {}
    rows = _metric_rows(entry)
    for metric, statement, labels, _per_share in rows:
        by_period = _row_by_period(data.get(statement), labels)
        if by_period:
            coverage[metric] = sorted(by_period, reverse=True)
            periods_by_metric[metric] = by_period

    # Complemento, nunca sustituto: si TODA la cobertura posible ya tiene
    # hecho oficial, no hay nada que aportar desde una fuente no oficial.
    if official_pairs and not any(
        (metric, int(period[:4])) not in official_pairs
        for metric, periods in coverage.items()
        for period in periods
    ):
        raise RuntimeError(
            f"{ticker} ya tiene cobertura oficial SEC/ESEF/CNMV de toda la "
            "cobertura disponible: nada que complementar desde una fuente no oficial"
        )

    imported = 0
    skipped_official = 0
    for metric, statement, labels, per_share in rows:
        by_period = periods_by_metric.get(metric, {})
        for period_date, val in sorted(by_period.items(), reverse=True)[:10]:
            if (metric, int(period_date[:4])) in official_pairs:
                skipped_official += 1
                continue
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=val,
                    unit="shares" if per_share == "shares" else (f"{currency}/share" if per_share else currency),
                    period=f"{period_date}:FY",
                    fiscal_year=int(period_date[:4]),
                    fiscal_quarter="FY",
                    source_id=document.id,
                    source_type=SOURCE_TYPE,
                    is_reported=False,  # Yahoo no es el emisor: no es cifra 'reported'
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
        "last_refreshed_at": retrieved_at,
        "verified_against": list(entry.get("verified_against") or []),
    }
    drop_shadowed_facts(db, company.id, document.id, tenant_condition(db))
    sync_company_fact_chunks(db, company)
    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "status": "ingested",
        "ticker": ticker,
        "provider": "YAHOO_FUNDAMENTALS",
        "official": False,
        "symbol": symbol,
        "currency": currency,
        "source_document_id": document.id,
        "facts_imported": imported,
        "facts_skipped_official": skipped_official,
        "metrics_covered": sorted(coverage),
        "retrieved_at": retrieved_at,
        "source_url": document.source_url,
        "verified_against": list(entry.get("verified_against") or []),
    }
