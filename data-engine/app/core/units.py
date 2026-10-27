"""Normalización de tasas a FRACCIÓN (0,0425 = 4,25 %) en las fronteras.

Convención única del motor: toda tasa, margen o rendimiento viaja como
fracción. La unidad se lee del dato cuando la trae, en vez de adivinarla
por el tamaño:

- ``decimal`` / ``ratio`` / ``fraction`` / ``pure`` -> ya es fracción.
- ``percent`` / ``%`` / ``pct`` -> ÷ 100 (0,9 % = 0,009, nunca 90 %).
- ``bps`` / ``basis_points`` -> ÷ 10 000.

Solo cuando la unidad no dice nada (``None``, ``USD`` heredado en hechos
antiguos…) se aplica la heurística histórica «1 < x ≤ 100 => porcentaje»,
y el método devuelto lo deja claro (``heuristic_*``) para la traza: con
esa heurística un 0,9 % guardado como ``0.9`` se leería como 90 %.
"""

from __future__ import annotations

from decimal import Decimal

FRACTION_UNITS = frozenset({"decimal", "ratio", "fraction", "pure"})
PERCENT_UNITS = frozenset({"percent", "%", "pct"})
BPS_UNITS = frozenset({"bps", "basis_points"})


def to_fraction(value: Decimal | float | int | str, unit: str | None = None) -> tuple[Decimal, str]:
    """Devuelve ``(fracción, método)``.

    ``método`` es ``explicit_fraction``, ``explicit_percent``,
    ``explicit_bps``, ``heuristic_percent`` o ``heuristic_fraction``.
    """
    number = Decimal(str(value)) if not isinstance(value, Decimal) else value
    normalized_unit = (unit or "").strip().lower()
    if normalized_unit in FRACTION_UNITS:
        return number, "explicit_fraction"
    if normalized_unit in PERCENT_UNITS:
        return number / Decimal("100"), "explicit_percent"
    if normalized_unit in BPS_UNITS:
        return number / Decimal("10000"), "explicit_bps"
    if Decimal("1") < number <= Decimal("100"):
        return number / Decimal("100"), "heuristic_percent"
    return number, "heuristic_fraction"


def is_from_percent(method: str) -> bool:
    return method in {"explicit_percent", "explicit_bps", "heuristic_percent"}
