"""Modelo de BPA del consenso propio (``bpa_escala_beneficio_operativo v1``)."""
from __future__ import annotations

from datetime import date

from app.services.estimate_base_rates import BaseRate
from app.services.own_consensus import actuals_from_facts, build_cells

TODAY = date(2026, 2, 15)
RATE = BaseRate(group="prueba", p25=0.0, p50=0.05, p75=0.10, n=100, source="prueba")


def _series(metric: str, values: dict[str, float]) -> dict:
    return actuals_from_facts([(k, v, None, f"https://www.sec.gov/{metric}/{k}") for k, v in values.items()],
                              metric=metric)


def _oi_quarters(scale: float = 1.0) -> dict[str, float]:
    out: dict[str, float] = {}
    for y in (2022, 2023, 2024, 2025):
        for q, m in ((1, "03-31"), (2, "06-30"), (3, "09-30"), (4, "12-31")):
            out[f"{y}-{m}:Q{q}"] = scale * (100.0 + 5 * (y - 2022) * 4 + q)
        out[f"{y}-12-31:FY"] = sum(v for k, v in out.items() if k.startswith(str(y)) and k.endswith(("Q1", "Q2", "Q3", "Q4")))
    return out


def _cells(eps_values: dict[str, float], oi_scale: float = 1.0) -> dict:
    oi = _series("operating_income", _oi_quarters(oi_scale))
    rev = _series("revenue", _oi_quarters(10.0))
    rev_cells = build_cells("revenue", rev, today=TODAY, base_rate=RATE)
    oi_cells = build_cells("operating_income", oi, today=TODAY, base_rate=RATE, revenue_cells=rev_cells,
                           revenue_actuals=rev)
    eps = _series("eps", eps_values)
    return build_cells("eps", eps, today=TODAY, base_rate=None, operating_cells=oi_cells, operating_actuals=oi), oi_cells


def test_eps_scales_with_operating_income_estimate() -> None:
    eps, oi_cells = _cells({"2024-12-31:FY": 4.0, "2025-12-31:FY": 5.0, "2025-03-31:Q1": 1.2})
    fy = eps["fy2026"]
    assert fy.status == "estimado" and fy.published is not None and fy.published.source == "modelo"
    oi_est = oi_cells["fy2026"].published
    oi_prev = sum(_oi_quarters()[f"2025-{m}:Q{q}"] for q, m in ((1, "03-31"), (2, "06-30"), (3, "09-30"), (4, "12-31")))
    assert abs(fy.published.mid - 5.0 * oi_est.mid / oi_prev) < 1e-9
    assert "acciones, intereses e impuestos constantes" in fy.published.formula
    kinds = [c["kind"] for c in fy.published.citations]
    assert kinds.count("dato_presentado") == 2 and "estimacion_beneficio_operativo" in kinds
    # el año +2 encadena las dos estimaciones publicadas del año anterior
    fy2 = eps["fy2027"]
    assert fy2.published is not None and "fy2026 estimado" in fy2.published.formula
    # trimestre con su mismo trimestre del año anterior
    assert eps["q1_2026"].published is not None and eps["q1_2026"].published.mid > 1.2


def test_eps_loss_or_missing_anchor_stays_without_estimate() -> None:
    eps, _ = _cells({"2024-12-31:FY": -1.0, "2025-12-31:FY": -0.5})
    assert eps["fy2026"].published is None and eps["fy2026"].status == "sin_estimacion"
    eps, _ = _cells({"2024-12-31:FY": 4.0, "2025-12-31:FY": 5.0}, oi_scale=-1.0)
    assert eps["fy2026"].published is None
    # sin BPA del trimestre anterior no se inventa el 4T
    eps, _ = _cells({"2024-12-31:FY": 4.0, "2025-12-31:FY": 5.0})
    assert eps["q4_2026"].published is None


def test_without_operating_cells_eps_behaves_as_before() -> None:
    eps = build_cells("eps", _series("eps", {"2024-12-31:FY": 4.0, "2025-12-31:FY": 5.0}), today=TODAY)
    assert all(c.published is None for c in eps.values())


def test_q4_eps_derived_from_year_minus_nine_months() -> None:
    # bpa_4t_año_menos_9m v1: el 10-K no da el BPA del 4T; 4T ≈ año − 9M, marcado aproximado.
    vals = {"2024-12-31:FY": 4.0, "2025-12-31:FY": 5.0, "2025-03-31:Q1": 1.2, "2025-06-30:Q2": 1.2,
            "2025-09-30:Q3": 1.25}
    eps, oi_cells = _cells(vals)
    q4 = eps["q4_2026"]
    assert q4.published is not None and q4.published.source == "modelo"
    oi_q4_prev = _oi_quarters()["2025-12-31:Q4"]
    assert abs(q4.published.mid - 1.35 * oi_cells["q4_2026"].published.mid / oi_q4_prev) < 1e-9
    assert "q4_2025 derivado" in q4.published.formula and "aproximado" in q4.published.formula
    kinds = [c["kind"] for c in q4.published.citations]
    assert "dato_derivado" in kinds


def test_q4_eps_not_derived_when_inconsistent() -> None:
    from app.services.own_consensus import derived_q4_eps
    oi = _series("operating_income", _oi_quarters())
    # división de acciones no reexpresada en los 10-Q: el 9M supera al año → sin estimación
    split = _series("eps", {"2025-12-31:FY": 5.0, "2025-03-31:Q1": 2.4, "2025-06-30:Q2": 2.4,
                            "2025-09-30:Q3": 2.5})
    assert derived_q4_eps("q4_2025", split, oi) is None
    # peso del 4T muy distinto al del beneficio operativo (×2 o más) → sin estimación
    odd = _series("eps", {"2025-12-31:FY": 5.0, "2025-03-31:Q1": 0.4, "2025-06-30:Q2": 0.4,
                          "2025-09-30:Q3": 0.4})
    assert derived_q4_eps("q4_2025", odd, oi) is None
    # falta un trimestre → sin estimación
    gap = _series("eps", {"2025-12-31:FY": 5.0, "2025-03-31:Q1": 1.2, "2025-09-30:Q3": 1.25})
    assert derived_q4_eps("q4_2025", gap, oi) is None
    ok = _series("eps", {"2025-12-31:FY": 5.0, "2025-03-31:Q1": 1.2, "2025-06-30:Q2": 1.2,
                         "2025-09-30:Q3": 1.25})
    d = derived_q4_eps("q4_2025", ok, oi)
    assert d is not None and d.derived and abs(d.value - 1.35) < 1e-9
