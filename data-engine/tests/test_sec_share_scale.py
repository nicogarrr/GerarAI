"""Recuentos de acciones SEC declarados en miles y BPA con la escala rota.

Casos reales (prod, 4-nov-2026), reducidos a lo esencial y sin tickers en el
codigo: un emisor etiqueta la media ponderada diluida en MILES en su 10-K
(221.769 frente a 380,8 M en la portada dei) y otro arrastra un BPA de
17,6 M $ de un 10-Q antiguo. Ambos daban valores por accion absurdos
(motor relativo: 3.519 $ frente a 5,28 $; 4,6e8 $ frente a 35,6 $).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FinancialFact
from app.valuation.engines.base import snapshot_trace
from app.valuation.fact_reference import latest_facts
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from app.valuation.share_scale import per_share_scale_is_wrong, share_scale_factor


def test_share_scale_factor_detects_thousands_and_millions():
    assert share_scale_factor(221_769, 380_763_481) == 1_000.0
    assert share_scale_factor(69_917, 93_173_191) == 1_000.0
    assert share_scale_factor(380.0, 380_763_481) == 1_000_000.0
    # Ampliaciones reales de capital (x1,4 / x3) no son escala.
    assert share_scale_factor(52_700_000, 69_917_000) == 1.0
    assert share_scale_factor(100_000_000, 300_000_000) == 1.0
    # Solo hacia arriba: si la referencia es la pequena, no se toca el valor.
    assert share_scale_factor(380_763_481, 380_763) == 1.0
    assert share_scale_factor(None, 1.0) == 1.0
    assert share_scale_factor(0.0, 1.0) == 1.0


def test_per_share_scale_is_wrong():
    assert per_share_scale_is_wrong(17_600_000.0, -24_405_000.0, 51_000_000.0)
    assert not per_share_scale_is_wrong(-1.34, -341_940_000.0, 255_982_592.0)
    assert not per_share_scale_is_wrong(74.33, 84_969_000_000.0, 1_143_000_000.0)
    assert not per_share_scale_is_wrong(1.0, None, 1.0)


def _db() -> tuple[Session, Company]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = "tenant-test"
    company = Company(
        ticker="THOU", name="Thousands Co", currency="USD", exchange="NASDAQ",
        sector="Tech", industry="Software", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return db, company


def _fact(db, company, metric, value, period, *, fy=None, fq=None, unit="USD", filed=None):
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
        period=period, fiscal_year=fy, fiscal_quarter=fq, filed=filed,
        source_type="SEC", is_reported=True, confidence=Decimal("1"),
    ))


def _thousands_company() -> tuple[Session, Company]:
    db, company = _db()
    for year, shares, outstanding, revenue in (
        (2023, 52_700_000, 70_000_000, 15_000_000),
        (2024, 69_917, 93_173_191, 25_000_000),
        (2025, 221_769, 380_763_481, 50_731_000),
    ):
        period = f"{year}-12-31:FY"
        filed = date(year + 1, 3, 30)
        _fact(db, company, "shares_diluted", shares, period, fy=year, fq="FY", unit="shares", filed=filed)
        _fact(db, company, "shares_outstanding", outstanding, period, fy=year, fq="FY", unit="shares", filed=filed)
        _fact(db, company, "revenue", revenue, period, fy=year, fq="FY", filed=filed)
        _fact(db, company, "free_cash_flow", revenue * 0.1, period, fy=year, fq="FY", filed=filed)
        _fact(db, company, "net_debt", -500_000_000, period, fy=year, fq="FY", filed=filed)
    db.commit()
    return db, company


def test_latest_facts_rescales_shares_reported_in_thousands_with_reference():
    db, company = _thousands_company()
    try:
        shares = latest_facts(db, company.id, ["shares_diluted"])["shares_diluted"]
        assert shares.value == 221_769_000.0
        trace = shares.as_trace()["share_scale"]
        assert trace["factor"] == 1_000.0
        assert trace["reference_metric"] == "shares_outstanding"
        assert trace["reference_period"] == "2025-12-31:FY"
        assert "miles" in trace["method"]
    finally:
        db.close()


def test_latest_facts_leaves_correct_share_counts_alone():
    db, company = _db()
    try:
        _fact(db, company, "shares_diluted", 1_143_000_000, "2026-09-03:FY", fy=2026, fq="FY", unit="shares")
        _fact(db, company, "shares_outstanding", 1_131_000_000, "2026-09-03:FY", fy=2026, fq="FY", unit="shares")
        db.commit()
        shares = latest_facts(db, company.id, ["shares_diluted"])["shares_diluted"]
        assert shares.value == 1_143_000_000.0
        assert "share_scale" not in shares.as_trace()
    finally:
        db.close()


def test_snapshot_rescales_diluted_shares_and_traces_the_reference():
    db, company = _thousands_company()
    try:
        snapshot = FinancialSnapshotBuilder().build(db, company)
        assert snapshot.value("shares_diluted") == 221_769_000.0
        trace = snapshot_trace(snapshot)
        assert trace["share_scale"]["shares_diluted"]["factor"] == 1_000.0
        assert any("miles" in w for w in snapshot.warnings)
    finally:
        db.close()


def test_snapshot_point_in_time_does_not_use_a_later_filing_as_reference():
    db, company = _db()
    try:
        _fact(db, company, "shares_diluted", 221_769, "2025-12-31:FY", fy=2025, fq="FY",
              unit="shares", filed=date(2026, 3, 30))
        _fact(db, company, "shares_outstanding", 380_763_481, "2026-03-31:DEI",
              unit="shares", filed=date(2026, 5, 15))
        db.commit()
        rows = db.query(FinancialFact).filter(FinancialFact.metric == "shares_diluted").all()
        from app.valuation.fact_reference import detect_share_scale

        assert detect_share_scale(db, company.id, rows[0], filed_not_after=date(2026, 4, 1)) is None
        scale = detect_share_scale(db, company.id, rows[0])
        assert scale is not None and scale.factor == 1_000.0
    finally:
        db.close()


def test_latest_facts_skips_an_eps_with_broken_scale():
    db, company = _db()
    try:
        # BPA antiguo con la escala rota, guardado sin fiscal_year (ultimo por
        # created_at) y uno posterior plausible.
        _fact(db, company, "net_income", -24_405_000, "2020-12-31:FY", fy=2020, fq="FY")
        _fact(db, company, "shares_diluted", 51_000_000, "2021-12-31:FY", fy=2021, fq="FY", unit="shares")
        _fact(db, company, "eps_diluted", -0.39, "2021-06-30:Q2", unit="USD/share")
        db.commit()
        _fact(db, company, "eps_diluted", 17_600_000, "2020-03-31:Q1", unit="USD/share")
        db.commit()
        eps = latest_facts(db, company.id, ["eps_diluted"])["eps_diluted"]
        assert eps.value == -0.39
    finally:
        db.close()
