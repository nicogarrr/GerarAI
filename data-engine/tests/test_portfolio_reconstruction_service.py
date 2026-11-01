"""Reconstruccion del valor diario desde el libro de operaciones."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, Portfolio, Position, Transaction
from app.services.portfolio_reconstruction_service import PortfolioReconstructionService

D0 = date(2026, 9, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        session.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        session.commit()
        yield session


def _company(db, ticker="AAA"):
    company = Company(
        ticker=ticker, name=ticker, exchange="X", currency="EUR", sector="T", industry="I",
        company_type="holding", valuation_model="unassigned", special_sources=[],
        special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _price(db, company, day, close):
    db.add(MarketPrice(company_id=company.id, date=day, close=Decimal(str(close)), adj_close=Decimal(str(close)), source="t"))


def _tx(db, company, day, action, qty, price, fees="0"):
    db.add(Transaction(
        company_id=company.id, trade_date=day, action=action, quantity=Decimal(qty),
        price=Decimal(price), fees=Decimal(fees), currency="EUR", raw_payload={},
    ))


def _position(db, company, qty, value="1"):
    db.add(Position(company_id=company.id, quantity=Decimal(qty), currency="EUR",
                    market_value=Decimal(value), market_value_base=Decimal(value), as_of=D0))


def test_buy_flow_is_not_counted_as_return(db):
    a = _company(db)
    _tx(db, a, D0, "buy", "10", "10")
    _tx(db, a, D0 + timedelta(days=2), "buy", "10", "11")
    for offset, close in enumerate([10, 10, 11, 12]):
        _price(db, a, D0 + timedelta(days=offset), close)
    _position(db, a, "20", "240")
    db.commit()

    result = PortfolioReconstructionService().build(db)

    assert result.status == "ok"
    # dia 3: valor 20*11=220, flujo +110 (compra 10x11), previo 100 -> 220-110=110 -> +10 %
    assert result.returns[D0 + timedelta(days=2)] == pytest.approx(0.10)
    assert result.returns[D0 + timedelta(days=3)] == pytest.approx(12 / 11 - 1)
    assert result.twr == pytest.approx(1.1 * (12 / 11) - 1)
    assert result.usable


def test_end_value_mismatch_is_declared_and_not_usable(db):
    a = _company(db)
    _tx(db, a, D0, "buy", "10", "10")
    for offset, close in enumerate([10, 11, 12]):
        _price(db, a, D0 + timedelta(days=offset), close)
    _position(db, a, "10", "200")  # valor guardado 200 vs reconstruido 120
    db.commit()
    result = PortfolioReconstructionService().build(db)
    assert result.status == "end_value_mismatch"
    assert not result.usable


def test_day_without_close_is_excluded_not_filled(db):
    a = _company(db)
    _tx(db, a, D0, "buy", "10", "10")
    _price(db, a, D0, 10)
    _price(db, a, D0 + timedelta(days=1), 11)
    _price(db, a, D0 + timedelta(days=3), 12)
    _position(db, a, "10")
    b = _company(db, "BBB")
    _tx(db, b, D0 + timedelta(days=1), "buy", "1", "5")
    _price(db, b, D0 + timedelta(days=3), 5)
    _position(db, b, "1")
    db.commit()

    result = PortfolioReconstructionService().build(db)

    assert [row["date"] for row in result.series] == [D0.isoformat(), (D0 + timedelta(days=3)).isoformat()]
    assert result.excluded_days[0]["date"] == (D0 + timedelta(days=1)).isoformat()
    assert "BBB" in result.excluded_days[0]["reason"]


def test_negative_opening_quantity_is_declared(db):
    a = _company(db)
    _tx(db, a, D0, "buy", "10", "10")
    _price(db, a, D0, 10)
    _position(db, a, "7")
    db.commit()
    assert PortfolioReconstructionService().build(db).status == "negative_opening_quantity"


def test_opening_quantity_is_derived_from_position_minus_ledger(db):
    a = _company(db)
    _tx(db, a, D0 + timedelta(days=1), "sell", "4", "11")
    for offset, close in enumerate([10, 11, 12]):
        _price(db, a, D0 + timedelta(days=offset), close)
    _position(db, a, "6", "72")
    db.commit()
    result = PortfolioReconstructionService().build(db)
    assert result.quantity_check[0]["opening_derived"] == 10.0
    assert result.status == "ok"
    assert [row["value_base"] for row in result.series] == [100.0, 66.0, 72.0]


def test_fx_lookup_is_once_per_currency_and_day_not_per_position(db, monkeypatch):
    """Antes: un ``rate_from_table`` por posicion y dia (N x dias); ahora uno por divisa y dia."""
    from app.services.portfolio_fx_service import PortfolioFXService

    companies = [_company(db, f"C{i}") for i in range(5)]
    days = 20
    for company in companies:
        _tx(db, company, D0, "buy", "10", "10")
        for offset in range(days):
            _price(db, company, D0 + timedelta(days=offset), 10 + offset * 0.1)
        _position(db, company, "10", str(10 * (10 + (days - 1) * 0.1)))
    db.commit()
    calls = {"n": 0}
    real = PortfolioFXService.rate_from_table

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(PortfolioFXService, "rate_from_table", staticmethod(counting))
    result = PortfolioReconstructionService().build(db)

    assert result.status == "ok" and result.usable
    # 20 dias x 1 divisa + 5 flujos de compra (antes 5 x 20 + 5 = 105).
    assert calls["n"] <= days + len(companies)


def test_normalize_currency_is_memoized_and_unchanged():
    from app.valuation.currency import normalize_currency

    assert normalize_currency("GBp") == ("GBP", 100)
    assert normalize_currency(" usd ") == ("USD", 1)
    assert normalize_currency(None) == (None, 1)
    assert normalize_currency("") == (None, 1)
    assert getattr(normalize_currency, "cache_info", None) is not None


def test_applied_split_does_not_fabricate_a_boundary_crash(db):
    """Split 2:1 aplicado (patas ya reescritas en terminos post-split por
    corporate_actions_service): los cierres crudos anteriores al split deben
    dividirse por el ratio o la serie vale el doble antes del split y la TWR
    inventa un -50 % en la frontera."""
    from app.models.entities import CorporateAction

    a = _company(db)
    # Pata YA ajustada por apply_action (cantidad x2, precio /2, fecha intacta).
    _tx(db, a, D0, "buy", "20", "50")
    _price(db, a, D0, 100)          # cierres crudos (sin ajustar por el split)
    _price(db, a, D0 + timedelta(days=1), 100)
    _price(db, a, D0 + timedelta(days=2), 50)   # split efectivo aqui
    _price(db, a, D0 + timedelta(days=3), 52)
    db.add(CorporateAction(
        company_id=a.id, action_type="split", ratio=Decimal("2"),
        effective_date=D0 + timedelta(days=2), applied=True, source="t",
    ))
    _position(db, a, "20", "1040")
    db.commit()

    result = PortfolioReconstructionService().build(db)

    assert result.status == "ok"
    # En terminos post-split la cartera vale 1000-1000-1000-1040: sin salto.
    assert [row["value_base"] for row in result.series] == [1000.0, 1000.0, 1000.0, 1040.0]
    assert result.returns[D0 + timedelta(days=2)] == pytest.approx(0.0)
    assert result.returns[D0 + timedelta(days=3)] == pytest.approx(0.04)
    assert result.twr == pytest.approx(0.04)


def test_unapplied_split_keeps_raw_closes_and_quantities(db):
    """Split ingerido pero NO aplicado (patas en terminos pre-split): ajustar
    los precios romperia la coherencia; la serie sigue en terminos crudos."""
    from app.models.entities import CorporateAction

    a = _company(db)
    _tx(db, a, D0, "buy", "10", "100")
    _price(db, a, D0, 100)
    _price(db, a, D0 + timedelta(days=1), 100)
    _price(db, a, D0 + timedelta(days=2), 50)
    _price(db, a, D0 + timedelta(days=3), 52)
    db.add(CorporateAction(
        company_id=a.id, action_type="split", ratio=Decimal("2"),
        effective_date=D0 + timedelta(days=2), applied=False, source="t",
    ))
    _position(db, a, "10", "520")
    db.commit()

    result = PortfolioReconstructionService().build(db)

    # Sin ajuste: la serie es la cruda (1000-1000-500-520); el -50 % del split
    # sin aplicar es visible y real para este libro (cantidad sin reescalar).
    assert [row["value_base"] for row in result.series] == [1000.0, 1000.0, 500.0, 520.0]
