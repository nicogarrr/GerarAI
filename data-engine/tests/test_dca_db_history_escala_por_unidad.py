"""Rendimiento: _db_history resuelve la escala por unidad, no por cierre.

Hay una o dos unidades por ticker (p. ej. GBp y GBP) y miles de cierres; la
escala se calcula una vez por unidad y el resultado no cambia.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.models.entities import MarketPrice
from app.services import dca_signal_service as svc
from app.valuation import currency as currency_module
from tests.test_dca_signal_service import _company, db  # noqa: F401  (fixture db)


def test_escala_una_vez_por_unidad_y_mismas_filas(db, monkeypatch):
    company = _company(db, "TSCO.L", currency="GBp", exchange="LSE")
    start = date(2026, 1, 1)
    for i in range(30):
        value = Decimal(str(250 + i))
        db.add(
            MarketPrice(
                company_id=company.id,
                date=start + timedelta(days=i),
                open=value,
                high=value,
                low=value,
                close=value,
                adj_close=value,
                volume=10,
                source="test",
                quote_currency="GBp",
            )
        )
    pounds = Decimal("2.9")
    db.add(
        MarketPrice(
            company_id=company.id,
            date=start + timedelta(days=30),
            open=pounds,
            high=pounds,
            low=pounds,
            close=pounds,
            adj_close=None,
            volume=10,
            source="test",
            quote_currency="GBP",
        )
    )
    db.flush()
    calls = {"n": 0}
    real = currency_module.normalize_currency

    def counting(raw):
        calls["n"] += 1
        return real(raw)

    monkeypatch.setattr(currency_module, "normalize_currency", counting)
    hist = svc._db_history(db, company)

    # 1 para la unidad declarada + 1 por cada unidad distinta (GBp, GBP); antes 1 + 31.
    assert calls["n"] == 3
    assert hist.currency == "GBP"
    assert len(hist.rows) == 31
    assert hist.rows[0] == svc.PriceRow(day=start, close=2.5, adj_close=2.5)
    assert hist.rows[-1] == svc.PriceRow(day=start + timedelta(days=30), close=2.9, adj_close=None)
