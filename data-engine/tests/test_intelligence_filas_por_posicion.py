"""Rendimiento: las filas de cierres se leen por posicion en /portfolio/intelligence.

En una Row de SQLAlchemy leer ``row.adj_close`` por nombre cuesta ~8 veces
mas que ``row[3]``, y por peticion son ~390.000 filas (agrupar por empresa y
retornos diarios). Ahora ``build`` las lee por posicion con el orden fijo de
``CLOSES_COLUMNS``. Este test fija ese orden y que los retornos por posicion
son identicos (bit a bit) a los de ``_returns`` por nombre, con cierres
ajustados a cero o nulos en medio.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.models import MarketPrice
from app.services import portfolio_intelligence_service as pis
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from tests.test_portfolio_reconstruction_service import D0, _company, db  # noqa: F401  (fixture db)


def _cierre(db, company, offset, close, adj):
    db.add(
        MarketPrice(
            company_id=company.id,
            date=D0 + timedelta(days=offset),
            close=Decimal(close),
            adj_close=None if adj is None else Decimal(adj),
            source="t",
        )
    )


def test_columnas_fijas_y_retornos_por_posicion_identicos(db):
    a, b = _company(db, "POSA"), _company(db, "POSB")
    for offset in range(15):
        _cierre(db, a, offset, f"{10 + offset * 0.37:.4f}", f"{9.5 + offset * 0.371:.6f}")
        adj = None if offset == 6 else ("0" if offset == 9 else f"{50 - offset * 1.13:.6f}")
        _cierre(db, b, offset, f"{50 - offset * 1.1:.4f}", adj)
    db.commit()

    filas = PortfolioIntelligenceService._closes_rows(db, [b.id, a.id], D0)

    assert tuple(filas[0]._fields) == pis.CLOSES_COLUMNS
    for company in (a, b):
        serie = [fila for fila in filas if fila[0] == company.id]
        por_nombre = PortfolioIntelligenceService._returns(serie)
        por_posicion = PortfolioIntelligenceService._returns_from_pairs(map(pis._CLOSE_DATE_ADJ, serie))
        assert por_posicion == por_nombre
        assert [v.hex() for v in por_posicion.values()] == [v.hex() for v in por_nombre.values()]
    # Los huecos (adj nulo o cero) siguen descartando el par, no fabrican -100 %.
    retornos_b = PortfolioIntelligenceService._returns([fila for fila in filas if fila[0] == b.id])
    assert len(retornos_b) == 15 - 1 - 2 - 2
    assert min(retornos_b.values()) > -0.5
