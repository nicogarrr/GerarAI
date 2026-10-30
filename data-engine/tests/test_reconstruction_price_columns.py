"""La reconstruccion lee los cierres como columnas, sin construir MarketPrice.

Con 30 valores y dos años de cierres son ~15.000 filas: un objeto ORM por fila
era el mayor coste de /api/portfolio/intelligence. Mismo resultado que antes
(los tests de test_portfolio_reconstruction_service lo fijan) y ninguna
entidad MarketPrice cargada.
"""

from datetime import timedelta

import pytest
from sqlalchemy import event

from app.models.entities import MarketPrice
from app.services.portfolio_reconstruction_service import PortfolioReconstructionService
from tests.test_portfolio_reconstruction_service import D0, _company, _position, _price, _tx, db  # noqa: F401


def test_reconstruction_reads_closes_without_orm_entities(db):  # noqa: F811
    a = _company(db)
    _tx(db, a, D0, "buy", "10", "10")
    _tx(db, a, D0 + timedelta(days=2), "buy", "10", "11")
    for offset, close in enumerate([10, 10, 11, 12]):
        _price(db, a, D0 + timedelta(days=offset), close)
    _position(db, a, "20", "240")
    db.commit()
    db.expunge_all()

    loaded = []

    def _on_load(target, _context):
        loaded.append(target)

    event.listen(MarketPrice, "load", _on_load)
    try:
        result = PortfolioReconstructionService().build(db)
    finally:
        event.remove(MarketPrice, "load", _on_load)

    assert loaded == []
    assert result.status == "ok"
    assert result.twr == pytest.approx(1.1 * (12 / 11) - 1)
