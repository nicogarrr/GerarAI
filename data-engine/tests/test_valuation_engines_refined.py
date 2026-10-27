"""Refinamiento de motores de valoración.

Cubre: (1) cada motor principal expone bear/base/bull + tabla de sensibilidad
no vacía; (2) coherencia cruzada entre motores para la misma empresa
(magnitudes, finitud, as_of respetado); (3) bordes: beneficios negativos,
caja neta y pre-revenue sin ingresos.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import CalculatedMetric, Company, FinancialFact, MarketPrice
from app.services.valuation_service import ValuationService

PERIOD = "FY2025"
FY = 2025


def _make_company(db, ticker, *, company_type, valuation_model, factor_tags=None):
    existing = db.scalar(select(Company).where(Company.ticker == ticker))
    if existing:
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == existing.id))
        db.execute(delete(MarketPrice).where(MarketPrice.company_id == existing.id))
        # SQLite reuses rowids, so a recreated company can inherit a stale
        # calculated_metrics row (e.g. a WACC) from a previous test. The
        # valuation engines now prefer the persisted traceable WACC, so the
        # leftovers have to go with the company.
        db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == existing.id))
        db.delete(existing)
        db.commit()
    company = Company(
        ticker=ticker,
        name=f"refined {ticker}",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type=company_type,
        valuation_model=valuation_model,
        special_sources=[],
        special_risks=[],
        factor_tags=factor_tags or [],
    )
    db.add(company)
    db.flush()
    return company


def _add_facts(db, company, facts, *, confidence="0.90"):
    for metric, value in facts.items():
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(value)),
                unit="USD",
                period=PERIOD,
                fiscal_year=FY,
                fiscal_quarter="FY",
                source_type="refined_test",
                confidence=Decimal(confidence),
            )
        )
    db.commit()


def _add_traceable_wacc(db, company, value=0.09):
    """A dated, sourced WACC.

    Without one the DCF falls back to the tag default and is labelled
    ``status="partial"``: a valuation whose discount rate is an assumption
    nobody can trace is not a final valuation. Tests that assert engine
    coherence need a fully sourced company, not a publishable one.
    """
    db.add(
        CalculatedMetric(
            company_id=company.id,
            metric="wacc",
            value=Decimal(str(value)),
            unit="decimal",
            period=f"{FY}-12-31:FY",
            fiscal_year=FY,
            status="ok",
            definition_version="WACC_STANDARD_V1",
            formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
        )
    )
    db.commit()


def _add_price(db, company, price):
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2025, 12, 31),
            close=Decimal(str(price)),
            adj_close=Decimal(str(price)),
            source="refined_test",
        )
    )
    db.commit()


def _cleanup(db, tickers):
    ids = [
        c.id for c in db.scalars(select(Company).where(Company.ticker.in_(tickers))).all()
    ]
    if ids:
        db.execute(delete(FinancialFact).where(FinancialFact.company_id.in_(ids)))
        db.execute(delete(MarketPrice).where(MarketPrice.company_id.in_(ids)))
        db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id.in_(ids)))
        db.execute(delete(Company).where(Company.id.in_(ids)))
        db.commit()


def _sensitivity_values(sensitivity):
    """Extrae todos los value_per_share de cualquier formato de sensitivity."""
    vals = []
    for row in (sensitivity or {}).get("rows", []):
        if row.get("value_per_share") is not None:
            vals.append(row["value_per_share"])
        for cell in row.get("values", []) or []:
            if cell.get("value_per_share") is not None:
                vals.append(cell["value_per_share"])
    return vals


def _assert_range_and_sensitivity(result, engine):
    bear, base, bull, expected = (
        result["bear_value"],
        result["base_value"],
        result["bull_value"],
        result["expected_value"],
    )
    assert bear is not None and base is not None, engine
    assert bull is not None and expected is not None, engine
    for v in (bear, base, bull, expected):
        assert math.isfinite(v), (engine, v)
    assert bear <= base <= bull, (engine, bear, base, bull)
    assert bear <= expected <= bull, (engine, expected)
    sens_vals = _sensitivity_values(result.get("sensitivity"))
    assert len(sens_vals) >= 3, (engine, result.get("sensitivity"))
    assert all(math.isfinite(v) for v in sens_vals), engine
    return sens_vals


def _engine_cases():
    """(ticker, routing, facts, price) por motor principal."""
    return [
        (
            "REFSTD",
            dict(company_type="standard", valuation_model="standard_dcf", factor_tags=[]),
            {"revenue": 2000, "free_cash_flow": 300, "revenue_growth": 0.08,
             "shares_diluted": 200, "net_debt": 400},
            25,
        ),
        (
            "REFPRE",
            dict(company_type="pre_revenue", valuation_model="probability_weighted_scenarios",
                 factor_tags=["pre_fcf", "speculative"]),
            {"revenue": 50, "free_cash_flow": 2, "shares_diluted": 100,
             "cash_and_equivalents": 500, "operating_cash_flow": -100,
             "capital_expenditure": -200},
            30,
        ),
        (
            "REFCOM",
            dict(company_type="mining", valuation_model="commodity_cycle", factor_tags=[]),
            {"revenue": 500, "free_cash_flow": 60, "shares_diluted": 100,
             "net_debt": 100, "production_volume": 20, "cash_cost_per_unit": 40,
             "realized_commodity_price": 70, "effective_tax_rate": 0.2,
             "commodity_earnings_multiple": 10},
            12,
        ),
        (
            "REFSOTP",
            dict(company_type="multi_segment", valuation_model="sotp",
                 factor_tags=["sotp"]),
            {"shares_diluted": 100, "net_debt": 250, "holding_company_discount": 0.12,
             "segment_alpha_operating_metric": 80, "segment_alpha_valuation_multiple": 12,
             "segment_beta_operating_metric": 500, "segment_beta_valuation_multiple": 1.1},
            10,
        ),
        (
            "REFHOLD",
            dict(company_type="holding", valuation_model="sotp_holding", factor_tags=[]),
            {"shares_diluted": 100, "net_debt": 250, "holding_company_discount": 0.12,
             "segment_alpha_operating_metric": 80, "segment_alpha_valuation_multiple": 12,
             "segment_beta_operating_metric": 500, "segment_beta_valuation_multiple": 1.1},
            10,
        ),
        (
            "REFBK",
            dict(company_type="bank", valuation_model="bank_residual_income", factor_tags=[]),
            {"tangible_book_value": 1000, "shares_diluted": 100, "roe": 0.14,
             "cost_of_equity": 0.10, "book_value_growth": 0.03},
            14,
        ),
        (
            "REFINS",
            dict(company_type="insurer", valuation_model="insurance_book_value",
                 factor_tags=[]),
            {"book_value": 1200, "shares_diluted": 100, "roe": 0.13,
             "cost_of_equity": 0.10, "combined_ratio": 0.95, "book_value_growth": 0.03},
            16,
        ),
        (
            "REFREIT",
            dict(company_type="reit", valuation_model="reit_nav", factor_tags=[]),
            {"net_operating_income": 100, "cap_rate": 0.05, "net_debt": 600,
             "shares_diluted": 100},
            15,
        ),
    ]


def test_all_engines_expose_bear_base_bull_and_sensitivity():
    init_db()
    db = SessionLocal()
    tickers = [case[0] for case in _engine_cases()]
    try:
        for ticker, routing, facts, price in _engine_cases():
            company = _make_company(db, ticker, **routing)
            _add_facts(db, company, facts)
            _add_price(db, company, price)
            _add_traceable_wacc(db, company)
        for ticker, _, _, _ in _engine_cases():
            company = db.scalar(select(Company).where(Company.ticker == ticker))
            result = ValuationService().value_company(db, company)
            engine = result["trace"]["engine"]
            if engine == "pre_revenue" and result["status"] == "insufficient_data":
                # Quema de caja reportada (OCF < 0): no hay rango por accion con
                # margen FCF supuesto; estado honesto, sin bear/base/bull.
                assert result["base_value"] is None, ticker
                assert result["trace"].get("observed_cash_burn"), ticker
                continue
            assert result["status"] in ("ok", "partial"), (ticker, result["status"])
            assert result["publishable"] is True or engine == "pre_revenue", ticker
            sens_vals = _assert_range_and_sensitivity(result, engine)
            # La sensibilidad debe acotar el caso base (cubre ambos lados).
            assert min(sens_vals) <= result["base_value"] <= max(sens_vals), engine
            probs = result["trace"].get("probabilities")
            if probs:
                assert abs(sum(probs.values()) - 1.0) < 1e-9, engine
            scenarios = result["trace"].get("scenarios")
            if scenarios:
                s_probs = [s["definition"]["probability"] for s in scenarios.values()]
                assert abs(sum(s_probs) - 1.0) < 1e-6, engine
    finally:
        _cleanup(db, tickers)
        db.close()


def test_cross_engine_coherence_same_company():
    """Misma empresa, tres motores: magnitudes, finitud y as_of coherentes."""
    init_db()
    db = SessionLocal()
    ticker = "XCOH"
    try:
        company = _make_company(
            db, ticker, company_type="standard", valuation_model="standard_dcf"
        )
        _add_facts(
            db,
            company,
            {
                "revenue": 1000, "free_cash_flow": 120, "revenue_growth": 0.07,
                "shares_diluted": 100, "net_debt": 200,
                "production_volume": 10, "cash_cost_per_unit": 50,
                "realized_commodity_price": 80, "effective_tax_rate": 0.25,
                "commodity_earnings_multiple": 8,
                "holding_company_discount": 0.12,
                "segment_alpha_operating_metric": 80,
                "segment_alpha_valuation_multiple": 12,
                "segment_beta_operating_metric": 500,
                "segment_beta_valuation_multiple": 1.1,
            },
        )
        _add_price(db, company, 15)
        _add_traceable_wacc(db, company)
        service = ValuationService()
        results = {}
        # DCF estándar con los facts base.
        results["standard_dcf"] = service.value_company(db, company)
        # SOTP con los mismos facts (segmentos + descuento).
        company.company_type = "multi_segment"
        company.valuation_model = "sotp"
        company.factor_tags = ["sotp"]
        results["sotp"] = service.value_company(db, company)
        # Commodity con los mismos facts (volumen/coste/precio).
        company.company_type = "mining"
        company.valuation_model = "commodity_cycle"
        company.factor_tags = ["commodities"]
        results["commodity"] = service.value_company(db, company)

        expected = {}
        for key, result in results.items():
            assert result["status"] == "ok", (key, result["status"])
            _assert_range_and_sensitivity(result, key)
            expected[key] = result["expected_value"]
            # as_of: todos los periodos del trace son FY2025.
            periods = list((result["trace"].get("periods") or {}).values())
            snapshot_as_of = (result["trace"].get("snapshot") or {}).get("as_of")
            if snapshot_as_of is not None:
                periods.append(snapshot_as_of)
            assert periods, key
            assert all(p == PERIOD for p in periods), (key, periods)
            # Margen de seguridad consistente con precio 15.
            mos = result["margin_of_safety"]
            assert mos is not None, key
            assert abs(mos - ((result["expected_value"] - 15) / result["expected_value"])) < 1e-9, key

        # Mismo orden de magnitud entre motores (ratio < 50x).
        assert max(expected.values()) / min(expected.values()) < 50, expected
        assert all(v > 0 for v in expected.values()), expected
    finally:
        _cleanup(db, [ticker])
        db.close()


def test_edge_negative_earnings_refused_not_sign_flipped():
    """Un margen FCF negativo conocido NO se convierte en positivo.

    Antes el motor acotaba el margen a [1%, 50%], asi que una empresa que
    quema caja (FCF -80 sobre revenue 1000, margen real -8%) se valoraba con
    un margen del +1% y devolvia un fair value positivo. El DCF FCFF no puede
    representar un FCF negativo, asi que el resultado correcto es negarse.
    """
    init_db()
    db = SessionLocal()
    tickers = ["NEGFCFA", "NEGFCFB"]
    try:
        company_a = _make_company(
            db, "NEGFCFA", company_type="standard", valuation_model="standard_dcf"
        )
        _add_facts(
            db, company_a,
            {"revenue": 1000, "free_cash_flow": -80, "shares_diluted": 100,
             "net_debt": 100},
        )
        company_b = _make_company(
            db, "NEGFCFB", company_type="standard", valuation_model="standard_dcf"
        )
        _add_facts(
            db, company_b,
            {"revenue": 1000, "fcf_margin": -0.05, "shares_diluted": 100,
             "net_debt": 100},
        )
        for ticker in tickers:
            company = db.scalar(select(Company).where(Company.ticker == ticker))
            result = ValuationService().value_company(db, company)
            assert result["status"] == "insufficient_data", (ticker, result["status"])
            assert "non_negative_fcf_margin" in result["missing_inputs"], ticker
            # No se publica ningun valor: ni positivo (inventado) ni negativo.
            for field in ("bear_value", "base_value", "bull_value", "expected_value"):
                assert result[field] is None, (ticker, field, result[field])
    finally:
        _cleanup(db, tickers)
        db.close()


def test_edge_net_cash_increases_equity_value():
    """Caja neta (net_debt negativo) suma a equity de forma lineal."""
    init_db()
    db = SessionLocal()
    tickers = ["NETCASHN", "NETCASHP"]
    try:
        facts = {"revenue": 1000, "free_cash_flow": 150, "revenue_growth": 0.07,
                 "shares_diluted": 100}
        company_n = _make_company(
            db, "NETCASHN", company_type="standard", valuation_model="standard_dcf"
        )
        _add_facts(db, company_n, {**facts, "net_debt": -300})
        company_p = _make_company(
            db, "NETCASHP", company_type="standard", valuation_model="standard_dcf"
        )
        _add_facts(db, company_p, {**facts, "net_debt": 300})
        _add_traceable_wacc(db, company_n)
        _add_traceable_wacc(db, company_p)
        service = ValuationService()
        result_n = service.value_company(
            db, db.scalar(select(Company).where(Company.ticker == "NETCASHN"))
        )
        result_p = service.value_company(
            db, db.scalar(select(Company).where(Company.ticker == "NETCASHP"))
        )
        assert result_n["status"] == "ok" and result_p["status"] == "ok"
        # Δequity/acc = -Δnet_debt / acciones = 600 / 100 = 6.0 exacto.
        assert abs((result_n["base_value"] - result_p["base_value"]) - 6.0) < 1e-6
        assert result_n["trace"]["scenarios"]["base"]["trace"]["inputs"]["net_debt"] == -300
    finally:
        _cleanup(db, tickers)
        db.close()


def test_edge_pre_revenue_without_revenue_is_insufficient():
    init_db()
    db = SessionLocal()
    ticker = "NOREV"
    try:
        company = _make_company(
            db, ticker, company_type="pre_revenue",
            valuation_model="probability_weighted_scenarios",
            factor_tags=["pre_fcf", "speculative"],
        )
        _add_facts(
            db, company,
            {"shares_diluted": 50, "cash_and_equivalents": 100},
        )
        result = ValuationService().value_company(db, company)
        assert result["status"] == "insufficient_data"
        assert result["publishable"] is False
        assert result["bear_value"] is None
        assert result["base_value"] is None
        assert result["bull_value"] is None
        assert result["expected_value"] is None
        assert result["missing_inputs"]
        assert result["sensitivity"] == {"rows": []}
    finally:
        _cleanup(db, [ticker])
        db.close()


def test_edge_minorities_and_preferred_are_subtracted_from_equity():
    """Puente de equity completo: EV - deuda neta - minoritarios - preferentes
    (Damodaran, *Investment Valuation*, cap. 16; CFA Level II, FCFF -> equity).

    Mismas cifras con y sin 150 de intereses minoritarios y 50 de preferentes:
    a mano, el valor por accion baja exactamente (150 + 50) / 100 acciones = 2,0.
    """
    init_db()
    db = SessionLocal()
    tickers = ["BRIDGEA", "BRIDGEB"]
    try:
        facts = {"revenue": 1000, "free_cash_flow": 150, "revenue_growth": 0.07,
                 "shares_diluted": 100, "net_debt": 300}
        plain = _make_company(db, "BRIDGEA", company_type="standard", valuation_model="standard_dcf")
        _add_facts(db, plain, facts)
        claims = _make_company(db, "BRIDGEB", company_type="standard", valuation_model="standard_dcf")
        _add_facts(db, claims, {**facts, "minority_interest": 150, "preferred_stock": 50})
        _add_traceable_wacc(db, plain)
        _add_traceable_wacc(db, claims)
        service = ValuationService()
        result_a = service.value_company(db, db.scalar(select(Company).where(Company.ticker == "BRIDGEA")))
        result_b = service.value_company(db, db.scalar(select(Company).where(Company.ticker == "BRIDGEB")))
        assert result_a["status"] == "ok" and result_b["status"] == "ok"
        assert abs((result_a["base_value"] - result_b["base_value"]) - 2.0) < 1e-6
        inputs = result_b["trace"]["scenarios"]["base"]["trace"]["inputs"]
        assert inputs["minority_interest"] == 150
        assert inputs["preferred_stock"] == 50
    finally:
        _cleanup(db, tickers)
        db.close()
