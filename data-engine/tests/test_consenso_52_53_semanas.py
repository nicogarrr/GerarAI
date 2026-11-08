"""Ejercicios de 52/53 semanas en el consenso propio (hallazgo del auditor sobre #4758).

Antes: un ejercicio que cierra el sábado 03-01-2026 (el FY2025 de un calendario semanal) salía como
«fy2026», el fy2025 desaparecía y los trimestres de 2025 caían en el ejercicio 2026 (porque el mes
de cierre pasaba a ser enero). Ahora el periodo se ubica por su fecha de cierre real, llevada al mes
nominal (un cierre en los 7 primeros días de un mes es del mes anterior)."""
from __future__ import annotations

from datetime import date

from app.services.own_consensus import actuals_from_facts, fiscal_year_of, nominal_month, quarter_of

ROWS = [("2024-12-28:FY", 100.0, None, None), ("2026-01-03:FY", 120.0, None, None),
        ("2025-03-29:Q1", 25.0, None, None), ("2025-06-28:Q2", 28.0, None, None),
        ("2025-09-27:Q3", 30.0, None, None), ("2024-09-28:Q3", 24.0, None, None)]


def test_cierre_a_primeros_de_mes_es_del_mes_anterior() -> None:
    assert nominal_month(date(2026, 1, 3)) == (2025, 12)
    assert nominal_month(date(2025, 9, 27)) == (2025, 9)
    assert fiscal_year_of(date(2026, 1, 3)) == 2025
    assert quarter_of(date(2026, 1, 3), 12) == (4, 2025)


def test_ejercicio_de_53_semanas_conserva_su_año_y_sus_trimestres() -> None:
    got = actuals_from_facts(ROWS, metric="revenue")
    assert got["fy2025"].value == 120.0 and got["fy2024"].value == 100.0
    assert "fy2026" not in got
    assert got["q1_2025"].value == 25.0 and got["q3_2025"].value == 30.0 and got["q3_2024"].value == 24.0
    q4 = got["q4_2025"]
    assert q4.derived and q4.value == 120.0 - 25.0 - 28.0 - 30.0


def test_ejercicio_de_septiembre_semanal() -> None:
    rows = [("2024-09-28:FY", 391.0, None, None), ("2025-09-27:FY", 416.0, None, None),
            ("2024-12-28:Q1", 124.3, None, None), ("2025-03-29:Q2", 95.4, None, None)]
    got = actuals_from_facts(rows, metric="revenue")
    assert set(got) >= {"fy2024", "fy2025", "q1_2025", "q2_2025"}
