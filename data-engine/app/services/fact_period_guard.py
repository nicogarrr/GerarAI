"""Guarda compartida del corte de periodo de un hecho (puente y reconcile)."""

from __future__ import annotations

import re
from datetime import date


def fact_period_consistent(
    fact_period: str | None, quarter: str, year: int, end: date, published: date | None,
) -> bool:
    """El corte debe estar respaldado por la fuente, no solo por una cadena copiable:
    sufijo ':Qn'/':FY' igual al periodo fiscal explicito, ano del corte a +-1 del ano fiscal y
    documento fuente publicado entre 0 y 200 dias DESPUES del corte. El calendario fiscal no se
    adivina: sin esos respaldos -> falla cerrado (solo contexto). Es coherencia, no prueba."""
    m = re.fullmatch(r'\d{4}-\d{2}-\d{2}:(Q[1-4]|FY)', fact_period or '')
    if not m or m[1] != quarter or abs(end.year - year) > 1 or published is None:
        return False
    return 0 <= (published - end).days <= 200
