"""Rendimiento: la reconstruccion guarda los cierres por dia y empresa.

El bucle diario (dias x posiciones: 390.000 vueltas con 300 posiciones y 5
años) buscaba cada cierre con una tupla (empresa, dia) nueva por vuelta. Ahora
toma el dict del dia una vez y busca por id, y un factor de unidad 1/1 no hace
dos operaciones Decimal. Este test fija la salida COMPLETA de una cartera con
compras, ventas, split aplicado, dias sin cierre y varias empresas: serie,
retornos (bit a bit), dias excluidos con su motivo, comprobaciones y TWR.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.models.entities import CorporateAction
from app.services.portfolio_reconstruction_service import PortfolioReconstructionService
from tests.test_portfolio_reconstruction_service import (  # noqa: F401  (fixture db)
    D0,
    _company,
    _position,
    _price,
    _tx,
    db,
)

# Salida de main antes del cambio (misma cartera).
SERIE = [
    ("01", 100.0),
    ("02", 331.72),
    ("03", 394.3),
    ("04", 395.94),
    ("06", 355.78),
    ("07", 581.65),
    ("08", 581.59),
    ("09", 135.77),
    ("10", 137.74),
    ("11", 139.71),
    ("12", 141.68),
]
RETORNOS = {
    2: "-0x1.c5d63886594afp-7",
    3: "-0x1.0b1c5ff3ec780p-11",
    4: "0x1.11ea1215f33bap-8",
    6: "0x1.7fabeaab37e8bp-7",
    7: "0x1.450ab7296cfa0p-1",
    8: "-0x1.a9745d413a6a4p-14",
    9: "-0x1.6194f99939aecp-2",
    10: "0x1.dbb4e10051183p-7",
    11: "0x1.d4e63c01a0ccap-7",
    12: "0x1.ce48c27727b8ep-7",
}
EXCLUIDOS = [("05", "sin precio de cierre: BBB")]
TWR = "0x1.e4cd8a8042230p-4"
MEDIANA = 0.0135


def _cartera(db):
    a, b, c = _company(db, "AAA"), _company(db, "BBB"), _company(db, "CCC")
    _tx(db, a, D0, "buy", "10", "10")
    _tx(db, b, D0 + timedelta(days=2), "buy", "3", "20.5", fees="1.25")
    _tx(db, a, D0 + timedelta(days=5), "sell", "4", "11.2")
    _tx(db, c, D0 + timedelta(days=1), "buy", "7", "33.3")
    _tx(db, c, D0 + timedelta(days=8), "sell", "7", "35")
    for offset in range(12):
        day = D0 + timedelta(days=offset)
        _price(db, a, day, 10 + offset * 0.173)
        if offset != 4:  # BBB sin cierre el dia 4: el dia queda fuera
            _price(db, b, day, 20 + offset * 0.311)
        _price(db, c, day, 66 - offset * 0.29)  # split 2:1 aplicado el dia 6
    db.add(
        CorporateAction(
            company_id=c.id,
            action_type="split",
            ratio=Decimal("2"),
            effective_date=D0 + timedelta(days=6),
            applied=True,
            source="t",
        )
    )
    _position(db, a, "6", str(6 * (10 + 11 * 0.173)))
    _position(db, b, "3", str(3 * (20 + 11 * 0.311)))
    db.commit()


def test_reconstruccion_misma_salida_completa(db):
    _cartera(db)

    result = PortfolioReconstructionService().build(db)

    assert result.status == "ok"
    assert [(row["date"][-2:], row["value_base"]) for row in result.series] == SERIE
    assert {day.day: value.hex() for day, value in result.returns.items()} == RETORNOS
    assert [(row["date"][-2:], row["reason"]) for row in result.excluded_days] == EXCLUIDOS
    assert result.twr is not None and result.twr.hex() == TWR
    assert result.price_check["compared_trades"] == 5
    assert result.price_check["median_abs_diff_vs_close"] == MEDIANA
