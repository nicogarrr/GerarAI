"""TTM (últimos 4 trimestres) con cifras reales de Apple (AAPL).

Fórmula (estándar de mercado, p. ej. Investopedia «Trailing 12 Months» y la
nota de la SEC sobre el 10-K, que incluye el cuarto trimestre):

- Partidas de flujo (ventas, beneficio, flujo operativo, capex, BPA, D&A...):
  suma de los 4 últimos trimestres fiscales consecutivos.
- Partidas de balance (caja, deuda, patrimonio, activos...): el último
  trimestre.
- Q4 no se presenta en 10-Q (va dentro del 10-K): Q4 = FY − (Q1 + Q2 + Q3),
  marcado INFERIDO.
- Flujos que el 10-Q solo trae acumulados (YTD): trimestre = YTD(t) − YTD(t−1)
  del mismo ejercicio, también INFERIDO.

Las cifras salen de tests/fixtures/aapl_ttm.json, copiadas a mano del
companyfacts de la SEC (https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json)
para estos filings de Apple Inc.:
- 10-K FY2025 (ejercicio cerrado el 27/09/2025, presentado el 31/10/2025);
- 10-Q Q1/Q2/Q3 FY2025 (cierres 28/12/2024, 29/03/2025 y 28/06/2025);
- 10-Q Q1/Q2/Q3 FY2026 (cierres 27/12/2025, 28/03/2026 y 27/06/2026; el
  último presentado el 31/07/2026).
Importes en millones de USD.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.ttm_fundamentals import (
    PeriodValue,
    combine_ttm,
    derive_quarters_from_ytd,
    latest_point,
    trailing_twelve_months,
)


class _Fixture:
    """Cifras reales de Apple: tests/fixtures/aapl_ttm.json (ver «_fuente»)."""

    def __init__(self, data: dict) -> None:
        self.__dict__.update(data)


aapl = _Fixture(json.loads((Path(__file__).parent / "fixtures" / "aapl_ttm.json").read_text("utf-8")))


def _flows(rows, unit="USD"):
    return [
        PeriodValue(
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
            value=Decimal(str(val)),
            unit=unit,
        )
        for start, end, val in rows
    ]


def _points(rows, unit="USD"):
    return [
        PeriodValue(end=date.fromisoformat(end), value=Decimal(str(val)), unit=unit)
        for end, val in rows
    ]


# --- Derivación del trimestre a partir de acumulados (YTD) ------------------


def test_trimestre_desde_acumulados_flujo_operativo_aapl():
    """Flujo operativo de Apple (10-Q solo trae 3, 6 y 9 meses acumulados).

    Q2 FY25 = 53.887 − 29.935 = 23.952
    Q3 FY25 = 81.754 − 53.887 = 27.867
    Q2 FY26 = 82.627 − 53.925 = 28.702
    Q3 FY26 = 116.996 − 82.627 = 34.369
    Q1 de cada ejercicio ya es un trimestre (3 meses): se queda tal cual.
    """
    quarters = derive_quarters_from_ytd(_flows(aapl.OPERATING_CASH_FLOW_YTD))
    by_end = {q.end.isoformat(): q for q in quarters}
    assert by_end[aapl.Q1_FY25].value == Decimal("29935")
    assert by_end[aapl.Q1_FY25].reported is True
    assert by_end[aapl.Q2_FY25].value == Decimal("23952")
    assert by_end[aapl.Q3_FY25].value == Decimal("27867")
    assert by_end[aapl.Q2_FY26].value == Decimal("28702")
    assert by_end[aapl.Q3_FY26].value == Decimal("34369")
    assert by_end[aapl.Q3_FY26].reported is False
    assert by_end[aapl.Q3_FY26].start == date(2026, 3, 29)


def test_trimestre_de_3_meses_presentado_gana_al_derivado():
    """Si el 10-Q ya trae el trimestre (3 meses), no se deriva nada."""
    rows = _flows([
        ("2025-09-28", "2025-12-27", 100),
        ("2025-09-28", "2026-03-28", 250),
        ("2025-12-28", "2026-03-28", 149),  # 3 meses presentado (≠ 150 a propósito)
    ])
    quarters = derive_quarters_from_ytd(rows)
    by_end = {q.end.isoformat(): q for q in quarters}
    assert by_end["2026-03-28"].value == Decimal("149")
    assert by_end["2026-03-28"].reported is True


def test_acumulado_sin_el_anterior_no_inventa_trimestre():
    """Un 9M sin el 6M del mismo ejercicio no deja derivar Q3."""
    rows = _flows([("2025-09-28", "2026-06-27", 300)])
    assert derive_quarters_from_ytd(rows) == []


# --- TTM de flujos ---------------------------------------------------------


def test_ttm_ventas_aapl_con_q4_derivado():
    """Ventas TTM a 27/06/2026.

    Q4 FY25 = FY25 − (Q1 + Q2 + Q3) = 416.161 − (124.300 + 95.359 + 94.036)
            = 416.161 − 313.695 = 102.466   (INFERIDO)
    TTM = Q4 FY25 + Q1 FY26 + Q2 FY26 + Q3 FY26
        = 102.466 + 143.756 + 111.184 + 109.417 = 466.823
    """
    result = trailing_twelve_months(
        "revenue", _flows(aapl.REVENUE_Q), _flows(aapl.REVENUE_FY)
    )
    assert result.basis == "TTM"
    assert result.value == Decimal("466823")
    assert result.provenance == "INFERIDO"
    assert result.period_end == date(2026, 6, 27)
    assert [q.end.isoformat() for q in result.quarters] == [
        aapl.FY25_END, aapl.Q1_FY26, aapl.Q2_FY26, aapl.Q3_FY26,
    ]
    q4 = result.quarters[0]
    assert q4.value == Decimal("102466")
    assert q4.reported is False
    assert result.label == "TTM (últimos 4 trimestres)"


def test_ttm_beneficio_neto_aapl():
    """Q4 FY25 = 112.010 − (36.330 + 24.780 + 23.434) = 27.466
    TTM = 27.466 + 42.097 + 29.578 + 29.789 = 128.930
    """
    result = trailing_twelve_months(
        "net_income", _flows(aapl.NET_INCOME_Q), _flows(aapl.NET_INCOME_FY)
    )
    assert result.value == Decimal("128930")
    assert result.basis == "TTM"


def test_ttm_bpa_diluido_aapl():
    """BPA: Q4 FY25 = 7,46 − (2,40 + 1,65 + 1,57) = 1,84 (aproximado: el BPA
    no es exactamente aditivo; Apple publicó 1,85).
    TTM = 1,84 + 2,84 + 2,01 + 2,02 = 8,71
    """
    result = trailing_twelve_months(
        "eps_diluted", _flows(aapl.EPS_DILUTED_Q, "USD/share"),
        _flows(aapl.EPS_DILUTED_FY, "USD/share"),
    )
    assert result.value == Decimal("8.71")
    assert result.provenance == "INFERIDO"
    assert result.note is not None and "aditivo" in result.note


def test_ttm_flujo_operativo_capex_y_fcf_aapl_desde_acumulados():
    """Flujo operativo TTM a 27/06/2026 con trimestres derivados de YTD:
    Q4 FY25 = 111.482 − 81.754 = 29.728 (FY − 9M)
    TTM = 29.728 + 53.925 + 28.702 + 34.369 = 146.724
    Comprobación con la fórmula clásica FY + YTD actual − YTD anterior:
    111.482 + 116.996 − 81.754 = 146.724 ✓

    Capex TTM = 12.715 + 6.799 − 9.473 = 10.041 (se guarda en negativo).
    FCF TTM = 146.724 − 10.041 = 136.683.
    D&A TTM = 11.698 + 9.973 − 8.571 = 13.100.
    """
    ocf = trailing_twelve_months(
        "operating_cash_flow",
        derive_quarters_from_ytd(_flows(aapl.OPERATING_CASH_FLOW_YTD)),
        _flows(aapl.OPERATING_CASH_FLOW_FY),
    )
    assert ocf.value == Decimal("146724")
    assert ocf.basis == "TTM"
    assert ocf.provenance == "INFERIDO"

    def negative(rows):
        return [(s, e, -v) for s, e, v in rows]

    capex = trailing_twelve_months(
        "capital_expenditure",
        derive_quarters_from_ytd(_flows(negative(aapl.CAPEX_YTD))),
        _flows(negative(aapl.CAPEX_FY)),
    )
    assert capex.value == Decimal("-10041")

    fcf = combine_ttm("free_cash_flow", ocf, capex, op="add")
    assert fcf.value == Decimal("136683")
    assert fcf.basis == "TTM"
    assert fcf.period_end == date(2026, 6, 27)

    dna = trailing_twelve_months(
        "depreciation_amortization",
        derive_quarters_from_ytd(_flows(aapl.DEPRECIATION_YTD)),
        _flows(aapl.DEPRECIATION_FY),
    )
    assert dna.value == Decimal("13100")


def test_ttm_todo_presentado_es_oficial():
    """4 trimestres de 3 meses presentados (sin Q4 derivado) → OFICIAL."""
    rows = _flows([
        ("2025-01-01", "2025-03-31", 10),
        ("2025-04-01", "2025-06-30", 20),
        ("2025-07-01", "2025-09-30", 30),
        ("2025-10-01", "2025-12-31", 40),
    ])
    result = trailing_twelve_months("revenue", rows, [])
    assert result.value == Decimal("100")
    assert result.provenance == "OFICIAL"


# --- Respaldo: FY y SIN_DATOS ----------------------------------------------


def test_sin_4_trimestres_contiguos_cae_al_ultimo_fy():
    """Solo Q1-Q3 FY26 y el FY25: falta el Q4 FY25 porque no hay los tres
    trimestres FY25 para restarlos → no hay 4 contiguos → FY25 etiquetado."""
    quarters = [q for q in _flows(aapl.REVENUE_Q) if q.end >= date(2025, 12, 1)]
    result = trailing_twelve_months("revenue", quarters, _flows(aapl.REVENUE_FY))
    assert result.basis == "FY"
    assert result.value == Decimal("416161")
    assert result.period_end == date(2025, 9, 27)
    assert result.label == "FY (último ejercicio)"
    assert result.provenance == "OFICIAL"


def test_hueco_entre_trimestres_no_es_contiguo():
    rows = _flows([
        ("2024-10-01", "2024-12-31", 10),
        ("2025-04-01", "2025-06-30", 20),  # falta el trimestre de marzo
        ("2025-07-01", "2025-09-30", 30),
        ("2025-10-01", "2025-12-31", 40),
    ])
    result = trailing_twelve_months("revenue", rows, [])
    assert result.basis == "SIN_DATOS"
    assert result.value is None
    assert result.provenance == "SIN_DATOS"


def test_fy_mas_reciente_que_los_trimestres_manda_el_fy():
    """Si el último 10-K cierra después del último trimestre, el FY ya es
    el TTM más reciente."""
    quarters = [q for q in _flows(aapl.REVENUE_Q) if q.end <= date(2025, 6, 30)]
    result = trailing_twelve_months("revenue", quarters, _flows(aapl.REVENUE_FY))
    assert result.basis == "FY"
    assert result.value == Decimal("416161")


def test_unidades_mezcladas_no_se_suman():
    rows = _flows([
        ("2025-01-01", "2025-03-31", 10),
        ("2025-04-01", "2025-06-30", 20),
        ("2025-07-01", "2025-09-30", 30),
    ]) + _flows([("2025-10-01", "2025-12-31", 40)], unit="EUR")
    result = trailing_twelve_months("revenue", rows, [])
    assert result.basis == "SIN_DATOS"


def test_sin_nada_es_sin_datos():
    result = trailing_twelve_months("revenue", [], [])
    assert result.basis == "SIN_DATOS"
    assert result.value is None
    assert result.label == "Sin datos"


# --- Balance: último trimestre ----------------------------------------------


@pytest.mark.parametrize(
    ("metric", "quarters", "annuals", "expected"),
    [
        ("cash_and_equivalents", aapl.CASH_Q, aapl.CASH_FY, "39544"),
        ("total_equity", aapl.EQUITY_Q, aapl.EQUITY_FY, "107520"),
        ("total_assets", aapl.ASSETS_Q, aapl.ASSETS_FY, "383266"),
    ],
)
def test_balance_ultimo_trimestre_aapl(metric, quarters, annuals, expected):
    """Balance a 27/06/2026 (10-Q Q3 FY26): caja 39.544, patrimonio 107.520,
    activos 383.266. No se suma nada: es el último instantáneo."""
    result = latest_point(metric, _points(quarters), _points(annuals))
    assert result.value == Decimal(expected)
    assert result.basis == "Q"
    assert result.period_end == date(2026, 6, 27)
    assert result.provenance == "OFICIAL"
    assert result.label == "Último trimestre"


def test_balance_sin_trimestres_usa_el_fy():
    result = latest_point("cash_and_equivalents", [], _points(aapl.CASH_FY))
    assert result.basis == "FY"
    assert result.value == Decimal("35934")


def test_combinar_periodos_distintos_no_mezcla():
    """FCF con OCF TTM y capex FY de fechas distintas → sin dato, no mezcla."""
    ocf = trailing_twelve_months(
        "operating_cash_flow",
        derive_quarters_from_ytd(_flows(aapl.OPERATING_CASH_FLOW_YTD)),
        _flows(aapl.OPERATING_CASH_FLOW_FY),
    )
    capex_fy = trailing_twelve_months(
        "capital_expenditure", [], _flows([(aapl.FY2025_START, aapl.FY25_END, -12715)])
    )
    fcf = combine_ttm("free_cash_flow", ocf, capex_fy, op="add")
    assert fcf.value is None
    assert fcf.basis == "SIN_DATOS"
