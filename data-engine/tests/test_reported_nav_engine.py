"""NAV publicado para entidades de inversion (CGEO.L y similares)."""

from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact
from app.valuation.engines.registry import resolve_engine_key
from app.valuation.engines.sotp_engine import SOTPEngine, is_reported_nav_entity


def _company(db, ticker, *, company_type="research_candidate", facts):
    existing = db.scalar(select(Company).where(Company.ticker == ticker))
    if existing:
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == existing.id))
        db.delete(existing)
        db.commit()
    company = Company(
        ticker=ticker, name="NAV test", exchange="LSE", currency="GBP",
        sector="Financial Services", industry="Asset Management",
        company_type=company_type, valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    for metric, (value, year) in facts.items():
        db.add(FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit="GEL",
            period=f"FY{year}", fiscal_year=year, fiscal_quarter="FY",
            source_type="nav_engine_test", confidence=Decimal("0.9"),
        ))
    db.commit()
    return company


def _context(db, company, price=None):
    engine = SOTPEngine()
    return engine, engine.build_context(db, company, price, None)


def test_cgeo_se_valora_por_nav_no_por_dcf():
    company = Company(ticker="CGEO.L", company_type="research_candidate", valuation_model="standard_dcf")
    assert resolve_engine_key(company) == "holding_company"
    assert is_reported_nav_entity(company)
    assert is_reported_nav_entity(Company(ticker="XYZ.L", company_type="investment_trust"))
    assert not is_reported_nav_entity(Company(ticker="AAPL", company_type="ai_big_tech"))


def test_nav_publicado_por_accion_con_cifras_del_informe_2025():
    init_db()
    db = SessionLocal()
    try:
        company = _company(db, "CGEO.L", facts={
            "total_equity": (5194527000, 2025),
            "shares_diluted": (35029723, 2025),
        })
        engine, context = _context(db, company)
        result = engine.value(context)
        assert result["status"] == "ok"
        nav_ps = 5194527000 / 35029723
        assert abs(result["trace"]["reported_nav"]["nav_per_share"] - nav_ps) < 1e-6
        assert abs(result["base_value"] - nav_ps) < 1e-6
        assert result["bear_value"] < result["base_value"] < result["bull_value"]
        assert result["trace"]["holding_discount_source"] == "none_reported_nav_at_par"
        assert result["trace"]["fact_ids"]["total_equity"] is not None
    finally:
        db.rollback()
        db.close()


def test_nav_aplica_descuento_holding_si_hay_hecho():
    init_db()
    db = SessionLocal()
    try:
        company = _company(db, "NAVDISC", company_type="investment_trust", facts={
            "total_equity": (1000, 2025), "shares_diluted": (10, 2025),
            "holding_company_discount": (0.2, 2025),
        })
        engine, context = _context(db, company)
        result = engine.value(context)
        assert result["status"] == "ok"
        assert abs(result["base_value"] - 80.0) < 1e-9
        assert result["trace"]["holding_discount_source"] == "financial_facts"
    finally:
        db.rollback()
        db.close()


def test_nav_y_acciones_de_ejercicios_distintos_no_se_dividen():
    init_db()
    db = SessionLocal()
    try:
        company = _company(db, "NAVMIX", company_type="investment_trust", facts={
            "total_equity": (1000, 2025), "shares_diluted": (10, 2023),
        })
        engine, context = _context(db, company)
        result = engine.value(context)
        assert result["status"] != "ok"
        assert "consistent_nav_and_shares_period" in result["missing_inputs"]
    finally:
        db.rollback()
        db.close()


def test_sin_nav_cae_al_contrato_sotp_que_declara_lo_que_falta():
    init_db()
    db = SessionLocal()
    try:
        company = _company(db, "NAVNONE", company_type="investment_trust", facts={
            "shares_diluted": (10, 2025),
        })
        engine, context = _context(db, company)
        result = engine.value(context)
        assert result["status"] != "ok"
        assert "net_debt" in result["missing_inputs"]
    finally:
        db.rollback()
        db.close()
