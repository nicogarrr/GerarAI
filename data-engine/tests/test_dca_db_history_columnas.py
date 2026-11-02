"""Rendimiento: la historia DCA de la BD se lee por columnas, sin entidades ORM.

Con 400 tickers y 5 años de cierres, construir un MarketPrice por fila era
casi todo el tiempo de la evaluacion DCA (10,5 s -> 5,6 s en el banco de
pruebas). Este test fija que _db_history no carga entidades y que el
resultado no cambia.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.models.entities import MarketPrice
from app.services import dca_signal_service as svc
from tests.test_dca_signal_service import _company, db  # noqa: F401  (fixture db)


def _price(db, company, day, close, adj=None, quote=None):
    value = Decimal(str(close))
    db.add(
        MarketPrice(
            company_id=company.id,
            date=day,
            open=value,
            high=value,
            low=value,
            close=value,
            adj_close=None if adj is None else Decimal(str(adj)),
            volume=10,
            source="test",
            quote_currency=quote,
        )
    )


def test_db_history_no_carga_entidades_market_price(db):
    company = _company(db, "TSCO.L", currency="GBp", exchange="LSE")
    _price(db, company, date(2026, 9, 30), 250.0, adj=240.0, quote="GBp")
    _price(db, company, date(2026, 10, 1), 2.52, quote="GBP")
    _price(db, company, date(2026, 10, 2), 2.55)
    db.flush()
    for obj in list(db.identity_map.values()):
        if isinstance(obj, MarketPrice):
            db.expunge(obj)

    loaded: list[MarketPrice] = []

    def _on_load(target, _context):
        loaded.append(target)

    event.listen(MarketPrice, "load", _on_load)
    try:
        hist = svc._db_history(db, company)
    finally:
        event.remove(MarketPrice, "load", _on_load)

    assert loaded == []
    assert hist.currency == "GBP"
    assert [(r.day, round(r.close, 6), r.adj_close) for r in hist.rows] == [
        (date(2026, 9, 30), 2.5, 2.4),
        (date(2026, 10, 1), 2.52, None),
        (date(2026, 10, 2), 0.0255, None),
    ]
