"""P1 QA prod (AAPL): serie de acciones diluidas sin ajustar por splits y
base de Ingresos del DCF tomada de un trimestre viejo.

AAPL FY2016 reporto 5,5B de acciones diluidas (pre-split 4:1 de 2020-08-28);
la SEC no reexpone 2016 en los 10-K posteriores, asi que sin ajuste la serie
2016-2025 (5,5B -> 15,3B) finge dilucion +11,8 % anual cuando la realidad es
recompra neta (22B -> 15,3B en acciones actuales). Y un hecho trimestral con
fiscal_year puesto pero sin marca FY (import legado) podia pisar el 10-K del
ano y sembrar el DCF con 117,2B en vez de los 416,16B del FY2025.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, CorporateAction, FinancialFact, Position
from app.services.long_term_model_service import LongTermModelService

TICKER = "SPLT"


def _fact(db, company, metric, value, year, *, quarter="FY", period=None):
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit="shares" if metric.startswith("shares") else "USD",
            period=period or f"{year}-09-30:FY",
            fiscal_year=year,
            fiscal_quarter=quarter,
            source_type="test_split_adjustment",
            is_reported=True,
            confidence=Decimal("0.95"),
        )
    )


def _company(db):
    company = Company(
        ticker=TICKER, name="Split Test Co", exchange="TEST", currency="USD",
        sector="Tech", industry="Software", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=["quality"],
    )
    db.add(company)
    db.flush()
    db.add(Position(company_id=company.id, market_price=Decimal("200")))
    return company


def _setup():
    init_db()
    db = SessionLocal()
    old = db.scalar(select(Company).where(Company.ticker == TICKER))
    if old:
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == old.id))
        db.execute(delete(CorporateAction).where(CorporateAction.company_id == old.id))
        db.execute(delete(Position).where(Position.company_id == old.id))
        db.delete(old)
        db.commit()
    return db


def test_shares_series_adjusted_by_cumulative_split_factor():
    db = _setup()
    try:
        company = _company(db)
        # Serie estilo AAPL en unidades ORIGINALES de cada epoca:
        for year, revenue, fcf, shares in [
            (2016, 215_600_000_000, 53_000_000_000, 5_500_000_000),
            (2017, 229_200_000_000, 51_000_000_000, 5_250_000_000),
            (2023, 383_300_000_000, 99_600_000_000, 15_800_000_000),
            (2024, 391_000_000_000, 108_800_000_000, 15_400_000_000),
            (2025, 416_160_000_000, 110_000_000_000, 15_100_000_000),
        ]:
            _fact(db, company, "revenue", revenue, year)
            _fact(db, company, "free_cash_flow", fcf, year)
            _fact(db, company, "shares_diluted", shares, year)
        db.add(CorporateAction(
            company_id=company.id, action_type="split",
            effective_date=date(2020, 8, 31), ratio=Decimal("4"),
            description="4:1", source="test",
        ))
        db.commit()

        model = LongTermModelService().build(db, company)

        history = {row["fiscal_year"]: row for row in model["historical_review"]["rows"]}
        sh16 = history[2016]["metrics"]["shares_diluted"]
        assert sh16["value"] == 22_000_000_000  # 5,5B x 4 (unidades actuales)
        assert "split" in (sh16["calculation"] or "")
        assert history[2025]["metrics"]["shares_diluted"]["value"] == 15_100_000_000
        cagr = model["assumptions"]["shares_cagr"]["value"]
        assert cagr is not None and cagr < 0  # recompra neta, no +11,8 %
    finally:
        db.close()


def test_dcf_revenue_base_prefers_fy_marked_over_stray_quarter():
    db = _setup()
    try:
        company = _company(db)
        for year, revenue, fcf, shares in [
            (2023, 383_300_000_000, 99_600_000_000, 15_800_000_000),
            (2024, 391_000_000_000, 108_800_000_000, 15_400_000_000),
            (2025, 416_160_000_000, 110_000_000_000, 15_100_000_000),
        ]:
            _fact(db, company, "revenue", revenue, year)
            _fact(db, company, "free_cash_flow", fcf, year)
            _fact(db, company, "shares_diluted", shares, year)
        db.flush()
        # Fila trimestral legada (fiscal_year puesto, sin marca FY) ingerida
        # DESPUES del 10-K: nunca debe ser la base de Ingresos.
        _fact(db, company, "revenue", 117_200_000_000, 2025,
              quarter=None, period="2022-12-31")
        db.commit()

        model = LongTermModelService().build(db, company)

        history = {row["fiscal_year"]: row for row in model["historical_review"]["rows"]}
        assert history[2025]["metrics"]["revenue"]["value"] == 416_160_000_000
        assert model["historical_review"]["last_year"] == 2025
        # La base de Ingresos del modelo (current snapshot = ultimo FY) es el
        # FY2025 del 10-K, nunca el trimestre viejo:
        assert model["current_snapshot"]["metrics"]["revenue"]["value"] == 416_160_000_000
    finally:
        db.close()
