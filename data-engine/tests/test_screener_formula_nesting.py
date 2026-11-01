"""Formulas muy anidadas: error de formula (ValueError), no RecursionError/500."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.screener_service import SafeFormula

DEEP_FORMULAS = [
    "-" * 998 + "1",
    "-(" * 330 + "1" + ")" * 330,
    "+" * 999 + "1",
]


@pytest.mark.parametrize("expression", DEEP_FORMULAS, ids=["menos", "parentesis", "mas"])
def test_formula_muy_anidada_es_error_de_formula(expression: str) -> None:
    assert len(expression) <= 1000
    with pytest.raises(ValueError, match="anidada|Sintaxis"):
        SafeFormula(expression)


def test_formula_anidada_razonable_sigue_funcionando() -> None:
    formula = SafeFormula("-" * 20 + "revenue")
    assert formula.evaluate({"revenue": Decimal("5")}) == Decimal("5")
