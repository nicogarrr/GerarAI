"""Tope a la normalización de capex: nunca por encima del mejor margen FCF real.

Owner (Nico, 4-nov-2026, 11:40 Madrid): «Mete todo lo que mejores resultados
tenga». La normalización de capex (capex de mantenimiento = amortización)
llevaba el margen objetivo de META del 34,6 % al 42,5 %, un margen que la
empresa nunca ha tenido. El backtest 2 (point-in-time, work/gerarai-backtest2)
probó a acotarlo al mejor margen FCF REAL (flujo operativo − capex total) de
los últimos 5 ejercicios: error a 12 m 48 % → 41 % en 2021–26 y casi igual en
2015–20. Regla general: objetivo = min(objetivo, mejor margen real de los
últimos ``CAPEX_NORM_MAX_REAL_MARGIN_YEARS`` ejercicios); con menos años, los
que haya, y la traza lo dice.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.valuation.normalized_fcf import (
    CAPEX_NORM_MAX_REAL_MARGIN_YEARS,
    capex_normalization,
)


def _fact(value, fid):
    return SimpleNamespace(value=value, unit="USD", id=fid)


def _history(rows):
    """rows: {año: (ingresos, flujo operativo, capex, amortización)}."""
    out = {}
    fid = 1
    for year, (revenue, ocf, capex, da) in rows.items():
        out[year] = {
            "revenue": _fact(revenue, fid),
            "operating_cash_flow": _fact(ocf, fid + 1),
            "capital_expenditure": _fact(-capex, fid + 2),
            "depreciation_amortization": _fact(da, fid + 3),
        }
        fid += 4
    return out


# Margen real (ocf − capex) / ventas: 30, 32, 33, 28, 20 %; con capex de
# mantenimiento = amortización el margen normalizado medio sale ~45 %.
GROWTH_CAPEX = {
    2025: (1000.0, 520.0, 320.0, 60.0),   # real 20 %, normalizado 46 %
    2024: (900.0, 450.0, 198.0, 50.0),    # real 28 %, normalizado 44,4 %
    2023: (800.0, 400.0, 136.0, 40.0),    # real 33 %, normalizado 45 %
    2022: (700.0, 350.0, 126.0, 35.0),    # real 32 %, normalizado 45 %
    2021: (600.0, 300.0, 120.0, 30.0),    # real 30 %, normalizado 45 %
    2020: (500.0, 250.0, 50.0, 25.0),     # real 40 %: fuera de la ventana de 5
}


def test_constante_de_cinco_ejercicios():
    assert CAPEX_NORM_MAX_REAL_MARGIN_YEARS == 5


def test_el_objetivo_no_supera_el_mejor_margen_real_de_cinco_ejercicios():
    result = capex_normalization(_history(GROWTH_CAPEX), 0.20)

    assert result["applied"] is True
    # Mejor margen real FY2021–FY2025 = 33 % (FY2023); el 40 % de FY2020
    # queda fuera de la ventana aunque esté en el historial de ciclo medio.
    assert result["target_margin"] == pytest.approx(0.33)
    cap = result["max_real_margin_cap"]
    assert cap["applied"] is True
    assert cap["value"] == pytest.approx(0.33)
    assert cap["fiscal_year"] == 2023
    assert cap["years"] == [2025, 2024, 2023, 2022, 2021]
    assert cap["short_history"] is False
    assert result["target_margin_capped_from"] == pytest.approx(
        sum((ocf - da) / rev for rev, ocf, _capex, da in GROWTH_CAPEX.values()) / 6
    )
    assert "33,0 %" in result["note_es"]


def test_con_menos_de_cinco_ejercicios_usa_los_que_hay_y_lo_dice():
    three = {year: GROWTH_CAPEX[year] for year in (2025, 2024, 2023)}

    result = capex_normalization(_history(three), 0.20)

    cap = result["max_real_margin_cap"]
    assert result["applied"] is True
    assert cap["years"] == [2025, 2024, 2023]
    assert cap["short_history"] is True
    assert result["target_margin"] == pytest.approx(0.33)


def test_un_objetivo_por_debajo_del_mejor_margen_real_no_se_toca():
    # Real 30 % todos los años; normalizado 35 %: el tope (30 %) recorta.
    # Con un real histórico alto (50 % en FY2022) el objetivo medio queda
    # por debajo y no se toca.
    rows = dict(GROWTH_CAPEX)
    rows[2022] = (700.0, 450.0, 100.0, 35.0)  # real 50 %
    result = capex_normalization(_history(rows), 0.20)

    assert result["applied"] is True
    assert result["max_real_margin_cap"]["applied"] is False
    assert result.get("target_margin_capped_from") is None


def test_si_el_tope_deja_el_objetivo_sin_subida_no_se_normaliza():
    # Mejor real 20,5 % frente a un margen de entrada del 20 %: tras el tope
    # la subida es < 1 pp y se queda el margen reportado, como cualquier
    # normalización que no sube el margen.
    rows = {
        2025: (1000.0, 520.0, 320.0, 60.0),   # real 20 %
        2024: (900.0, 400.0, 215.5, 50.0),    # real 20,5 %
        2023: (800.0, 350.0, 190.0, 40.0),    # real 20 %
    }
    result = capex_normalization(_history(rows), 0.20)

    assert result["applied"] is False
    assert result["midcycle_margin"] == pytest.approx(0.205)
    assert "1 pp" in result["reason"]
