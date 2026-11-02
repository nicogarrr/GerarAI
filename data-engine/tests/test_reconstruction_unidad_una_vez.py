"""Rendimiento: la reconstruccion resuelve la unidad de cotizacion una vez por empresa.

Antes ``price_in_currency`` recalculaba la unidad del listado en CADA cierre
(391.200 veces con 300 posiciones y 5 años: un tercio del tiempo de la
reconstruccion). La unidad depende de la empresa y de la unidad del cierre,
no del valor, asi que se resuelve una vez por par; el resultado no cambia.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.services import price_units
from app.services.portfolio_reconstruction_service import PortfolioReconstructionService
from tests.test_portfolio_reconstruction_service import (  # noqa: F401  (fixture db)
    D0,
    _company,
    _position,
    _price,
    _tx,
    db,
)


def test_unidad_del_listado_una_vez_por_empresa_y_mismos_retornos(db, monkeypatch):
    companies = [_company(db, f"C{i}") for i in range(5)]
    days = 20
    for company in companies:
        _tx(db, company, D0, "buy", "10", "10")
        for offset in range(days):
            _price(db, company, D0 + timedelta(days=offset), 10 + offset * 0.1)
        _position(db, company, "10", str(10 * (10 + (days - 1) * 0.1)))
    db.commit()
    calls = {"n": 0}
    real = price_units.listing_quote_unit

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(price_units, "listing_quote_unit", counting)
    result = PortfolioReconstructionService().build(db)

    assert result.status == "ok" and result.usable
    # Una resolucion por empresa (antes una por cierre: 5 x 20 = 100).
    assert calls["n"] == len(companies)
    # Cierre plano en EUR sobre EUR: +0,1 por dia sobre la base del dia previo.
    second = D0 + timedelta(days=1)
    assert result.returns[second] == pytest.approx(float(Decimal("10.1") / Decimal("10") - 1))


@pytest.mark.parametrize(
    ("quote", "target", "ticker", "listing"),
    [
        ("GBp", "GBP", "TSCO.L", "GBp"),
        ("GBP", "GBp", "TSCO.L", "GBp"),
        ("USD", "USD", "AAPL", "USD"),
        ("USD", "EUR", "AAPL", "USD"),
        (None, "USD", "AAPL", "USD"),
        (None, "GBP", "TSCO.L", "GBp"),
    ],
)
def test_factor_reproduce_price_in_currency(quote, target, ticker, listing):
    company = type("C", (), {"ticker": ticker, "currency": listing})()
    value = Decimal("123.456789")
    factor = price_units.price_unit_factor(quote_currency=quote, target_currency=target, company=company)
    direct = price_units.price_in_currency(
        value, quote_currency=quote, target_currency=target, company=company
    )
    if factor is None:
        assert direct is None
    else:
        assert direct == value * Decimal(factor[0]) / Decimal(factor[1])
