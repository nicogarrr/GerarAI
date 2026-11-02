"""Rendimiento: los cierres de /portfolio/intelligence se leen por Core.

Son cientos de miles de filas por peticion (300 posiciones x 5 años) y la
capa de resultados ORM era una parte grande de la lectura. MarketPrice no es
de tenant, asi que leer por ``db.connection()`` no pierde ningun filtro. Este
test fija que las filas son las mismas (valores, tipos, orden y nombres de
columna) que las de la consulta ORM equivalente, y que no pasa por el ORM.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import event, select

from app.models import MarketPrice
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from tests.test_portfolio_reconstruction_service import D0, _company, _price, db  # noqa: F401  (fixture db)


def test_cierres_por_core_mismas_filas_sin_orm(db):
    companies = [_company(db, f"K{i}") for i in range(3)]
    for index, company in enumerate(companies):
        for offset in range(12):
            _price(db, company, D0 + timedelta(days=offset), 10 + index + offset * 0.137)
    db.commit()
    ids = [company.id for company in reversed(companies)]
    since = D0 + timedelta(days=2)

    esperado = db.execute(
        select(
            MarketPrice.company_id,
            MarketPrice.date,
            MarketPrice.close,
            MarketPrice.adj_close,
            MarketPrice.source,
            MarketPrice.quote_currency,
        )
        .where(MarketPrice.company_id.in_(sorted(ids)), MarketPrice.date >= since)
        .order_by(MarketPrice.company_id, MarketPrice.date)
    ).all()

    orm_calls: list[object] = []

    def _orm(state):
        orm_calls.append(state)

    event.listen(db, "do_orm_execute", _orm)
    try:
        filas = PortfolioIntelligenceService._closes_rows(db, ids, since)
    finally:
        event.remove(db, "do_orm_execute", _orm)

    assert orm_calls == []
    assert len(filas) == 3 * 10
    assert [tuple(fila) for fila in filas] == [tuple(fila) for fila in esperado]
    primera = filas[0]
    assert primera.company_id == companies[0].id and primera.date == since
    assert isinstance(primera.close, Decimal) and isinstance(primera.adj_close, Decimal)
    assert [type(v) for v in filas[-1]] == [type(v) for v in esperado[-1]]
