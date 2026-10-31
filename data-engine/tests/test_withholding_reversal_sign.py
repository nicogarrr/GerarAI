"""Reversion de retenciones IBKR: resta, no suma otra retencion.

IBKR Flex publica la retencion como importe NEGATIVO y su reversion como
POSITIVO (p. ej. -15, +15, -15 = 15 retenidos). Un abs() en el XIRR y en el
informe fiscal convertia la reversion en otra retencion: -45 en vez de -15.
La entrada manual guarda la retencion en positivo y no cambia.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Portfolio, Position, Transaction
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from app.services.tax_report_service import TaxReportService, withholding_cost

FLEX_WHT = {"type": "Withholding Tax", "currency": "EUR"}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str = "AAPL") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _row(price: str, payload: dict | None = None):
    return SimpleNamespace(price=Decimal(price), quantity=Decimal("1"), raw_payload=payload or {})


def test_withholding_cost_follows_the_source_sign_convention():
    # IBKR: negativo = retenido, positivo = reversion.
    assert withholding_cost(_row("-15", FLEX_WHT)) == Decimal("15")
    assert withholding_cost(_row("15", FLEX_WHT)) == Decimal("-15")
    # CSV canonico y notas manuales: el signo lo escribe el usuario.
    assert withholding_cost(_row("15", {"source": "ibkr_csv"})) == Decimal("15")
    assert withholding_cost(_row("15", {"notes": "retencion"})) == Decimal("15")
    # Manual / historico sin origen: valor absoluto, como antes.
    assert withholding_cost(_row("19")) == Decimal("19")
    assert withholding_cost(_row("-15")) == Decimal("15")


def test_tax_report_nets_ibkr_withholding_reversal(db):
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.commit()
    company = _company(db, "CCC")
    day = date(2026, 4, 1)
    rows = [("dividend", "100", {"type": "Dividends"})] + [
        ("withholding", price, FLEX_WHT) for price in ("-15", "15", "-15")
    ]
    for action, price, payload in rows:
        db.add(Transaction(
            company_id=company.id, trade_date=day, action=action,
            quantity=Decimal("1"), price=Decimal(price), currency="EUR",
            raw_payload=payload,
        ))
    db.commit()

    report = TaxReportService().compute_report(db, 2026)
    row = next(d for d in report["dividends"] if d["ticker"] == "CCC")
    assert row["dividends_base"] == 100.0
    assert row["withholding_base"] == 15.0


def test_xirr_ibkr_withholding_reversal_is_an_inflow(db, monkeypatch):
    """Compra -1.000, dividendo +100 y retenciones IBKR -15, +15, -15 (dia 184),
    valor final 1.000. Neto retenido 15 -> mismos flujos que una sola
    retencion: -1.000, +85, +1.000 -> XIRR = 8,8657 %. Con abs() eran -45.
    """
    today = date.today()

    import app.services.portfolio_intelligence_service as pi_module

    # El servicio fecha el valor final con local_today() (hoy en Madrid):
    # congelar ESA base. Parchear date.today ya no gobierna al servicio y en
    # CI (TZ=UTC) entre las 23:00 y 00:00 el valor final quedaba un dia por
    # delante de los flujos y el XIRR se movia lo suficiente para romper las
    # tolerancias.
    monkeypatch.setattr(pi_module, "local_today", lambda: today)
    company = _company(db)
    from app.services.portfolio_fx_service import PortfolioFXService

    portfolio = PortfolioFXService().ensure_portfolio(db)
    start = today - timedelta(days=365)
    mid = start + timedelta(days=184)
    db.add_all([
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id, trade_date=start,
            action="buy", quantity=Decimal("10"), price=Decimal("100"),
            currency="EUR", external_id="rev-buy",
        ),
        Transaction(
            portfolio_id=portfolio.id, company_id=company.id, trade_date=mid,
            action="dividend", quantity=Decimal("1"), price=Decimal("100"),
            currency="EUR", external_id="rev-div", raw_payload={"type": "Dividends"},
        ),
        *[
            Transaction(
                portfolio_id=portfolio.id, company_id=company.id, trade_date=mid,
                action="withholding", quantity=Decimal("1"), price=Decimal(price),
                currency="EUR", external_id=f"rev-wht-{index}", raw_payload=FLEX_WHT,
            )
            for index, price in enumerate(("-15", "15", "-15"))
        ],
    ])
    position = Position(
        portfolio_id=portfolio.id, company_id=company.id,
        quantity=Decimal("10"), market_price=Decimal("100"),
        market_value_base=Decimal("1000"), currency="EUR", as_of=today,
    )
    db.add(position)
    db.commit()

    xirr, meta = PortfolioIntelligenceService()._xirr(db, [(position, company)])
    assert meta["status"] == "calculated"
    assert xirr == pytest.approx(0.088657, abs=1e-5)
