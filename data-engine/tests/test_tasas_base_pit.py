"""Tasas base point-in-time: la tabla del producto usa ingresos hasta 2019 y no sirve para valorar antes."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.valuation import shareholder_irr_rules as rules


def test_tabla_solo_conocida_despues_de_sus_datos():
    assert rules.base_rates_known_at(date(2015, 6, 30)) is None
    assert rules.base_rates_known_at(date(2019, 12, 31)) is None
    assert rules.base_rates_known_at(date(2020, 6, 30)) is rules.BASE_RATES


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backtest_irr_pit.py"
    spec = importlib.util.spec_from_file_location("backtest_irr_pit_script", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backtest_antes_de_2020_no_usa_la_tabla_del_producto():
    mod = _script()
    row = {"ticker": "X", "t": "2015-06-30", "status": "ok", "basis": "pe", "sic": 3571, "multiple": 15.0,
           "revenue": 100.0, "rev_hist": {}, "inputs": SimpleNamespace(start=SimpleNamespace(basis="pe"))}
    seen: list[dict] = []
    mod.bt.value = lambda inp, peer_multiples=(): seen.append(dict(rules.BASE_RATES)) or dict.fromkeys(("bear", "base", "bull", "bear_10", "base_10", "bull_10", "weighted"), 0.0)
    out = mod.value_date(("2015-06-30", [row], False))
    # antes: se valoraba con la tabla de 2010–2019 (información futura); ahora, sin observaciones previas,
    # con la tabla vacía (la regla usa su respaldo 0 / 3 / 6 %)
    assert seen == [{}] and out[0]["base_rates"] == "sin_datos_previos"
    assert rules.BASE_RATES  # la tabla del producto se restaura
    out = mod.value_date(("2021-06-30", [{**row, "t": "2021-06-30"}], False))
    assert seen[-1] == rules.BASE_RATES and out[0]["base_rates"] == "producto"
