"""Tasas base medidas en SEC: grupo más fino con muestra suficiente y relajación en orden fijo."""
from __future__ import annotations

from app.services.estimate_base_rates import MIN_N, for_annual_revenue, lookup, sector_of_cik, table


def _item(p50: float, n: int) -> dict:
    return {"p10": p50 - 0.2, "p25": p50 - 0.05, "p50": p50, "p75": p50 + 0.05, "p90": p50 + 0.2, "n": n}


DATA = {"version": "prueba", "source": "fixture", "buckets": {"sector": ["manufactura"]}, "groups": {
    "h1|1B-10B|5-10 %|manufactura": {"growth": _item(0.06, MIN_N)},
    "h1|1B-10B|5-10 %|*": {"growth": _item(0.05, 200)},
    "h1|*|> 20 %|*": {"growth": _item(0.12, 500)},
    "h1|*|*|*": {"growth": _item(0.04, 9000), "margin": _item(0.0, 8000)},
    "h1|<100M|> 20 %|*": {"growth": _item(0.3, MIN_N - 1)},
}}


def test_finest_group_with_enough_sample_wins() -> None:
    r = lookup(revenue=2e9, prior_growth=0.07, sector="manufactura", data=DATA)
    assert r is not None and r.p50 == 0.06 and "sector manufactura" in r.group
    r2 = lookup(revenue=2e9, prior_growth=0.07, sector="servicios", data=DATA)
    assert r2 is not None and r2.p50 == 0.05 and "sector" not in r2.group


def test_small_groups_relax_to_prior_growth_then_all() -> None:
    r = lookup(revenue=5e7, prior_growth=0.4, sector=None, data=DATA)  # su grupo tiene n < MIN_N
    assert r is not None and r.p50 == 0.12 and r.group.startswith("crecimiento previo > 20 %")
    r_all = for_annual_revenue({}, data=DATA)
    assert r_all is not None and r_all.p50 == 0.04 and r_all.group.startswith("todas")


def test_company_group_from_its_annual_revenue() -> None:
    r = for_annual_revenue({2022: 1.5e9, 2025: 1.5e9 * 1.07 ** 3}, sector="manufactura", data=DATA)
    assert r is not None and r.p50 == 0.06 and r.source.startswith("prueba")


def test_shipped_table_is_measured_on_sec_data() -> None:
    data = table()
    allg = data["groups"]["h1|*|*|*"]["growth"]
    assert allg["n"] > 10_000 and -0.05 < allg["p50"] < 0.15
    assert "data.sec.gov" in data["source"] and data["rule"]
    assert allg["p10"] < allg["p25"] < allg["p50"] < allg["p75"] < allg["p90"]
    assert sector_of_cik("945841") is not None  # POOL (SIC 5090, mayorista)
