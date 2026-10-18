"""Genera el dataset congelado de evals del backtest point-in-time.

Uso: python data-engine/scripts/build_backtest_eval_dataset.py

Por que generarlo y no escribirlo a mano: un dataset de gates escrito a mano
solo demuestra que el gate pasa sobre el JSON que el autor del gate escribio.
Este script siembra una base de datos con deliberately sembradas trampas de
look-ahead (un hecho FY2999, un filing posterior al corte, una tesis todavia no
publicada, un precio en el futuro), ejecuta ``ThesisBacktestService.cell`` de
verdad, y congela los artefactos resultantes. Asi cada caso del dataset es una
salida real del pipeline y cada ``expect_gate_failure`` es una mutacion
deliberada de una salida real: la pregunta "si el replay se rompiera asi, lo
detectaria el gate?" tiene una respuesta ejecutada, noDeclaration.

Determinista: sin red, sin LLM, sin reloj (fechas fijas). Salida:
``evals/backtest/backtest_v1.json``.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("APP_ENV", "test")
os.environ["RESEARCH_AUTH_REQUIRED"] = "false"
os.environ["WORKERS_ENABLED"] = "false"
os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    CalculatedMetric,
    Claim,
    ClaimEvidence,
    Company,
    Document,
    FinancialFact,
    MarketPrice,
    Tenant,
    ThesisSection,
    ThesisVersion,
)
from app.models.thesis_backtest import BacktestCellRow  # noqa: E402,F401
from app.services.thesis_backtest_service import ThesisBacktestService  # noqa: E402

DATASET_VERSION = "backtest-v1"
GENERATED_NOTE = (
    "Generado por scripts/build_backtest_eval_dataset.py ejecutando "
    "ThesisBacktestService.cell sobre una BD sembrada con trampas de look-ahead. "
    "No editar a mano: las mutaciones de los controles negativos son deliberadas."
)


def _ts(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------- company specs

# (ticker, company_type, valuation_model, factor_tags, metric->value per fiscal year)
COMPANIES: list[dict] = [
    {
        "ticker": "IND",
        "name": "Industrial 2000 SA",
        "company_type": "industrial",
        "valuation_model": "standard_dcf",
        "factor_tags": [],
        "years": {
            2022: {"revenue": 820.0, "free_cash_flow": 74.0, "net_debt": 260.0, "shares_diluted": 100.0},
            2023: {"revenue": 900.0, "free_cash_flow": 95.0, "net_debt": 240.0, "shares_diluted": 100.0},
            2024: {"revenue": 1000.0, "free_cash_flow": 120.0, "net_debt": 300.0, "shares_diluted": 100.0},
        },
        # FY2025 exists in the database but is FILED on 2026-03-10. A replay at
        # 2025-06-30 must not see it; a replay at 2026-06-30 must.
        "late_filing": {
            2025: {"revenue": 1150.0, "free_cash_flow": 160.0, "net_debt": 280.0, "shares_diluted": 100.0},
            "published": date(2026, 3, 10),
        },
        "base_price": 12.0,
    },
    {
        "ticker": "BNK",
        "trap_full_period": True,
        "name": "Banco del Norte",
        "company_type": "bank",
        "valuation_model": "bank_residual_income",
        "factor_tags": [],
        "years": {
            2022: {"tangible_book_value": 480.0, "shares_diluted": 100.0, "roe": 0.1057, "cost_of_equity": 0.10, "book_value_growth": 0.03},
            2023: {"tangible_book_value": 520.0, "shares_diluted": 100.0, "roe": 0.1107, "cost_of_equity": 0.10, "book_value_growth": 0.035},
            2024: {"tangible_book_value": 560.0, "shares_diluted": 100.0, "roe": 0.1167, "cost_of_equity": 0.10, "book_value_growth": 0.04},
        },
        "late_filing": None,
        "base_price": 8.5,
    },
    {
        "ticker": "INS",
        "trap_full_period": True,
        "name": "Seguros Peninsula",
        "company_type": "insurer",
        "valuation_model": "insurance_book_value",
        "factor_tags": [],
        "years": {
            2023: {"book_value": 300.0, "shares_diluted": 60.0, "roe": 0.08, "cost_of_equity": 0.10, "combined_ratio": 0.94, "book_value_growth": 0.03},
            2024: {"book_value": 330.0, "shares_diluted": 60.0, "roe": 0.0909, "cost_of_equity": 0.10, "combined_ratio": 0.91, "book_value_growth": 0.035},
        },
        "late_filing": None,
        "base_price": 6.0,
    },
    {
        "ticker": "REE",
        "trap_full_period": True,
        "name": "Inmobiliaria Costa",
        "company_type": "reit",
        "valuation_model": "reit_nav",
        "factor_tags": [],
        "years": {
            2023: {"net_operating_income": 45.0, "cap_rate": 0.055, "net_debt": 400.0, "shares_diluted": 100.0},
            2024: {"net_operating_income": 52.0, "cap_rate": 0.05, "net_debt": 380.0, "shares_diluted": 100.0},
        },
        "late_filing": None,
        "base_price": 9.0,
    },
    {
        "ticker": "MIN",
        "name": "Minas del Norte",
        "company_type": "mining",
        "valuation_model": "commodity",
        "factor_tags": ["commodities"],
        "years": {
            2023: {"realized_commodity_price": 42.0, "cash_cost_per_unit": 24.0, "production_volume": 120.0, "net_debt": 500.0, "shares_diluted": 100.0, "effective_tax_rate": 0.25, "commodity_earnings_multiple": 6.0},
            2024: {"realized_commodity_price": 48.0, "cash_cost_per_unit": 25.0, "production_volume": 130.0, "net_debt": 470.0, "shares_diluted": 100.0, "effective_tax_rate": 0.25, "commodity_earnings_multiple": 6.5},
        },
        "late_filing": None,
        "base_price": 4.0,
    },
    {
        "ticker": "NEW",
        "name": "Newco Biologics",
        "company_type": "pre_revenue",
        "valuation_model": "probability_weighted_scenarios",
        "factor_tags": ["pre_fcf", "speculative"],
        "years": {
            2023: {"cash_and_equivalents": 180.0, "total_debt": 60.0, "operating_cash_flow": -45.0, "capital_expenditure": -30.0, "shares_diluted": 50.0},
            2024: {"cash_and_equivalents": 140.0, "total_debt": 95.0, "operating_cash_flow": -60.0, "capital_expenditure": -40.0, "shares_diluted": 52.0},
        },
        "late_filing": None,
        "base_price": 3.2,
    },
    {
        "ticker": "GRP",
        "name": "Grupo diversified",
        "company_type": "asset_manager",
        "valuation_model": "sotp",
        "factor_tags": ["sotp"],
        "years": {
            2023: {"segment_retail_operating_metric": 40.0, "segment_retail_valuation_multiple": 10.0, "segment_utilities_operating_metric": 500.0, "segment_utilities_valuation_multiple": 1.1, "net_debt": 150.0, "shares_diluted": 100.0, "holding_company_discount": 0.12},
            2024: {"segment_retail_operating_metric": 45.0, "segment_retail_valuation_multiple": 10.0, "segment_utilities_operating_metric": 500.0, "segment_utilities_valuation_multiple": 1.1, "net_debt": 130.0, "shares_diluted": 100.0, "holding_company_discount": 0.12},
        },
        "late_filing": None,
        "base_price": 7.5,
    },
    {
        # TRAMPA 2: una company's FY2025 accounts exist in the database but were
        # filed on 2026-04-20. Every cutoff before that date must not see them,
        # even though the *period* (2025-12-31) would pass a naive fiscal-year
        # guard. This is the trap a period-end-only check walks straight into.
        "ticker": "FIL",
        "name": "Filing Tardio SA",
        "company_type": "industrial",
        "valuation_model": "standard_dcf",
        "factor_tags": [],
        "years": {
            2023: {"revenue": 700.0, "free_cash_flow": 60.0, "net_debt": 200.0, "shares_diluted": 100.0},
            2024: {"revenue": 780.0, "free_cash_flow": 78.0, "net_debt": 190.0, "shares_diluted": 100.0},
        },
        "late_filing": {
            2025: {"revenue": 1600.0, "free_cash_flow": 240.0, "net_debt": 150.0, "shares_diluted": 100.0},
            "published": date(2026, 4, 20),
        },
        "base_price": 10.0,
    },
    {
        # Empresa SIN trampas: ni FY2999, ni filing tardio, ni precio futuro.
        # Existe para dos cosas: (1) que el dataset tenga replayes limpios donde
        # los gates se ejercitan en su camino feliz, y (2) ser la base de las
        # mutaciones de los controles negativos. Un control negativo que muta una
        # celda que ya venia con trampas no demuestra que el gate muerde, solo
        # que la trampa se nota.
        "ticker": "CLN",
        "name": "Compania Limpia SA",
        "company_type": "industrial",
        "valuation_model": "standard_dcf",
        "factor_tags": [],
        "years": {
            2022: {"revenue": 600.0, "free_cash_flow": 50.0, "net_debt": 180.0, "shares_diluted": 100.0},
            2023: {"revenue": 660.0, "free_cash_flow": 62.0, "net_debt": 170.0, "shares_diluted": 100.0},
            2024: {"revenue": 720.0, "free_cash_flow": 80.0, "net_debt": 160.0, "shares_diluted": 100.0},
        },
        "late_filing": None,
        "base_price": 11.0,
        "clean": True,
    },
    {
        # Banco SIN trampas. Existe para que el gate de escenarios
        # (bear <= base <= bull) se ejercite sobre celdas REALMENTE valoradas y
        # no solo sobre abstenciones: los motores sectoriales se saltan el
        # snapshot, asi que sin una empresa limpia de este sector el dataset
        # no tendria ningun caso de banker con bear/base/bull que comprobar.
        "ticker": "CLB",
        "name": "Banco Limpio",
        "company_type": "bank",
        "valuation_model": "bank_residual_income",
        "factor_tags": [],
        "years": {
            2022: {"tangible_book_value": 420.0, "shares_diluted": 100.0, "roe": 0.098, "cost_of_equity": 0.10, "book_value_growth": 0.03},
            2023: {"tangible_book_value": 455.0, "shares_diluted": 100.0, "roe": 0.104, "cost_of_equity": 0.10, "book_value_growth": 0.032},
            2024: {"tangible_book_value": 490.0, "shares_diluted": 100.0, "roe": 0.112, "cost_of_equity": 0.10, "book_value_growth": 0.035},
        },
        "late_filing": None,
        "base_price": 7.4,
        "clean": True,
    },
    {
        "ticker": "CLR",
        "name": "Reit Limpia",
        "company_type": "reit",
        "valuation_model": "reit_nav",
        "factor_tags": [],
        "years": {
            2022: {"net_operating_income": 38.0, "cap_rate": 0.06, "net_debt": 300.0, "shares_diluted": 100.0},
            2023: {"net_operating_income": 41.0, "cap_rate": 0.058, "net_debt": 290.0, "shares_diluted": 100.0},
            2024: {"net_operating_income": 44.0, "cap_rate": 0.057, "net_debt": 280.0, "shares_diluted": 100.0},
        },
        "late_filing": None,
        "base_price": 8.2,
        "clean": True,
    },
    {
        "ticker": "CLM",
        "name": "Minas Limpia",
        "company_type": "mining",
        "valuation_model": "commodity",
        "factor_tags": ["commodities"],
        "years": {
            2022: {"realized_commodity_price": 38.0, "cash_cost_per_unit": 22.0, "production_volume": 100.0, "net_debt": 420.0, "shares_diluted": 100.0, "effective_tax_rate": 0.25, "commodity_earnings_multiple": 5.5},
            2023: {"realized_commodity_price": 41.0, "cash_cost_per_unit": 23.0, "production_volume": 110.0, "net_debt": 410.0, "shares_diluted": 100.0, "effective_tax_rate": 0.25, "commodity_earnings_multiple": 5.8},
            2024: {"realized_commodity_price": 45.0, "cash_cost_per_unit": 23.5, "production_volume": 118.0, "net_debt": 395.0, "shares_diluted": 100.0, "effective_tax_rate": 0.25, "commodity_earnings_multiple": 6.0},
        },
        "late_filing": None,
        "base_price": 3.6,
        "clean": True,
    },
]

BENCHMARK = {
    "ticker": "^GSPC",
    "name": "S&P 500 (benchmark)",
    "company_type": "index",
    "valuation_model": "none",
}

THESIS_CLAIMS = {
    "IND": "Revenue {revenue} grows with a durable margin.",
    "BNK": "Tangible book value {tangible_book_value} compounds at a stable return.",
    "INS": "Book value {book_value} supports the current solvency ratio.",
    "REE": "Net operating income {net_operating_income} funds the portfolio.",
    "MIN": "Realised price {realized_commodity_price} per tonne underpins the plan.",
    "NEW": "Cash {cash_and_equivalents} funds the runway to the next readout.",
    "GRP": "Retail segment {segment_retail_operating_metric} anchors the sum of the parts.",
    "FIL": "Revenue {revenue} recovers as the order book converts.",
    "CLN": "Revenue {revenue} grows with a stable margin.",
    "CLB": "Tangible book value {tangible_book_value} compounds steadily.",
    "CLR": "Net operating income {net_operating_income} covers the debt cost.",
    "CLM": "Realised price {realized_commodity_price} per tonne underpins the plan.",
}

# Cutoffs exercised per ticker. Includes dates before the thesis exists, dates
# where only early filings are public, and dates after the late FY2025 filing.
CUTOFFS = [date(2024, 6, 30), date(2024, 12, 31), date(2025, 6, 30), date(2026, 6, 30)]


def _seed_company(db, spec: dict) -> None:
    company = Company(
        ticker=spec["ticker"],
        name=spec["name"],
        exchange="TEST",
        currency="EUR",
        sector="Test",
        industry="Test",
        company_type=spec["company_type"],
        valuation_model=spec["valuation_model"],
        special_sources=[],
        special_risks=[],
        factor_tags=spec["factor_tags"],
    )
    db.add(company)
    db.flush()

    def add_facts(facts: dict, fiscal_year: int, published: date, tag: str) -> Document:
        document = Document(
            company_id=company.id,
            title=f"{spec['ticker']} accounts FY{fiscal_year}",
            source_type="sec_10k",
            source_url=f"https://example.invalid/{spec['ticker']}/{fiscal_year}",
            published_at=_ts(published),
        )
        db.add(document)
        db.flush()
        for metric, value in facts.items():
            unit = "ratio" if metric in {"roe", "cap_rate", "tax_rate", "combined_ratio"} else "EUR"
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=Decimal(str(value)),
                    unit=unit,
                    period=f"{fiscal_year}-12-31",
                    fiscal_year=fiscal_year,
                    fiscal_quarter="FY",
                    source_id=document.id,
                    source_type="sec",
                    confidence=Decimal("0.92"),
                )
            )
        del tag
        return document

    latest_year = max(spec["years"])
    latest_facts = spec["years"][latest_year]
    for fiscal_year, facts in sorted(spec["years"].items()):
        # Filed with the usual lag: an annual report lands in spring of the
        # following year, so FY2023 is public from 2024-03-15 onwards.
        add_facts(facts, fiscal_year, date(fiscal_year + 1, 3, 15), "annual")
    if spec["late_filing"]:
        late = spec["late_filing"]
        add_facts(late[2025], 2025, late["published"], "late")

    # TRAMPA 1: un hecho de un ejercicio absurdo (FY2999) con fecha de
    # lectura inequívoca. Ninguna fecha de corte de la rejilla puede verlo, y
    # su presencia es lo que demuestra que el filtro point-in-time funciona: sin
    # este hecho, una celda verde no probaría nada.
    if not spec.get("clean"):
        # Los motores sectoriales (banco, aseguradora, REIT) leen FinancialFact
        # directamente y anclan el periodo en la fila MAS RECIENTE de su metrica
        # ancla (ver _resolve_inputs). Desde #727 una sola fila FY2999 se
        # convierte en el ancla y el resto de entradas no existen en ese
        # ejercicio: el motor se abstiene (N/D) en vez de filtrar el futuro, lo
        # cual es honesto pero deja el guard de look-ahead sin ejercitar. Para
        # que la trampa llegue al guard, esos sectores reciben el FY2999
        # COMPLETO (todas las entradas del motor): el motor valora con datos
        # futuros y el guard publico tiene que rechazar la celda.
        trap_metrics = list(latest_facts) if spec.get("trap_full_period") else [next(iter(latest_facts))]
        # La trampa tambien tiene filing real (en 2999): con la politica de
        # abstencion, sin published_on no seria una trampa de futuro sino una
        # fila no verificable, y el guard de look-ahead no se ejercitaria.
        trap_doc = Document(
            company_id=company.id,
            title=f"{company.ticker} TRAMPA FY2999",
            source_type="sec_10k",
            source_url=f"https://example.invalid/{company.ticker}/2999",
            published_at=_ts(date(2999, 3, 15)),
        )
        db.add(trap_doc)
        db.flush()
        for trap_metric in trap_metrics:
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=trap_metric,
                    source_id=trap_doc.id,
                    value=Decimal("999999") if len(trap_metrics) == 1 else Decimal(str(latest_facts[trap_metric])),
                    unit="EUR",
                    period="2999-12-31",
                    fiscal_year=2999,
                    fiscal_quarter="FY",
                    source_type="sec",
                    confidence=Decimal("0.99"),
                )
            )

    db.add(
        CalculatedMetric(
            company_id=company.id,
            metric="wacc",
            value=Decimal("0.09"),
            unit="decimal",
            period=f"{latest_year}-12-31:FY",
            fiscal_year=latest_year,
            status="ok",
            definition_version="WACC_STANDARD_V1",
            formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
            # computed before every replay cutoff (PIT filter: created_at <= as_of)
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )

    # Daily-ish price series with a deterministic ramp, plus a *future* price
    # row that the replay must never touch.
    for offset in range(0, 900, 7):
        day = date(2024, 1, 2) + timedelta(days=offset)
        price = Decimal(str(round(spec["base_price"] * (1 + offset * 0.0009), 4)))
        db.add(
            MarketPrice(
                company_id=company.id,
                date=day,
                close=price,
                adj_close=price,
                source="seed",
            )
        )
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2027, 6, 1),
            close=Decimal("999.0"),
            adj_close=Decimal("999.0"),
            source="seed_future_trap",
        )
        if not spec.get("clean")
        else MarketPrice(
            company_id=company.id,
            date=date(2024, 1, 1),
            close=Decimal("11.0"),
            adj_close=Decimal("11.0"),
            source="seed",
        )
    )

    thesis_day = date(2024, 7, 15)
    thesis = ThesisVersion(
        company_id=company.id,
        version=1,
        status="published",
        thesis_markdown=f"# {spec['name']}\nTesis publicada el {thesis_day.isoformat()}.",
        executive_summary=spec["name"],
        rating="buy",
        source_coverage_score=90,
        created_at=_ts(thesis_day),
    )
    db.add(thesis)
    db.flush()

    template = THESIS_CLAIMS[spec["ticker"]]
    filled = template.format(**{k: _pretty(v) for k, v in latest_facts.items()})
    metric = next(iter(latest_facts))
    claim = Claim(
        company_id=company.id,
        thesis_version_id=thesis.id,
        statement=filled,
        claim_type="thesis",
        status="verified",
        confidence=Decimal("0.80"),
        materiality_score=8,
        created_at=_ts(thesis_day),
        metadata_={"metric": metric},
    )
    db.add(claim)
    db.flush()
    evidence_doc = db.scalar(
        select(Document).where(
            Document.company_id == company.id,
            Document.title == f"{spec['ticker']} accounts FY{latest_year}",
        )
    )
    assert evidence_doc is not None, spec["ticker"]
    db.add(
        ClaimEvidence(
            claim_id=claim.id,
            document_id=evidence_doc.id,
            source_url=f"https://example.invalid/{spec['ticker']}/{latest_year}",
            evidence_type="supports",
            summary=f"FY{latest_year} reported accounts",
            quote=template.split("{")[0].strip(),
            confidence=Decimal("0.85"),
            source_tier="primary",
            created_at=_ts(thesis_day),
        )
    )

    # Stored debate verdict, persisted before the later cutoffs.
    db.add(
        ThesisSection(
            thesis_version_id=thesis.id,
            company_id=company.id,
            section_key="thesis_debate",
            title="Thesis debate (bull vs bear)",
            body="VEREDICTO: neutral | evidencia equilibrada",
            status="published",
            order_index=999,
            created_at=_ts(thesis_day),
            metadata_={"verdict": "neutral", "model": "deterministic", "degraded": False},
        )
    )
    db.commit()
    return company


def _pretty(value: float) -> str:
    """Render a fact the way the claim prose does: no trailing ``.0`` noise."""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _seed_benchmark(db) -> None:
    company = Company(
        ticker=BENCHMARK["ticker"],
        name=BENCHMARK["name"],
        exchange="INDEX",
        currency="EUR",
        sector="Index",
        industry="Index",
        company_type="index",
        valuation_model="none",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    for offset in range(0, 900, 7):
        day = date(2024, 1, 2) + timedelta(days=offset)
        price = Decimal(str(round(100.0 * (1 + offset * 0.0004), 4)))
        db.add(
            MarketPrice(
                company_id=company.id, date=day, close=price, adj_close=price, source="seed"
            )
        )
    db.commit()


# ------------------------------------------------------------------ artifact build


def _used_periods(cell) -> list[dict]:
    """Every fact the point-in-time filter CONSIDERED AND KEPT, with both dates."""
    snapshot = (cell.point_in_time or {}).get("snapshot") or {}
    out: list[dict] = []
    for entry in snapshot.get("kept") or []:
        period = entry.get("period") or {}
        out.append(
            {
                "metric": entry.get("metric"),
                "raw": period.get("raw"),
                "end_date": period.get("end_date"),
                "precision": period.get("precision"),
                "source_published_on": entry.get("published_on"),
            }
        )
    return out


def _violation_detail(cell) -> list[dict]:
    out: list[dict] = []
    for entry in _used_periods(cell):
        end_date = entry["end_date"]
        if end_date and end_date > cell.as_of.isoformat():
            out.append({"metric": entry["metric"], "end_date": end_date})
    return out


def _engine_trace_periods(cell) -> list[dict]:
    """Periods from the ENGINE's own trace, not from the point-in-time snapshot.

    Four of the eight valuation engines (``bank``, ``insurer``, ``reit``,
    ``holding_company``/``sotp`` and ``commodity``) query ``FinancialFact``
    directly instead of going through the snapshot, so their periods are
    invisible to the snapshot audit. The gate needs both lists or it would pass
    every sector cell without having checked a single date.
    """
    periods = (cell.point_in_time or {}).get("valuation_periods") or {}
    out: list[dict] = []
    for metric, raw in periods.items():
        if raw is None:
            continue
        out.append(
            {
                "metric": metric,
                "raw": raw,
                "end_date": _period_end(str(raw)),
                "precision": "from_trace",
                "source_published_on": None,
            }
        )
    return out


def _period_end(raw: str) -> str | None:
    from app.valuation.period_bounds import parse_period_bounds

    bounds = parse_period_bounds(period=raw)
    return bounds.end_date.isoformat() if bounds.end_date else None


def _artifact(cell, siblings: list[dict], scenarios: dict | None) -> dict:
    claims = [
        {
            "text": item.get("statement"),
            "metric": item.get("metric"),
            "has_evidence": item.get("has_evidence"),
            "evidence_published_on": None,
        }
        for item in cell.claims
    ]
    return {
        "ticker": cell.ticker,
        "as_of": cell.as_of.isoformat(),
        "evidence_cutoff": cell.evidence_cutoff.isoformat(),
        "as_of_source": (cell.point_in_time or {}).get("as_of_source"),
        "status": cell.status,
        "fair_value": _num(cell.fair_value),
        "bear_value": _num(cell.bear_value),
        "base_value": _num(cell.base_value),
        "bull_value": _num(cell.bull_value),
        "current_price": _num(cell.current_price),
        "upside": _num(cell.upside),
        "engine_key": cell.engine_key,
        "model_version": cell.model_version,
        "degraded": cell.degraded,
        "degraded_reason": cell.degraded_reason,
        "source_coverage_score": cell.source_coverage_score,
        "n_claims": cell.n_claims,
        "n_claims_with_evidence": cell.n_claims_with_evidence,
        "debate_verdict": cell.debate_verdict,
        "lookahead_violations": list(cell.lookahead_violations),
        "excluded_future_inputs": list(cell.excluded_future_inputs),
        "unverifiable_inputs": list(cell.unverifiable_inputs),
        "missing_inputs": list(cell.missing_inputs),
        "used_periods": _used_periods(cell),
        "engine_trace_periods": _engine_trace_periods(cell),
        "lookahead_violations_detail": _violation_detail(cell),
        "claims": claims,
        "scenario_probabilities": scenarios,
        "declared_constant_reason": _constant_reason(siblings),
        "realized": cell.realized,
        "siblings": siblings,
        "replay_hash": cell.cell_hash,
        "replay_hash_again": "",  # filled by the caller with a second run
    }


def _num(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _frozen_facts(spec: dict) -> dict[str, list[float]]:
    """Every reported value per metric, across every frozen year.

    A list per metric, not a scalar: a claim legitimately quotes last year's
    revenue, and a scalar would let the most recent filing overwrite the
    history and make the invented-numbers gate fail a true statement.
    """
    out: dict[str, list[float]] = {}
    vintages: list[dict] = list(spec["years"].values())
    if spec["late_filing"]:
        vintages.append(spec["late_filing"][2025])
    for facts in vintages:
        for metric, value in facts.items():
            out.setdefault(metric, []).append(float(value))
    return out


def _constant_reason(siblings: list[dict]) -> str | None:
    """Why a ticker's fair value did not move between cutoffs — or ``None``.

    A horizontal line across dates is the signature of a backtest with no
    information, so the gate flags it. It is also the *correct* outcome when no
    new fact was published between two cutoffs, which is exactly what a fixed
    annual filing calendar produces. The distinction is checkable, so the
    dataset declares it: silent repetition is a finding, declared repetition is
    a fact about the world.
    """
    scored = [item for item in siblings if item["status"] == "ok" and item["fair_value"]]
    if len(scored) < 2:
        return None
    values = {round(float(item["fair_value"]), 6) for item in scored}
    if len(values) != 1:
        return None
    return (
        f"el mismo juego de hechos ({scored[0]['as_of']} y {scored[-1]['as_of']}) "
        "sigue siendo el ultimo publicado en todos los cortes: no se filtro ninguna "
        "publicacion nueva entre esas fechas"
    )


def build_cases(db) -> list[dict]:
    service = ThesisBacktestService()
    cases: list[dict] = []

    for spec in COMPANIES:
        ticker = spec["ticker"]
        cells = {}
        for cutoff in CUTOFFS:
            cell = service.cell(db, ticker, cutoff)
            again = service.cell(db, ticker, cutoff)
            cell.cell_hash = cell.cell_hash or cell.compute_hash()
            cells[cutoff] = (cell, again)

        siblings = [
            {"as_of": cutoff.isoformat(), "status": cell.status, "fair_value": _num(cell.fair_value)}
            for cutoff, (cell, _again) in sorted(cells.items())
        ]
        scenarios = {"bear": 0.3, "base": 0.45, "bull": 0.25}

        for index, (cutoff, (cell, again)) in enumerate(sorted(cells.items())):
            artifact = _artifact(cell, siblings, scenarios)
            artifact["replay_hash_again"] = again.cell_hash
            category, note = _classify(cell, index, ticker)
            cases.append(
                {
                    "id": f"{ticker.lower()}_{cutoff.isoformat()}",
                    "category": category,
                    "ticker": ticker,
                    "as_of": cutoff.isoformat(),
                    "note": note,
                    "applies_to": None,
                    "expect_gate_failure": None,
                    "expected": {
                        "as_of": cutoff.isoformat(),
                        "evidence_cutoff": cell.evidence_cutoff.isoformat(),
                        "status": cell.status,
                    },
                    "frozen_facts": _frozen_facts(spec),
                    "artifact": artifact,
                }
            )
    return cases


def _classify(cell, index: int, ticker: str) -> tuple[str, str]:
    """Name the trap this cell actually faced, not the sector it belongs to."""
    if cell.status == "not_yet_published":
        return (
            "lookahead_trap_thesis_publication",
            "La tesis se publico despues del corte: celda vacia, no un 0.",
        )
    if cell.status == "rejected_lookahead":
        return (
            "lookahead_trap_period_leak",
            "Un periodo posterior llego a la valoracion: celda rechazada y contada.",
        )
    excluded = cell.excluded_future_inputs
    if any("2999" in item for item in excluded):
        return (
            "lookahead_trap_fiscal_year_2999",
            "La BD contenia un hecho FY2999 y la celda no lo uso.",
        )
    if excluded:
        return (
            "lookahead_trap_filing_date",
            f"La BD contenia {len(excluded)} hecho(s) publicado(s) despues del corte "
            "y la celda no los uso.",
        )
    if cell.status == "insufficient_data":
        return ("insufficient_data", f"Sin datos suficientes: {cell.degraded_reason}")
    if cell.unverifiable_inputs:
        return (
            "unverifiable_provenance",
            "Insumos sin fecha de publicacion verificable: celda degradada.",
        )
    if cell.degraded:
        return ("degraded_with_reason", f"Degradada: {cell.degraded_reason}")
    if index == 0 and ticker == "IND":
        return ("valid_replay", "Replay limpio con evidencia previa al corte.")
    return (
        "valid_replay",
        f"Replay point-in-time con {cell.n_claims} claim(s) y evidencia previa al corte.",
    )


# ----------------------------------------------------------------- negative controls


def _base_case(cases: list[dict], ticker: str) -> dict:
    for case in cases:
        if case["ticker"] == ticker and case["category"] == "valid_replay":
            return case
    raise SystemExit(f"no valid_replay case for {ticker}")

def _negative_controls(cases: list[dict]) -> list[dict]:
    """Mutated real artifacts: each one is a replay that has gone wrong.

    A negative control is only worth having if the gate actually bites, so each
    entry below changes exactly one thing about a cell that genuinely passed, and
    declares the single gate that must then fail.
    """
    base = _base_case(cases, "CLN")
    out: list[dict] = []

    def add(suffix: str, gate: str, note: str, mutate) -> None:
        case = json.loads(json.dumps(base))
        case["id"] = f"neg_{suffix}"
        case["category"] = "negative_control"
        case["note"] = note
        case["expect_gate_failure"] = gate
        mutate(case)
        out.append(case)

    def leak_period(case: dict) -> None:
        case["artifact"]["used_periods"].append(
            {
                "metric": "revenue",
                "raw": "FY2999",
                "end_date": "2999-12-31",
                "precision": "exact_date",
                "source_published_on": "2999-03-01",
            }
        )

    add(
        "periodo_futuro",
        "no_lookahead",
        "Un hecho FY2999 se cuela en el snapshot: debe abortar la celda.",
        leak_period,
    )

    def drop_as_of(case: dict) -> None:
        case["expected"].pop("as_of", None)

    add(
        "sin_as_of",
        "no_lookahead",
        "El caso no declara expected.as_of: el gate no puede omitirse.",
        drop_as_of,
    )

    def future_cutoff(case: dict) -> None:
        case["artifact"]["evidence_cutoff"] = "2027-01-01"

    add(
        "corte_futuro",
        "evidence_cutoff_respected",
        "El corte de evidencia es posterior al as_o de la celda.",
        future_cutoff,
    )

    def drop_cutoff(case: dict) -> None:
        case["expected"].pop("evidence_cutoff", None)

    add(
        "sin_corte",
        "evidence_cutoff_respected",
        "El caso no declara expected.evidence_cutoff: el gate no puede omitirse.",
        drop_cutoff,
    )

    def fill_with_price(case: dict) -> None:
        case["artifact"]["status"] = "insufficient_data"
        case["artifact"]["fair_value"] = case["artifact"]["current_price"]

    add(
        "abstencion_rellenada",
        "insufficient_data_not_filled_with_price",
        "Una abstención rellenada con el precio actual: el fallo que arruina un hit-rate.",
        fill_with_price,
    )

    def invert_scenarios(case: dict) -> None:
        case["artifact"]["bear_value"] = 99.0
        case["artifact"]["bull_value"] = 1.0

    add(
        "escenarios_invertidos",
        "bear_le_base_le_bull",
        "El escenario bear por encima del bull.",
        invert_scenarios,
    )

    def silent_degradation(case: dict) -> None:
        case["artifact"]["degraded"] = True
        case["artifact"]["degraded_reason"] = ""

    add(
        "degradada_sin_motivo",
        "degraded_reason_present_when_degraded",
        "Celda degradada sin motivo: no se puede depurar ni justificar.",
        silent_degradation,
    )

    def drop_coverage(case: dict) -> None:
        case["artifact"]["source_coverage_score"] = None

    add(
        "cobertura_ausente",
        "source_coverage_score_present",
        "Cobertura de fuentes no calculada: el gate no puede omitirse.",
        drop_coverage,
    )

    def impossible_ratio(case: dict) -> None:
        case["artifact"]["n_claims"] = 1
        case["artifact"]["n_claims_with_evidence"] = 4

    add(
        "ratio_imposible",
        "claims_have_evidence_ratio_recorded",
        "Mas claims con evidencia que claims totales.",
        impossible_ratio,
    )

    def unstable_replay(case: dict) -> None:
        case["artifact"]["replay_hash_again"] = "0" * 64

    add(
        "replay_inestable",
        "idempotent_replay",
        "Dos ejecuciones de la misma celda dan hashes distintos.",
        unstable_replay,
    )

    def drop_hash(case: dict) -> None:
        case["artifact"].pop("replay_hash", None)
        case["artifact"].pop("replay_hash_again", None)

    add(
        "replay_sin_hash",
        "idempotent_replay",
        "Sin hash de replay: el gate no puede omitirse.",
        drop_hash,
    )

    def invent_number(case: dict) -> None:
        case["artifact"]["claims"][0]["text"] = "Revenue 98765 grows."

    add(
        "numero_inventado",
        "no_invented_numbers",
        "Claim con una magnitud que ningun hecho congelado respalda.",
        invent_number,
    )

    def drop_facts(case: dict) -> None:
        case.pop("frozen_facts", None)

    add(
        "sin_frozen_facts",
        "no_invented_numbers",
        "Sin frozen_facts no hay contra que comprobar: el gate no puede omitirse.",
        drop_facts,
    )

    def flat_line(case: dict) -> None:
        value = case["artifact"]["fair_value"]
        for sibling in case["artifact"]["siblings"]:
            sibling["status"] = "ok"
            sibling["fair_value"] = value
        case["artifact"].pop("declared_constant_reason", None)

    add(
        "linea_plana",
        "net_neutral_honest",
        "Todas las fechas dan el mismo fair_value sin motivo declarado.",
        flat_line,
    )

    def bad_probabilities(case: dict) -> None:
        case["artifact"]["scenario_probabilities"] = {"bear": 0.5, "base": 0.6, "bull": 0.3}

    add(
        "probabilidades",
        "probabilities_sum_to_one",
        "Las probabilidades de escenario suman 1,4.",
        bad_probabilities,
    )

    return out


def main() -> int:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(external_id="tenant-backtest-evals", name="Backtest evals", status="active")
    session.add(tenant)
    session.commit()
    session.info["tenant_id"] = tenant.id

    for spec in COMPANIES:
        _seed_company(session, spec)
    _seed_benchmark(session)

    cases = build_cases(session)
    cases.extend(_negative_controls(cases))

    dataset = {
        "version": DATASET_VERSION,
        "generated_by": "scripts/build_backtest_eval_dataset.py",
        # Empresas FICTICIAS y datos sinteticos: esto no es un backtest real ni
        # sus cifras son de ninguna compania. Que nadie lo lea como tal.
        "origin": "synthetic_fixture",
        "note": GENERATED_NOTE,
        "cases": cases,
    }
    target = ROOT / "evals" / "backtest" / "backtest_v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    negatives = [case for case in cases if case["expect_gate_failure"]]
    print(f"{len(cases)} casos -> {target.relative_to(ROOT)}")
    print(f"  controles negativos: {len(negatives)}")
    from collections import Counter

    for category, count in sorted(Counter(case["category"] for case in cases).items()):
        print(f"  {category}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
