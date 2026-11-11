"""Tasas base de la primera cifra publicada (point-in-time) y «¿con qué frecuencia lo consiguieron?»."""
from __future__ import annotations

import importlib.util
import json
import zipfile
from datetime import date
from pathlib import Path

from app.services.estimate_base_rates import BaseRate, lookup, share_reaching, table
from app.services.financial_health import HealthFact
from app.services.own_consensus import Actual, Candidate, Cell, attach_base_rate_checks, attach_margin_checks
from app.services.valuation_summary import _reverse_base_rate_check

GRID = [round(0.05 * i, 2) for i in range(1, 20)]
# p5 = −0,18 … p95 = +0,54, a pasos de 0,04: F(g) lineal entre ellos.
Q = [round(-0.18 + 0.04 * i, 4) for i in range(19)]
RATE = BaseRate(p25=-0.02, p50=0.18, p75=0.38, n=400, group="prueba · 1 año(s)", source="v2: fixture",
                p10=-0.14, p90=0.50, horizon=1, quantiles=tuple(Q), grid=tuple(GRID))


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "estimate_base_rates.py"
    spec = importlib.util.spec_from_file_location("estimate_base_rates_script", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_share_reaching_interpolates_inside_the_grid_and_bounds_outside() -> None:
    r = share_reaching(RATE, 0.18)  # p50
    assert r is not None and r.bound == "=" and abs(r.share - 0.5) < 1e-9 and r.text() == "el 50%"
    mid = share_reaching(RATE, 0.20)  # entre p50 (0,18) y p55 (0,22): F = 0,525
    assert mid is not None and abs(mid.share - 0.475) < 1e-9
    hi = share_reaching(RATE, 0.90)
    assert hi is not None and hi.bound == "<" and abs(hi.share - 0.05) < 1e-9 and hi.text() == "menos del 5%"
    lo = share_reaching(RATE, -0.50)
    assert lo is not None and lo.bound == ">" and abs(lo.share - 0.95) < 1e-9
    d = mid.as_dict(implied_formula="exige +20,0 %")
    assert d["n"] == 400 and d["horizon_years"] == 1 and d["formula"].startswith("exige +20,0 %; el 48%")
    assert "primera cifra publicada" in d["formula"]


def test_share_reaching_is_nd_without_grid_or_input() -> None:
    old = BaseRate(p25=0.0, p50=0.04, p75=0.09, n=120, group="v1", source="frames")
    assert share_reaching(old, 0.1) is None
    assert share_reaching(None, 0.1) is None
    assert share_reaching(RATE, None) is None


def test_lookup_carries_the_grid() -> None:
    data = {"version": "t", "source": "f", "grid": GRID, "groups": {"h5|*|*|*": {"growth": {
        "p10": -0.1, "p25": 0.0, "p50": 0.05, "p75": 0.1, "p90": 0.2, "n": 50, "q": Q}}}}
    r = lookup(horizon=5, revenue=1e9, prior_growth=0.1, data=data)
    assert r is not None and r.quantiles == tuple(Q) and r.grid == tuple(GRID) and r.horizon == 5
    assert lookup(horizon=4, revenue=1e9, prior_growth=0.1, data=data) is None  # plazo sin tabla: N/D


def test_shipped_table_is_point_in_time_from_companyfacts() -> None:
    data = table()
    assert "primera cifra publicada" in data["version"] and "companyfacts" in data["source"]
    assert data["grid"] == GRID
    for h in (1, 2, 3, 5, 7, 10):
        allg = data["groups"][f"h{h}|*|*|*"]["growth"]
        assert allg["n"] >= 1000 and len(allg["q"]) == 19 and allg["q"] == sorted(allg["q"])
    rev = data["revisions"]
    assert rev["cifras"] > 10_000 and 0 < rev["pct_reexpresadas"] < 0.5


def test_script_keeps_the_first_published_figure_within_400_days() -> None:
    mod = _script()
    units = [
        {"form": "10-K", "start": "2020-01-01", "end": "2020-12-31", "filed": "2021-02-20", "val": 100},
        {"form": "10-K", "start": "2020-01-01", "end": "2020-12-31", "filed": "2022-02-20", "val": 90},  # reexpresada
        {"form": "10-Q", "start": "2020-01-01", "end": "2020-12-31", "filed": "2021-01-05", "val": 1},  # no anual
        {"form": "10-K", "start": "2020-07-01", "end": "2020-12-31", "filed": "2021-02-20", "val": 50},  # 6 meses
        {"form": "10-K", "start": "2019-01-01", "end": "2019-12-31", "filed": "2022-02-20", "val": 80},  # tardía
    ]
    per = mod.annual_points(units)
    assert per["2020-12-31"] == ["2021-02-20", 100.0, "2022-02-20", 90.0]
    assert mod.yearly(per) == {2020: 100.0}  # 2019 solo aparece 3 años después: no es la original
    assert mod.yearly(per, mode="last") == {2020: 90.0, 2019: 80.0}
    # Ejercicio que cierra en enero (minoristas): cuenta como el año anterior.
    jan = mod.annual_points([{"form": "10-K", "start": "2020-02-02", "end": "2021-01-30", "filed": "2021-03-20",
                              "val": 7}])
    assert mod.yearly(jan) == {2020: 7.0}


def test_script_builds_groups_from_a_companyfacts_zip(tmp_path: Path, monkeypatch, capsys) -> None:
    mod = _script()
    monkeypatch.setattr(mod, "MIN_N", 1)
    zpath = tmp_path / "cf.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for cik in range(1, 4):
            usd = [{"form": "10-K", "start": f"{y}-01-01", "end": f"{y}-12-31", "filed": f"{y + 1}-02-15",
                    "val": 1e8 * 1.1 ** (y - 2010) * cik} for y in range(2010, 2021)]
            z.writestr(f"CIK{cik:010d}.json", json.dumps({"cik": cik, "facts": {"us-gaap": {
                "Revenues": {"units": {"USD": usd}}}}}))
    sector = tmp_path / "s.json"
    sector.write_text(json.dumps({"buckets": {"sector": ["manufactura"]}, "sector_by_cik": {"1": 0}}))
    mod.main([str(zpath), "--sector-json", str(sector), "--workers", "1"])
    out = json.loads(capsys.readouterr().out)
    g = out["groups"]["h1|*|*|*"]["growth"]
    assert abs(g["p50"] - 0.1) < 1e-3 and g["n"] == 3 * 7 and len(g["q"]) == 19
    assert out["sector_by_cik"] == {"1": out["buckets"]["sector"].index("manufactura")}
    assert out["revisions"]["reexpresadas_mas_0_5pct"] == 0


def _cell(period: str, mid: float, source: str = "analista_citado") -> Cell:
    return Cell("revenue", period, date(2027, 12, 31), "estimado", Candidate(source, None, mid, None, "f"), [], [], {})


def test_consensus_year_cells_get_the_share_that_reached_their_implied_growth() -> None:
    acts = {"fy2025": Actual("fy2025", date(2025, 12, 31), 1000.0, date(2026, 2, 1), "https://sec/x")}
    cells = {"fy2026": _cell("fy2026", 1200.0), "fy2027": _cell("fy2027", 1440.0),
             "q1_2026": Cell("revenue", "q1_2026", date(2026, 3, 31), "estimado",
                             Candidate("guia", None, 300.0, None, "g"), [], [], {})}
    seen: list[int] = []

    def rate_for(h: int) -> BaseRate | None:
        seen.append(h)
        return RATE
    attach_base_rate_checks(cells, acts, rate_for)
    chk = cells["fy2026"].base_rate_check
    assert chk is not None and abs(chk["growth"] - 0.2) < 1e-9 and abs(chk["share"] - 0.475) < 1e-9
    assert "fy2026 estimado 1,200 / fy2025 presentado 1,000" in chk["formula"] and chk["anchor"]["url"]
    nxt = cells["fy2027"].base_rate_check  # contra la celda estimada del año anterior
    assert nxt is not None and "fy2026 estimado 1,200" in nxt["formula"] and nxt["anchor"] is None
    assert cells["q1_2026"].base_rate_check is None and seen == [1, 1]
    assert cells["fy2026"].as_dict()["base_rate_check"]["n"] == 400


def test_year_with_reported_quarters_is_nd_with_reason() -> None:
    acts = {"fy2025": Actual("fy2025", date(2025, 12, 31), 1000.0),
            "q1_2026": Actual("q1_2026", date(2026, 3, 31), 280.0)}
    cells = {"fy2026": _cell("fy2026", 1200.0)}
    attach_base_rate_checks(cells, acts, lambda h: RATE)
    chk = cells["fy2026"].base_rate_check
    assert chk is not None and chk["share"] is None and "1 trimestre(s) ya presentado(s)" in chk["reason"]
    own = {"fy2026": _cell("fy2026", 1040.0, source="tasa_base")}
    attach_base_rate_checks(own, {"fy2025": Actual("fy2025", date(2025, 12, 31), 1000.0)}, lambda h: RATE)
    assert own["fy2026"].base_rate_check["share"] is None  # type: ignore[index]  # circular: no se compara
    none = {"fy2026": _cell("fy2026", 1200.0)}
    attach_base_rate_checks(none, {"fy2025": Actual("fy2025", date(2025, 12, 31), 1000.0)}, lambda h: None)
    assert none["fy2026"].base_rate_check is None  # sin tasa base: N/D


def test_reverse_dcf_check_uses_its_own_horizon_and_usd_revenue(monkeypatch) -> None:
    import app.services.estimate_base_rates as ebr

    monkeypatch.setattr(ebr, "for_annual_revenue", lambda annual, sector=None, horizon=1, **kw: RATE if horizon == 1 else None)

    class Co:
        cik = None
    facts = [HealthFact(1, "revenue", 2025, 1e9, "USD", date(2025, 12, 31), "u", "sec")]
    rev = {"status": "ok", "trace": {"horizon_years": 1}}
    out = _reverse_base_rate_check(Co(), facts, rev, 0.20)  # type: ignore[arg-type]
    assert out is not None and abs(out["share"] - 0.475) < 1e-9 and out["formula"].startswith("el precio exige")
    assert _reverse_base_rate_check(Co(), facts, {"status": "ok", "trace": {}}, 0.2) is None  # type: ignore[arg-type]
    assert _reverse_base_rate_check(Co(), facts, {"trace": {"horizon_years": 5}}, 0.2) is None  # type: ignore[arg-type]
    twd = [HealthFact(1, "revenue", 2025, 1e9, "TWD", date(2025, 12, 31), "u", "sec")]
    assert _reverse_base_rate_check(Co(), twd, rev, 0.2)["share"] is None  # type: ignore[arg-type,index]  # sin db: N/D
    assert _reverse_base_rate_check(Co(), facts, rev, None) is None  # type: ignore[arg-type]


MARGIN = BaseRate(p25=-0.03, p50=0.0, p75=0.03, n=500, group="márgenes · 1 año(s)", source="v2: fixture",
                  p10=-0.08, p90=0.08, metric="margin", horizon=1,
                  quantiles=tuple(round(-0.09 + 0.01 * i, 4) for i in range(19)), grid=tuple(GRID))


def test_operating_income_year_gets_the_share_that_expanded_margin_that_much() -> None:
    rev_a = {"fy2025": Actual("fy2025", date(2025, 12, 31), 1000.0)}
    oi_a = {"fy2025": Actual("fy2025", date(2025, 12, 31), 100.0)}  # margen 10 %
    rev_c = {"fy2026": _cell("fy2026", 1100.0)}
    oi_c = {"fy2026": Cell("operating_income", "fy2026", date(2026, 12, 31), "estimado",
                           Candidate("analista_citado", None, 132.0, None, "f"), [], [], {})}  # 12 %: +2 puntos
    attach_margin_checks(oi_c, oi_a, rev_c, rev_a, lambda h: MARGIN)
    chk = oi_c["fy2026"].base_rate_check
    assert chk is not None and chk["metric"] == "margin" and abs(chk["growth"] - 0.02) < 1e-9
    assert abs(chk["share"] - 0.40) < 1e-9 and "+2.0 puntos" in chk["formula"]
    assert "mejoró su margen operativo al menos +2.0 puntos" in chk["formula"]
    oi_a["q1_2026"] = Actual("q1_2026", date(2026, 3, 31), 30.0)
    attach_margin_checks(oi_c, oi_a, rev_c, rev_a, lambda h: MARGIN)
    assert oi_c["fy2026"].base_rate_check["share"] is None  # type: ignore[index]
