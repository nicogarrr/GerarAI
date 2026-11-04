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
        # Divisa de los ESTADOS (no la de cotizacion): el modo completo sin
        # mapa revisado solo acepta esta.
        "financial_currency": info.get("financialCurrency"),
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


# Modo HUECOS (owner 3-nov-2026: «a ver como conseguimos esos datos»): para
# CUALQUIER emisor con listado Yahoo seguro, solo las piezas del puente de
# valoracion que faltan (deuda, deuda neta, caja, acciones) y solo en los
# pares (metrica, ejercicio) sin hecho oficial. Comprobado en prod el 3-nov:
# AENA/EBRO/SAN/VIS (ESEF sin deuda mapeada) y PLTR/HIMS (SEC sin tag de
# deuda reciente; HIMS tiene 1.120 M en convertibles, asi que «sin tag» NO
# era deuda cero). Cada cifra queda como fuente NO oficial y de UNA sola
# fuente salvo que el oficial la confirme; nunca sustituye a SEC/ESEF/CNMV.
GAP_METRICS: tuple[str, ...] = ("total_debt", "net_debt", "cash_and_equivalents", "shares_diluted")
GAP_EXTRA_ROWS: list[tuple[str, str, list[str], bool | str]] = [
    ("net_debt", "balance", ["Net Debt"], False),
]
GAP_TITLE_PREFIX = "Yahoo Finance huecos del puente (fuente no oficial)"
SINGLE_SOURCE_NOTE = "una sola fuente, no oficial (Yahoo Finance)"


def gap_entry(db: Session, company: Company) -> dict[str, Any] | None:
    """Entrada sintetica del modo huecos, o None si no hay listado seguro.

    El simbolo es el MISMO que usan los precios (``yahoo_symbol``: bolsa
    mapeada -> sufijo, ISIN revisado -> su listado; sin simbolo seguro no hay
    entrada). La identidad se prueba despues contra el nombre real de la
    Company (una ficha con el ticker como nombre no acredita nada) y la
    divisa contra la de los hechos oficiales ya guardados o la del maestro.
    """
    from app.services.propicks_price_service import yahoo_symbol

    symbol = yahoo_symbol(company)
    if not symbol:
        return None
    official_units = {
        (unit or "").split("/")[0].upper()
        for (unit,) in db.execute(
            select(FinancialFact.unit).where(
                FinancialFact.company_id == company.id,
                FinancialFact.source_type.in_(OFFICIAL_SOURCE_TYPES),
                FinancialFact.metric.in_(("revenue", "cash_and_equivalents", "total_assets")),
                *tenant_filters(db, FinancialFact),
            ).distinct()
        ).all()
        if unit
    }
    currencies = {u for u in official_units if len(u) == 3 and u.isalpha()}
    if len(currencies) > 1:
        return None  # hechos oficiales en varias divisas: no se mezcla una tercera fuente
    currency = next(iter(currencies)) if currencies else (company.currency or "").upper() or None
    return {
        "symbol": symbol,
        "currency": currency,
        "names": [company.name],
        "metrics": GAP_METRICS,
        "gap_only": True,
    }


def refresh_gaps_from_yahoo(
    db: Session, company: Company, *, fetcher: Any = _fetch_yahoo, commit: bool = True
) -> dict[str, Any]:
    """Modo huecos para cualquier emisor (ver GAP_METRICS)."""
    entry = gap_entry(db, company)
    if entry is None:
        raise RuntimeError(f"Sin listado Yahoo seguro para {company.ticker}")
    return _refresh(db, company, entry, fetcher=fetcher, commit=commit)


# Modo COMPLETO sin mapa revisado (nov 2026, BFIT.AS): para un emisor sin
# SEC ni ESEF (Alemania, Suiza, Canada, Asia, un ESEF que no esta en el
# indice...), los estados anuales enteros de Yahoo como UNICA fuente, con las
# MISMAS guardas que el modo huecos: nombre real que acredite identidad, divisa
# declarada por Yahoo, documento propio y metadata single_source. Nunca toca
# un par (metrica, ejercicio) con hecho oficial.
FULL_TITLE_PREFIX = "Yahoo Finance estados completos (una sola fuente, no oficial)"


def full_entry(db: Session, company: Company) -> dict[str, Any] | None:
    """Entrada sintetica del modo completo, o None si no hay listado Yahoo seguro."""
    entry = gap_entry(db, company)
    if entry is None:
        return None
    names = [company.name]
    from app.services.listing_identity import reviewed_listing_for_ticker

    listing = reviewed_listing_for_ticker(company.ticker)
    if listing is not None and listing.yahoo == entry["symbol"]:
        names.append(listing.name)
    return {
        **entry,
        "names": names,
        "metrics": None,
        "gap_only": False,
        "single_source": True,
        # Sin hechos oficiales la divisa de los estados es la que DECLARA
        # Yahoo (financialCurrency: CGEO.L cotiza en GBp y presenta en GEL);
        # con hechos oficiales manda la de esos hechos y debe coincidir.
        "currency_from_declared": entry["currency"] is None or not _has_official_facts(db, company),
        "title": f"{FULL_TITLE_PREFIX} - {entry['symbol']}",
    }


