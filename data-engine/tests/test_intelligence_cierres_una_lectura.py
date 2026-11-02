"""/portfolio/intelligence lee los cierres UNA vez por peticion.

Las series de rentabilidad (posiciones en cartera, ventana de N anos) y la
reconstruccion diaria (empresas con operaciones, desde la primera operacion)
leian por separado casi las mismas ~390.000 filas de market_prices con 300
posiciones. Ahora la reconstruccion pide sus cierres y se leen de una vez
para las dos; la respuesta tiene que ser IDENTICA a la de leer por separado,
tanto si la lectura comun coincide con lo pedido como si abarca mas
(empresa ya vendida, primera operacion antes de la ventana).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import event

from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from app.services.portfolio_reconstruction_service import PortfolioReconstructionService
from tests.test_portfolio_reconstruction_service import (  # noqa: F401  (fixture db)
    D0,
    _company,
    _position,
    _price,
    _tx,
    db,
)

LECTURA = "SELECT market_prices.company_id, market_prices.date, market_prices.close"


def _cartera_con_vendida(db):
    held = [_company(db, f"H{i}") for i in range(3)]
    vendida = _company(db, "VEND")
    for index, company in enumerate([*held, vendida]):
        _tx(db, company, D0, "buy", "10", str(10 + index))
        for offset in range(40):
            _price(db, company, D0 + timedelta(days=offset), 10 + index + offset * 0.05)
    _tx(db, vendida, D0 + timedelta(days=20), "sell", "10", "12")
    for index, company in enumerate(held):
        _position(db, company, "10", str(10 * (10 + index + 39 * 0.05)))
    db.commit()


def _cartera_antigua(db):
    """Primera operacion ANTES de la ventana de 1 ano: la reconstruccion pide
    desde antes y las series empiezan en el corte."""
    start = date.today() - timedelta(days=400)
    held = [_company(db, f"A{i}") for i in range(3)]
    for index, company in enumerate(held):
        _tx(db, company, start, "buy", "5", str(20 + index))
        for offset in range(400):
            _price(db, company, start + timedelta(days=offset), 20 + index + offset * 0.01)
        _position(db, company, "5", str(5 * (20 + index + 399 * 0.01)))
    db.commit()


def _cartera_reciente(db):
    """Todo en cartera y operaciones dentro de la ventana: la lectura comun es
    exactamente la de las series."""
    start = date.today() - timedelta(days=100)
    for index in range(3):
        company = _company(db, f"R{index}")
        _tx(db, company, start, "buy", "4", str(30 + index))
        for offset in range(100):
            _price(db, company, start + timedelta(days=offset), 30 + index + offset * 0.02)
        _position(db, company, "4", str(4 * (30 + index + 99 * 0.02)))
    db.commit()


def _con_lecturas(db, accion):
    sentencias: list[str] = []

    def _anotar(conn, cursor, statement, params, context, executemany):
        sentencias.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _anotar)
    try:
        resultado = accion()
    finally:
        event.remove(engine, "before_cursor_execute", _anotar)
    return resultado, [s for s in sentencias if " ".join(s.split()).startswith(LECTURA)]


def _por_separado(monkeypatch):
    """La ruta de antes: la reconstruccion lee sus propios cierres."""
    original = PortfolioReconstructionService.build

    def build_sin_compartir(self, db, **kwargs):
        kwargs.pop("closes", None)
        return original(self, db, **kwargs)

    monkeypatch.setattr(PortfolioReconstructionService, "build", build_sin_compartir)


@pytest.mark.parametrize(
    ("cartera", "years"), [(_cartera_con_vendida, 5), (_cartera_antigua, 1), (_cartera_reciente, 1)]
)
def test_una_lectura_de_cierres_y_misma_respuesta(db, monkeypatch, cartera, years):
    cartera(db)
    service = PortfolioIntelligenceService()
    compartida, lecturas = _con_lecturas(db, lambda: service.build(db, years=years))
    assert len(lecturas) == 1
    assert compartida["performance"]["reconstruction"]["status"] == "ok"

    _por_separado(monkeypatch)
    separada, lecturas_antes = _con_lecturas(db, lambda: service.build(db, years=years))
    assert len(lecturas_antes) == 2
    assert compartida == separada


def test_reconstruccion_sin_proveedor_o_proveedor_sin_datos_lee_ella(db):
    _cartera_con_vendida(db)
    propia = PortfolioReconstructionService().build(db, start=D0)
    con_none = PortfolioReconstructionService().build(db, start=D0, closes=lambda ids, since: None)
    assert propia.as_dict() == con_none.as_dict()
    assert list(propia.returns.items()) == list(con_none.returns.items())
