"""Tesis v2 con insiders (#4751) y estimaciones citadas de analistas (#4753) como marcadores y tablas.

Antes: la sección 4 (directivos y capital) no veía los Form 4 que GerarAI ya resume (compras y ventas en
mercado a 3/6/12 meses, compras en grupo, presentaciones tarde) y la 8 bis no veía las estimaciones que la
recogida de prensa guarda por firma (ASTS: Clear Street 115 $, Deutsche 93, Piper 54, Scotiabank 55,70).
"""
from __future__ import annotations

from app.services.expert_team import thesis_v2 as T
from tests.test_irr_tipo_empresa import _runway_val


def _side(trades: int, value: float, plan: int = 0) -> dict:
    return {"trades": trades, "insiders": trades, "shares": 0.0, "value": value, "value_missing": 0, "planned_10b5_1": plan}


def _ctx():
    val = _runway_val()
    insiders = {"status": "ok", "windows": [
        {"days": 90, "buys": _side(0, 0.0), "sells": _side(3, 2_000_000.0, 3), "net_value": -2_000_000.0},
        {"days": 365, "buys": _side(2, 5_700_000.0), "sells": _side(4, 3_000_000.0, 2), "net_value": 2_700_000.0}],
        "clusters": [{"end": "2026-05-01"}], "late": {"filings": 175, "late": 0}}
    analysts = [{"firm": "Clear Street", "metric": "revenue", "year": 2027, "value": 557.0, "as_of": "2026-10-14", "url": "https://example.org/a"},
                {"firm": "Deutsche Bank", "metric": "revenue", "year": 2027, "value": 400.0, "as_of": "2026-10-01", "url": "https://example.org/b"}]
    targets = [{"firm": "Piper", "target": 54.0, "currency": "USD", "date": "2026-10-02", "url": "https://example.org/c"},
               {"firm": "Clear Street", "target": 115.0, "currency": "USD", "date": "2026-10-14", "url": "https://example.org/d"}]
    return T.ThesisContext("ZZZ", "Zeta", val, [], [], T.kill_switches(val, []), None, [], insiders=insiders,
                           analysts=analysts, price_targets=targets)


def test_marcadores_de_insiders_y_analistas():
    m = T.thesis_markers(_ctx())
    assert m["insiders.12m.compras"] == "2" and m["insiders.12m.neto"].startswith("2,7")
    assert m["insiders.3m.ventas_plan"] == "3" and m["insiders.compras_grupo"] == "1" and m["insiders.tarde"] == "0"
    assert m["analistas.firmas_precio"] == "2" and m["analistas.precio_max"].startswith("115")
    assert m["analistas.revenue.2027.n"] == "2" and m["analistas.revenue.2027.mediana"].startswith("478")


def test_tablas_con_enlace_por_fila():
    tb = T.tables(_ctx())
    assert [r[0] for r in tb["insiders"]["rows"]][:2] == ["90 días", "365 días"]
    assert len(tb["analistas"]["rows"]) == 4 and all(tb["analistas"]["links"])
    secs = {k: tabs for k, _t, _p, tabs in T.SECTIONS}
    assert "insiders" in secs["directivos_capital"] and "analistas" in secs["consenso_guia"]