def _has_official_facts(db: Session, company: Company) -> bool:
    return db.scalar(
        select(FinancialFact.id).where(
            FinancialFact.company_id == company.id,
            FinancialFact.source_type.in_(OFFICIAL_SOURCE_TYPES),
            *tenant_filters(db, FinancialFact),
        ).limit(1)
    ) is not None


def refresh_full_from_yahoo(
    db: Session, company: Company, *, fetcher: Any = None, commit: bool = True
) -> dict[str, Any]:
    """Estados anuales completos de Yahoo para cualquier emisor sin mapa revisado.

    Cada hecho queda como fuente NO oficial y de una sola fuente
    (``SINGLE_SOURCE_NOTE``); los del mapa revisado siguen por
    ``refresh_from_yahoo``."""
    if fetcher is None:
        fetcher = _fetch_yahoo
    if company.ticker.upper() in REVIEWED_MAP:
        return refresh_from_yahoo(db, company, fetcher=fetcher, commit=commit)
    entry = full_entry(db, company)
    if entry is None:
        raise RuntimeError(f"Sin listado Yahoo seguro para {company.ticker}")
    return _refresh(db, company, entry, fetcher=fetcher, commit=commit)


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
    return _refresh(db, company, entry, fetcher=fetcher, commit=commit)


def _refresh(
    db: Session, company: Company, entry: dict[str, Any], *, fetcher: Any, commit: bool
) -> dict[str, Any]:
    ticker = company.ticker.upper()
    gap_only = bool(entry.get("gap_only"))
    # Guardas estrictas (nombre real, divisa declarada, metadata de una sola
    # fuente): modo huecos y modo completo sin mapa revisado.
    strict = gap_only or bool(entry.get("single_source"))

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
    if strict and placeholder_name:
        raise RuntimeError(
            f"company_mismatch: la Company {ticker} no tiene nombre real con el que "
            "acreditar identidad frente a Yahoo"
        )
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
    if entry.get("currency_from_declared"):
        currency = (data.get("financial_currency") or "").upper() or None
    if strict and not (declared and currency):
        raise RuntimeError("currency_unknown: sin divisa declarada con la que comparar")
    if declared and declared != currency:
        raise RuntimeError(
            f"currency_mismatch: Yahoo declara {declared}, el mapa revisado dice {currency}"
        )

    symbol = entry["symbol"]
    retrieved_at = datetime.now(UTC).isoformat()
    title = entry.get("title") or (
        f"{GAP_TITLE_PREFIX} - {symbol}"
        if gap_only
        else f"Yahoo Finance fundamentals (fuente no oficial) - {symbol}"
    )
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
    if gap_only:
        rows = [*rows, *GAP_EXTRA_ROWS]
    for metric, statement, labels, _per_share in rows:
        by_period = _row_by_period(data.get(statement), labels)
        if by_period:
            coverage[metric] = sorted(by_period, reverse=True)
            periods_by_metric[metric] = by_period

    if gap_only:
        # Deuda neta sin fila «Net Debt» (Yahoo la omite con caja neta, p. ej.
        # PLTR): deuda total menos caja del MISMO balance de Yahoo.
        debt_rows = periods_by_metric.get("total_debt", {})
        cash_rows = periods_by_metric.get("cash_and_equivalents", {})
        net_rows = dict(periods_by_metric.get("net_debt", {}))
        for period_date, debt_value in debt_rows.items():
            if period_date not in net_rows and period_date in cash_rows:
                net_rows[period_date] = debt_value - cash_rows[period_date]
        if net_rows:
            periods_by_metric["net_debt"] = net_rows
            coverage["net_debt"] = sorted(net_rows, reverse=True)
        # Un ejercicio con deuda OFICIAL (total o neta) ya tiene puente: la
        # deuda neta de Yahoo lo taparia en el snapshot (prefiere net_debt).
        official_pairs = official_pairs | {
            ("net_debt", fiscal_year)
            for metric, fiscal_year in official_pairs
            if metric == "total_debt"
        }

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
    if gap_only and "net_debt" in periods_by_metric and not any(r[0] == "net_debt" for r in rows):
        rows = [*rows, *GAP_EXTRA_ROWS]
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
        **({"gap_only": True, "single_source": True, "note": SINGLE_SOURCE_NOTE} if gap_only else {}),
        **(
            {"mode": "full_unreviewed", "single_source": True, "note": SINGLE_SOURCE_NOTE}
            if strict and not gap_only
            else {}
        ),
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
        **({"single_source": True, "note": SINGLE_SOURCE_NOTE} if strict else {}),
    }
