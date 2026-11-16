"""Regresiones del backtest PIT sin sesgo de supervivencia (``scripts/dca_backtest_pit.py``).

Universo sintetico: una ganadora (WIN, datos completos) y una quebrada (DEAD,
datos hasta 2008-06 y desaparece). El filtro antiguo (``all(m in s.first...)``)
excluia a DEAD: estas pruebas fijan que ya no.
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

from app.services.dca_signal_engine import DailyBar
from scripts import dca_backtest_pit as bt
from scripts import pit_exits as px

T0 = 2008 * 12  # 2008-01
MONTHS = list(range(T0, T0 + 12))  # 2008-01 .. 2008-12


def _bars(rets, start=100.0, day0=date(2005, 1, 3)):
    out = []
    price = start
    for i, r in enumerate(rets):
        y, m = divmod(day0.month - 1 + i, 12)
        first = price
        price = price * (1 + r)
        out.append(DailyBar(day=date(day0.year + y, m + 1, 3), close=first))
        out.append(DailyBar(day=date(day0.year + y, m + 1, 20), close=price))
    return out


def _series(sym, rets, **kw):
    return bt.build_series(sym, _bars(rets, **kw))


def _winner():
    # 60 meses 2005-01..2009-12: cubre toda la ventana con nivel en t0-1.
    return _series("WIN", [0.02] * 60)


def _dead():
    # 42 meses 2005-01..2008-06: desaparece a mitad de la ventana.
    return _series("DEAD", [0.01] * 42)


def test_elegibilidad_conserva_la_quebrada():
    win, dead = _winner(), _dead()
    out = bt.run_benchmark([win, dead], _winner(), MONTHS, portfolios=2, sizes=(2,), seed=3)
    assert out["eligible"] == 2
    # Regresion: el filtro antiguo exigia precio en todos los meses y la quitaba.
    assert not all(m in dead.first for m in MONTHS)
    assert T0 in dead.first and (T0 - 1) in dead.level


def test_anadir_quiebra_en_t_no_cambia_resultados_previos():
    win, dead = _winner(), _dead()
    sin_evento = bt.simulate([win, dead], MONTHS, strategy="plano", exits={})
    ev = px.ExitEvent("DEAD", T0 + 5, "bankruptcy", -1.0)  # last_month 2008-06
    con_evento = bt.simulate([win, dead], MONTHS, strategy="plano", exits={"DEAD": ev})
    # La baja se ejecuta el mes siguiente a su ultimo precio (2008-07) y hasta
    # entonces ambas carteras son identicas (indices 0..5 = 2008-01..06).
    assert con_evento.exits_log[0]["symbol"] == "DEAD"
    assert con_evento.exits_log[0]["month"] == "2008-07"
    assert sin_evento.curve[:6] == con_evento.curve[:6]


def test_elegibilidad_no_depende_de_precios_posteriores():
    dead = _dead()
    kw = dict(
        has_price_at={"DEAD": T0 in dead.first},
        level_prev={"DEAD": (T0 - 1) in dead.level},
        first_filing={"DEAD": None},
        membership=None,
    )
    antes = px.eligible_at(["DEAD"], T0, **kw)
    # Truncar todo lo posterior a t0 (fuga de universo simulada).
    dead.first = {m: v for m, v in dead.first.items() if m <= T0}
    dead.last = {m: v for m, v in dead.last.items() if m <= T0}
    despues = px.eligible_at(["DEAD"], T0, **kw)
    assert antes == despues == ["DEAD"]


def test_hueco_de_dos_meses_no_cierra_la_posicion():
    bars = [b for b in _bars([0.01] * 60) if not (date(2008, 3, 1) <= b.day <= date(2008, 4, 30))]
    gap = bt.build_series("GAP", bars)
    assert T0 + 2 not in gap.first and T0 + 3 not in gap.first  # hueco 2008-03/04
    r = bt.simulate([_winner(), gap], MONTHS, strategy="plano", exits={})
    assert r.exits_log == []


def test_evento_posterior_a_los_precios_no_se_adelanta():
    # Datos hasta 2008-06 pero evento con last_month 2008-10: salir en julio
    # aplicaria 3 meses antes un dato que aun no existia (mirar al futuro).
    win, dead = _winner(), _dead()
    ev = px.ExitEvent("DEAD", T0 + 9, "acquired", 0.1)  # last_month 2008-10
    r = bt.simulate([win, dead], MONTHS, strategy="plano", exits={"DEAD": ev})
    assert r.exits_log[0]["month"] == "2008-11"
    assert all(e["month"] != "2008-07" for e in r.exits_log)


def test_evento_anterior_a_los_precios_manda_sobre_la_serie():
    # Evento con last_month 2008-03 aunque haya precios hasta 2008-06: la salida
    # es en 2008-04, no en 2008-07 (la fecha del evento es el dato).
    win, dead = _winner(), _dead()
    ev = px.ExitEvent("DEAD", T0 + 2, "bankruptcy", -1.0)  # last_month 2008-03
    r = bt.simulate([win, dead], MONTHS, strategy="plano", exits={"DEAD": ev})
    assert r.exits_log[0]["month"] == "2008-04"


def test_signo_estricto_cero_no_es_concluyente_contra_signo():
    assert bt._mismo_signo_estricto(0.05, 0.01)
    assert bt._mismo_signo_estricto(0.0, 0.0)
    assert not bt._mismo_signo_estricto(0.0, 0.05)
    assert not bt._mismo_signo_estricto(0.0, -0.05)
    assert not bt._mismo_signo_estricto(-0.02, 0.05)


def test_sensibilidad_ejecuta_la_cota_que_falta_y_etiqueta_bien(monkeypatch):
    # Base ejecutada con --unknown-exit 0.0: la cota inferior (-1.0) NO puede
    # heredar el diff de la superior (regresion del hallazgo del auditor).
    calls = []

    def fake_run(universe, spy, months, **kw):
        calls.append(kw.get("unknown_exit"))
        return {"app_vs_plano": {"irr_diff_median": -0.02}}

    monkeypatch.setattr(bt, "run_benchmark", fake_run)
    out = bt.unknown_exit_sensitivity(
        [],
        None,
        MONTHS,
        portfolios=1,
        sizes=(1,),
        seed=1,
        membership=None,
        exits=None,
        chosen_unknown=0.0,
        chosen_diff=0.05,
    )
    assert calls == [-1.0]  # solo ejecuta la cota que falta
    assert out["irr_diff_median_cota_inferior"] == -0.02  # de la ejecucion con -1.0
    assert out["irr_diff_median_cota_superior"] == 0.05  # la base elegida
    assert out["concluyente"] is False


def test_misma_semilla_mismo_json():
    win, dead = _winner(), _dead()
    kw = dict(portfolios=2, sizes=(2,), seed=99)
    a = bt.run_benchmark([win, dead], _winner(), MONTHS, **kw)
    b = bt.run_benchmark([win, dead], _winner(), MONTHS, **kw)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_tir_cota_inferior_menor_o_igual_que_superior():
    win, dead = _winner(), _dead()
    inf = bt.simulate([win, dead], MONTHS, strategy="plano", exits={}, unknown_exit=-1.0)
    sup = bt.simulate([win, dead], MONTHS, strategy="plano", exits={}, unknown_exit=0.0)
    assert inf.irr <= sup.irr
    assert inf.exits_log[0]["exit_return"] == -1.0
    assert sup.exits_log[0]["exit_return"] == 0.0


def test_sin_bajas_ni_costes_no_cambia_el_resultado():
    a, b = _series("AAA", [0.02] * 60), _series("BBB", [0.015] * 60)
    r0 = bt.simulate([a, b], MONTHS, strategy="plano", cost=0.0)
    r_def = bt.simulate([a, b], MONTHS, strategy="plano")
    assert r0.exits_log == [] and r_def.exits_log == []
    assert r0.irr >= r_def.irr  # sin comision, igual o mejor; nada se cierra
    assert r0.monthly_returns != [] and len(r0.curve) == len(MONTHS)


def _write_px_csv(path: Path, rets, start=100.0):
    rows = ["Date,Close"]
    price = start
    for i, r in enumerate(rets):
        y, m = divmod(i, 12)
        first = price
        price = price * (1 + r)
        rows.append(f"{2005 + y}-{m + 1:02d}-03,{first:.6f}")
        rows.append(f"{2005 + y}-{m + 1:02d}-20,{price:.6f}")
    path.write_text("\n".join(rows) + "\n")


def _write_sec(path: Path):
    facts = {"facts": {"us-gaap": {"Assets": {"units": {"USD": [{"filed": "2004-02-15"}]}}}}}
    with gzip.open(path, "wt") as fh:
        json.dump(facts, fh)


def test_main_end_to_end_con_bajas_y_membresia(tmp_path):
    pxdir = tmp_path / "px"
    secdir = tmp_path / "sec"
    pxdir.mkdir()
    secdir.mkdir()
    _write_px_csv(pxdir / "WIN.csv", [0.02] * 60)
    _write_px_csv(pxdir / "DEAD.csv", [0.01] * 42)
    _write_px_csv(pxdir / "SPY.csv", [0.008] * 60)
    for sym in ("WIN", "DEAD", "SPY"):
        _write_sec(secdir / f"{sym}.json.gz")
    (tmp_path / "symbols.txt").write_text("WIN\nDEAD\n")
    (tmp_path / "membership.csv").write_text("symbol,start,end\nWIN,2005-01,\nDEAD,2005-01,2008-06\n")
    (tmp_path / "exits.csv").write_text("symbol,last_month,kind,exit_return\nDEAD,2008-06,bankruptcy,\n")
    out = tmp_path / "out.json"
    rc = bt.main(
        [
            "--px",
            str(pxdir),
            "--sec",
            str(secdir),
            "--symbols",
            str(tmp_path / "symbols.txt"),
            "--start",
            "2008-01",
            "--end",
            "2008-12",
            "--portfolios",
            "2",
            "--sizes",
            "2",
            "--leak-samples",
            "5",
            "--membership",
            str(tmp_path / "membership.csv"),
            "--exits",
            str(tmp_path / "exits.csv"),
            "--wf-train",
            "6",
            "--wf-test",
            "3",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["eligible"] == 2  # la quebrada sigue en el universo
    assert rep["strategies"]["app"]["exits_median"] >= 1  # la baja se ejecuta
    assert rep["sensibilidad_unknown_exit"]["concluyente"] in (True, False)
    assert set(rep["costes_bps"]) == {"5_bps", "10_bps", "25_bps"}
    assert len(rep["walk_forward"]["folds"]) == 2
    assert len(rep["data_hash"]) == 64
    assert rep["unknown_exit"] == -1.0
