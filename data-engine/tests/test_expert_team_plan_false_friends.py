"""Plan del chat: palabras que se parecían a un experto sin serlo.

- «año fiscal», «ejercicio fiscal», «fiscal year», «fiscal 2024» hablan del
  periodo contable de la empresa, no de tus impuestos: no llaman al experto
  fiscal (antes una pregunta de beneficios abría el equipo con IRPF incluido).
- «taxonomy»/«taxi» no son «tax»; «características» no es «cara».
- Lo que sí es fiscal o de valoración sigue igual. Sin LLM ni datos.
"""

from __future__ import annotations

import pytest

from app.services.expert_team.chat import plan_for


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("¿Cuál fue el beneficio de ABC en el año fiscal 2024?", ["fundamental"]),
        ("What was ABC revenue in fiscal 2024?", ["fundamental"]),
        ("What was ABC revenue in fiscal year 2024?", ["fundamental"]),
        ("¿Cuál es el resultado del ejercicio fiscal de ABC y su margen?", ["fundamental"]),
        ("ABC: taxonomy of revenue segments and growth", ["fundamental"]),
        ("Dame las características y el crecimiento de ABC", ["fundamental"]),
    ],
)
def test_falsos_amigos_no_abren_experto(question, expected):
    assert plan_for(question, "ABC") == expected


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("¿Tributa la venta de ABC y cuál es su valoración?", ["valuation", "tax"]),
        ("Tax implications of selling ABC", ["tax"]),
        ("¿Cuántos impuestos pago si vendo ABC tras su año fiscal?", ["tax"]),
        ("What are the taxes on ABC dividends and its revenue?", ["fundamental", "tax"]),
        ("¿Está cara ABC? ¿Qué riesgo tiene?", ["valuation", "risk"]),
        ("¿ABC está cara?", ["valuation"]),
        ("ABC está caro y con mucha deuda", ["valuation", "risk"]),
        ("¿Está barato ABC y cuántos ingresos tiene?", ["fundamental", "valuation"]),
        ("¿Son caras estas acciones de ABC? ¿Y su deuda?", ["valuation", "risk"]),
    ],
)
def test_lo_fiscal_y_lo_caro_siguen_entrando(question, expected):
    assert plan_for(question, "ABC") == expected
