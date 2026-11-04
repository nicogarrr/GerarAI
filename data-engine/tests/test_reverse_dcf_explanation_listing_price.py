"""El DCF inverso explica el precio en la divisa del listado, no en la de las cuentas.

Con capex normalizado o DCF multietapa, el DCF inverso trae un texto
(``explanation_es``: «El precio de X descuenta un crecimiento…») que la ficha
de research y la tesis muestran tal cual. El servicio traduce el precio a la
divisa de las cuentas para valorar y luego reescala los importes por acción a
la divisa del listado (``scale_per_share_outputs``), pero el texto se quedaba
con el precio traducido: una empresa que cotiza en euros y reporta en dólares
decía «El precio de 178,34» cuando su cotización es 153,74 €. Pasa con
cualquier empresa cuya divisa de cuentas no sea la del listado (británicas que
reportan en US$ y cotizan en libras, europeas con 20-F, ADR…).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import FXRate, MarketPrice
from app.models.entities import Base
from app.services.valuation_service import ValuationService
from app.valuation.currency import scale_per_share_outputs
from app.valuation.engines.standard_dcf import StandardDCFEngine
from app.valuation.normalized_fcf import _num_es
from tests.test_valgrandes_normalized_fcf import PLTR, M, _seed

EUR_PER_USD = 1 / 1.16


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _reverse_text(result: dict) -> str:
    text = result["reverse_dcf"]["explanation_es"]
    assert isinstance(text, str) and text
    return text


def test_scale_per_share_outputs_rewrites_the_price_in_the_reverse_explanation(db):
    company = _seed(db, "PLTRY", PLTR, shares=2_565.2 * M, net_debt=-6_000 * M, price=178.34, wacc=0.1204)
    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 178.34))
    assert "El precio de 178,34 " in _reverse_text(result)

    scale_per_share_outputs(result, EUR_PER_USD)

    listed = _num_es(178.34 * EUR_PER_USD, 2)
    text = _reverse_text(result)
    assert result["reverse_dcf"]["market_price"] == pytest.approx(178.34 * EUR_PER_USD)
    assert f"El precio de {listed} " in text
    assert "178,34" not in text
    # Las tasas (crecimiento, margen, WACC) no cambian con la divisa.
    assert "descuenta un crecimiento de ingresos" in text


def test_scale_without_reverse_text_is_unchanged():
    result = {"reverse_dcf": {"market_price": 10.0, "solved_value_per_share": 12.0}}
    scale_per_share_outputs(result, 2.0)
    assert result["reverse_dcf"] == {"market_price": 20.0, "solved_value_per_share": 24.0}


def test_valuation_service_explains_the_listing_price_when_accounts_are_in_another_currency(db):
    # Cuentas en US$ (hechos de PLTR) y cotización en euros: el servicio
    # convierte el precio a dólares para el DCF y devuelve todo en euros.
    company = _seed(db, "PLTRE", PLTR, shares=2_565.2 * M, net_debt=-6_000 * M, price=153.74, wacc=0.1204)
    company.currency = "EUR"
    for price in db.scalars(select(MarketPrice).where(MarketPrice.company_id == company.id)):
        price.quote_currency = "EUR"
    db.add(
        FXRate(
            base_currency="EUR", quote_currency="USD", rate=Decimal(1) / Decimal("1.16"),
            rate_date=date(2026, 11, 3), source="ECB",
        )
    )
    db.commit()

    result = ValuationService().value_company(db, company)

    assert result["currency"]["status"] == "converted"
    assert result["current_price"] == pytest.approx(153.74)
    text = _reverse_text(result)
    assert "El precio de 153,74 " in text
    assert "178,3" not in text
