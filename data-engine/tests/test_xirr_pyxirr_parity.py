"""Paridad del XIRR con pyxirr frente a la bisección casera anterior.

``solve_xirr`` sustituye el bucle de bisección (200 iteraciones, tres NPV en
Python por iteración) por pyxirr (Rust). El contrato no cambia: el mismo
intervalo [-0,9999; 10], ``None`` cuando no hay raíz en él (el estado
``no_xirr_root``) y la misma tasa (a 1e-6) cuando la hay. Cuando pyxirr no
puede garantizar la MISMA raíz (sin cambio de signo, varias raíces posibles o
una respuesta fuera del intervalo) se usa la bisección de siempre.

``_legacy_bisection`` es una copia literal del código anterior de
``PortfolioIntelligenceService._xirr`` (a partir de ``origin = ...``) y es la
referencia de la paridad.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from app.services.portfolio_intelligence_service import solve_xirr


def _legacy_bisection(cashflows: list[tuple[date, float]]) -> float | None:
    origin = min(day for day, _ in cashflows)

    def npv(rate: float) -> float:
        return sum(value / ((1 + rate) ** ((day - origin).days / 365.0)) for day, value in cashflows)

    low, high = -0.9999, 10.0
    if npv(low) * npv(high) > 0:
        return None
    middle = low
    for _ in range(200):
        middle = (low + high) / 2
        if abs(npv(middle)) < 1e-8:
            break
        if npv(low) * npv(middle) <= 0:
            high = middle
        else:
            low = middle
    return middle


D0 = date(2020, 1, 1)


def _d(days: int) -> date:
    return D0 + timedelta(days=days)


def _monthly_dca(months: int, amount: float, final: float) -> list[tuple[date, float]]:
    flows = [(_d(30 * i), -amount) for i in range(months)]
    return [*flows, (_d(30 * months), final)]


def _random_portfolio(seed: int) -> list[tuple[date, float]]:
    rng = random.Random(seed)
    flows: list[tuple[date, float]] = []
    invested = 0.0
    for _ in range(rng.randint(3, 60)):
        day = _d(rng.randint(0, 3650))
        kind = rng.random()
        if kind < 0.6:
            amount = -round(rng.uniform(50, 5000), 2)
            invested -= amount
        elif kind < 0.8:
            amount = round(rng.uniform(1, 200), 2)  # dividendo
        elif kind < 0.9:
            amount = -round(rng.uniform(0.5, 15), 2)  # comisión
        else:
            amount = round(rng.uniform(100, 3000), 2)  # venta parcial
        flows.append((day, amount))
    flows.append((_d(3700), round(invested * rng.uniform(0.3, 2.5), 2)))
    return flows


CASES: dict[str, list[tuple[date, float]]] = {
    "compra_y_mantener_10pct": [(_d(0), -1000.0), (_d(365), 1100.0)],
    "venta_parcial_y_final": [(_d(0), -1000.0), (_d(200), 400.0), (_d(500), 800.0)],
    "dca_24_meses": _monthly_dca(24, 100.0, 2900.0),
    "dca_con_perdida": _monthly_dca(36, 250.0, 6000.0),
    "perdida_50pct": [(_d(0), -1000.0), (_d(365), 500.0)],
    "perdida_casi_total": [(_d(0), -1000.0), (_d(365), 1.0)],
    "ganancia_500pct": [(_d(0), -1000.0), (_d(365), 6000.0)],
    "ganancia_fuera_de_intervalo": [(_d(0), -1000.0), (_d(365), 20000.0)],
    "dos_dias_1pct": [(_d(0), -1000.0), (_d(2), 1010.0)],
    "tres_dias_5pct_fuera": [(_d(0), -1000.0), (_d(3), 1050.0)],
    "todo_negativo": [(_d(0), -1000.0), (_d(100), -500.0), (_d(365), -10.0)],
    "todo_positivo": [(_d(0), 1000.0), (_d(365), 1100.0)],
    "un_solo_flujo_negativo": [(_d(0), -1000.0)],
    "un_solo_flujo_positivo": [(_d(0), 1000.0)],
    "mismo_dia_suma_cero": [(_d(0), -100.0), (_d(0), 100.0)],
    "mismo_dia_suma_no_cero": [(_d(0), -100.0), (_d(0), 150.0)],
    "dos_cambios_de_signo_raiz_unica": [
        (_d(0), -1000.0),
        (_d(180), 600.0),
        (_d(400), -800.0),
        (_d(800), 1500.0),
    ],
    # Dos raíces (10 % y 20 %): el NPV tiene el mismo signo en los extremos,
    # así que ni antes ni ahora hay tasa (no_xirr_root).
    "dos_raices_10_y_20pct": [(_d(0), -100.0), (_d(365), 230.0), (_d(730), -132.0)],
    # Tres raíces (0 %, 10 % y 20 %): la bisección elige una de ellas.
    "tres_raices_0_10_20pct": [
        (_d(0), -1000.0 / (1.1 * 1.2)),
        (_d(365), 1000.0 * (1 / 1.1 + 1 / 1.2 + 1 / (1.1 * 1.2))),
        (_d(730), -1000.0 * (1 + 1 / 1.1 + 1 / 1.2)),
        (_d(1095), 1000.0),
    ],
    "importes_enormes": [(_d(0), -2.5e9), (_d(400), 1.0e9), (_d(900), 2.1e9)],
    "importes_diminutos": [(_d(0), -0.05), (_d(365), 0.06)],
    "orden_desordenado": [(_d(365), 1100.0), (_d(100), -300.0), (_d(0), -700.0)],
    "fechas_repetidas": [
        (_d(0), -500.0),
        (_d(0), -500.0),
        (_d(90), 10.0),
        (_d(90), -2.0),
        (_d(365), 1080.0),
    ],
    "veinte_anios": [(_d(0), -10000.0), (_d(7300), 40000.0)],
    "rentabilidad_cero": [(_d(0), -100.0), (_d(365), 100.0)],
    "perdida_20pct_con_dividendos": [
        (_d(0), -1000.0),
        (_d(90), 5.0),
        (_d(180), 5.0),
        (_d(270), 5.0),
        (_d(365), 785.0),
    ],
    "comisiones_y_retenciones": [
        (_d(0), -1004.5),
        (_d(120), 30.0),
        (_d(120), -4.5),
        (_d(300), -9.0),
        (_d(500), 1150.0),
    ],
}
for _seed in range(30):
    CASES[f"cartera_aleatoria_{_seed}"] = _random_portfolio(_seed)


@pytest.mark.parametrize("name", sorted(CASES))
def test_solve_xirr_matches_legacy_bisection(name: str) -> None:
    flows = CASES[name]
    expected = _legacy_bisection(flows)
    got, method = solve_xirr(flows)
    if expected is None:
        assert got is None, (name, got, method)
        return
    assert got is not None, (name, expected, method)
    assert got == pytest.approx(expected, abs=1e-6), (name, got, expected, method)


def test_simple_flows_use_pyxirr() -> None:
    rate, method = solve_xirr(CASES["compra_y_mantener_10pct"])
    assert method == "pyxirr"
    assert rate == pytest.approx(0.1, abs=1e-9)


def test_ambiguous_flows_fall_back_to_bisection() -> None:
    # Tres raíces (0 %, 10 % y 20 %): la bisección elige una de forma
    # determinista; pyxirr podría elegir otra, así que se mantiene la bisección.
    _, method = solve_xirr(CASES["tres_raices_0_10_20pct"])
    assert method == "bisection_xirr"
    # Sin cambio de signo neto (suma cero el mismo día): igual que antes.
    _, method = solve_xirr(CASES["mismo_dia_suma_cero"])
    assert method == "bisection_xirr"


def test_no_root_reports_none() -> None:
    assert solve_xirr(CASES["todo_negativo"]) == (None, "no_root")
    assert solve_xirr(CASES["ganancia_fuera_de_intervalo"]) == (None, "no_root")
    assert solve_xirr(CASES["dos_raices_10_y_20pct"]) == (None, "no_root")


def test_random_portfolios_mostly_take_the_fast_path() -> None:
    methods = [solve_xirr(CASES[f"cartera_aleatoria_{seed}"])[1] for seed in range(30)]
    assert methods.count("pyxirr") >= 20, methods
