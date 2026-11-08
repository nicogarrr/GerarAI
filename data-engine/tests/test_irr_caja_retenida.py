"""Rama PER / P/VC del motor de TIR: el flujo que no se reparte no desaparece (hallazgo del auditor).

Antes: con PER y reparto 0, diez años de flujo libre (100/año) no aparecían en ningún sitio: precio a
10 años = 100 y TIR 0 %, como si la empresa tirara la caja. Ahora se acumula como caja del accionista."""
from __future__ import annotations

import pytest

from app.valuation import shareholder_irr as e


def _sp(basis: str) -> e.StartingPoint:
    return e.StartingPoint(price=100, shares_diluted=10, revenue=1000, ebitda=200, net_income=100, basis=basis)


def _drivers(dp: float, bp: float, mna: float = 0.0) -> e.Drivers:
    return e.Drivers(organic_growth=0.0, organic_growth_late=0.0, cash_conversion=1.0, dividend_payout=dp,
                     buyback_payout=bp, mna_spend_pct_revenue=mna, exit_multiple=10.0)


def test_per_sin_reparto_acumula_la_caja_retenida() -> None:
    rows = e.project(_sp("pe"), _drivers(0.0, 0.0), 10)
    assert rows[-1].net_debt == pytest.approx(-1000.0)  # 100/año × 10 retenidos
    # precio = PER 10 × BPA 10 + caja 100/acción
    assert rows[-1].buyback_price == pytest.approx(200.0)


def test_per_retener_o_repartir_vale_parecido() -> None:
    """Sin crecimiento ni cambio de múltiplo, retener el flujo como caja o repartirlo debe dar una TIR
    parecida (antes: 0 % retenido frente a ~10 % repartido)."""
    sp = _sp("pe")
    kept = e.evaluate(sp, _drivers(0.0, 0.0), (10,))[10]
    paid = e.evaluate(sp, _drivers(1.0, 0.0), (10,))[10]
    assert kept.irr is not None and paid.irr is not None
    assert kept.irr > 0.05
    assert abs(kept.irr - paid.irr) < 0.03


def test_pb_tambien_acumula_la_caja_retenida() -> None:
    sp = e.StartingPoint(price=100, shares_diluted=10, revenue=1000, ebitda=None, net_income=100, basis="pb")
    rows = e.project(sp, e.Drivers(organic_growth=0.0, organic_growth_late=0.0, cash_conversion=1.0,
                                   exit_multiple=1.0), 10)
    assert rows[-1].net_debt == pytest.approx(-1000.0)
    assert rows[-1].buyback_price == pytest.approx(200.0)  # P/VC 1 × 100 + caja 100


def test_per_mna_por_encima_del_flujo_se_financia_con_deuda() -> None:
    rows = e.project(_sp("pe"), _drivers(0.0, 0.0, mna=0.2), 1)
    # flujo 100·(1+crec. por M&A) − gasto 200: la diferencia es deuda, no un regalo
    assert rows[0].net_debt > 0


def test_ev_ebitda_sin_cambios() -> None:
    sp = e.StartingPoint(price=100, shares_diluted=10, revenue=1000, ebitda=200, net_income=100, debt=300, cash=100)
    rows = e.project(sp, _drivers(0.0, 0.0), 10)
    assert rows[-1].net_debt == pytest.approx(200 - 10 * 200)
