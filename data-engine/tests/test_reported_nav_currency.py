"""NAV publicado en una divisa y precio en otra (PSH.L: NAV en USD, cotiza en GBp).

El filtro de divisa del servicio solo miraba el snapshot. Una entidad de
inversion sin hechos monetarios en el snapshot dejaba el filtro en "unknown" y
el NAV en USD se comparaba con el precio en libras sin convertir.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, FinancialFact, FXRate, MarketPrice, Tenant
from app.services import valuation_service
from app.services.valuation_service import ValuationService
from app.valuation.engines.sotp_engine import SOTPEngine

PRICE_DAY = date(2026, 10, 23)
EUR_USD = Decimal("1.16")
EUR_GBP = Decimal("0.87")


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(valuation_service, "resolve", lambda _company: SOTPEngine())
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _ecb(db: Session, rates: dict[str, Decimal]) -> None:
    for quote, eur_quote in rates.items():
        db.add(FXRate(base_currency="EUR", quote_currency=quote, rate=Decimal(1) / eur_quote,
                      rate_date=PRICE_DAY, source="ECB"))


def _psh(db: Session, *, nav_unit: str = "USD") -> Company:
    company = Company(ticker="PSH.L", name="Pershing Square Holdings", exchange="LSE", currency="GBP",
                      company_type="investment_trust", valuation_model="holding_company", factor_tags=[])
    db.add(company)
    db.flush()
    for metric, value, unit in (
        ("total_equity", 1_000_000_000, nav_unit),
        ("shares_diluted", 10_000_000, "shares"),
    ):
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit=unit,
                             period="FY2025", fiscal_year=2025, fiscal_quarter="FY",
                             source_type="test", confidence=Decimal("0.9")))
    # 4.000 peniques = 40,00 GBP.
    db.add(MarketPrice(company_id=company.id, date=PRICE_DAY, open=Decimal(4000), high=Decimal(4000),
                       low=Decimal(4000), close=Decimal(4000), source="test", quote_currency="GBp"))
    db.commit()
    return company


def test_nav_en_usd_se_compara_con_el_precio_convertido(db: Session) -> None:
    _ecb(db, {"USD": EUR_USD, "GBP": EUR_GBP})
    company = _psh(db)

    result = ValuationService().value_company(db, company)

    # NAV 1.000 M USD / 10 M acciones = 100 USD; 1 USD = 0,87/1,16 = 0,75 GBP -> 75 GBP.
    # Precio 40 GBP. MOS = (75 - 40) / 75 = 46,67 %. Antes: 100 "GBP" y 60 %.
    assert result["trace"]["method"] == "reported_nav"
    assert result["currency"]["status"] == "converted"
    assert result["currency"]["reporting_currency"] == "USD"
    assert result["value_currency"] == "GBP"
    assert result["base_value"] == pytest.approx(75.0)
    assert result["current_price"] == pytest.approx(40.0)
    # El MOS va sobre el valor esperado (escenarios), ya en GBP: invariante a la divisa.
    expected = result["expected_value"]
    assert 70 < expected < 80
    assert result["margin_of_safety"] == pytest.approx((expected - 40) / expected)


def test_nav_sin_tipo_de_cambio_es_nd(db: Session) -> None:
    # CGEO.L publica el NAV en GEL y el BCE no da GEL: N/D, nunca 148 GEL frente a 40 GBP.
    _ecb(db, {"USD": EUR_USD, "GBP": EUR_GBP})
    company = _psh(db, nav_unit="GEL")

    result = ValuationService().value_company(db, company)

    assert result["currency"]["status"] == "blocked"
    assert result["base_value"] is None
    assert result["margin_of_safety"] is None
    assert result["value_currency"] is None
