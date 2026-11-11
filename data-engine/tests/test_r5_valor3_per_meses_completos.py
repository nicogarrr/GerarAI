"""Regla «per-antiguedad-v2»: la antigüedad del PER se cuenta en meses completos, igual en el corte y en el texto.

v1 cortaba a los 548 días y nombraba la diferencia de mes de calendario. Con un cierre a fin de mes leído justo a
los 18 meses (2025-07-31 → 2027-01-31, 549 días) decía «hace 18 meses, más de 18», que se contradice; y un cierre
2025-03-15 leído el 2026-11-11 decía «hace 20 meses» con 19 cumplidos. Fechas fijas.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.api.routes import watchlist as wl
from app.models import FinancialFact


def _row(end: date) -> FinancialFact:
    return FinancialFact(metric="eps_diluted", period=f"{end.isoformat()}:FY", fiscal_year=end.year)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2024, 12, 31), date(2026, 6, 30), (18, 0)),  # fin de mes: junio no tiene 31
        (date(2024, 12, 31), date(2026, 7, 1), (18, 1)),
        (date(2025, 1, 31), date(2026, 7, 3), (17, 3)),  # 18 meses serían el 31-jul: 17 (al 30-jun) y 3 días
        (date(2025, 2, 1), date(2026, 8, 1), (18, 0)),  # retailer 52/53 semanas
        (date(2025, 2, 1), date(2026, 7, 31), (17, 30)),
        (date(2024, 2, 29), date(2025, 8, 29), (18, 0)),
    ],
)
def test_meses_completos(start, end, expected):
    assert wl._whole_months_and_days(start, end) == expected


def test_justo_18_meses_no_es_mas_de_18():
    # v1: 549 días > 548 → N/D «hace 18 meses, más de 18».
    assert wl._stale_annual_reason(_row(date(2025, 7, 31)), date(2027, 1, 31)) is None


def test_18_meses_y_dias_lo_dice_sin_contradecirse():
    reason = wl._stale_annual_reason(_row(date(2025, 2, 1)), date(2026, 8, 4))
    assert reason is not None
    assert "hace 18 meses y 3 días, más de 18" in reason
    assert "hace 18 meses, más de 18" not in reason


def test_mas_de_18_meses_cuenta_meses_completos():
    # 2024-12-31 → 2026-11-11: 22 meses completos (al 2026-10-31) y 11 días.
    reason = wl._stale_annual_reason(_row(date(2024, 12, 31)), date(2026, 11, 11))
    assert reason is not None and "hace 22 meses, más de 18" in reason
    # 2025-03-15 → 2026-11-11: 19 meses completos (la diferencia de calendario diría 20).
    reason = wl._stale_annual_reason(_row(date(2025, 3, 15)), date(2026, 11, 11))
    assert reason is not None and "hace 19 meses, más de 18" in reason


def test_un_dia_tras_18_meses_es_nd():
    assert wl._stale_annual_reason(_row(date(2025, 2, 1)), date(2026, 8, 2)) is not None
    assert wl._stale_annual_reason(_row(date(2025, 2, 1)), date(2026, 8, 1)) is None
