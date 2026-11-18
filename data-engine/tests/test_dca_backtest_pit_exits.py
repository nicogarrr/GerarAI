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

import pytest

from app.services.dca_signal_engine import DailyBar
from scripts import dca_backtest_pit as bt
from scripts import pit_exits as px

T0 = 2008 * 12  # 2008-01
MONTHS = list(range(T0, T0 + 12))  # 2008-01 .. 2008-12


def _gz(payload: bytes) -> bytes:
    """gzip determinista. ``gzip.compress`` sin ``mtime`` escribe ``time.time()`` en la
    cabecera: dos compresiones del mismo contenido en segundos distintos dan bytes
    distintos y ``_data_hash`` (que hashea los bytes) cambia. Flaky medido en CI #5887:
    el test reescribe el mismo companyfacts y cruzar un limite de segundo rompia la
    igualdad de hash."""
    return gzip.compress(payload, mtime=0)


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


def test_salida_al_cierre_del_ultimo_mes_no_al_open():
    # Contrato: el retorno de salida es sobre el ULTIMO CIERRE, no sobre el
    # primer cierre (open) del mes. _bars pone open=px y close=px*(1+r).
    win, dead = _winner(), _dead()
    ev = px.ExitEvent("DEAD", T0 + 5, "acquired", 0.0)  # last_month 2008-06, ret 0
    r = bt.simulate([win, dead], MONTHS, strategy="plano", exits={"DEAD": ev}, cost=0.0)
    shares = sum(100.0 / dead.first[m] for m in range(T0, T0 + 6))
    expected = shares * dead.last[T0 + 5]  # cierre de 2008-06, no el open
    assert r.exits_log[0]["exit_price"] == pytest.approx(dead.last[T0 + 5])
    assert r.exits_log[0]["recovered"] == pytest.approx(expected, abs=0.01)


def test_baja_inferida_es_supuesto_e_invariante_a_un_precio_futuro():
    """Regresión independiente (auditor): la serie muerta acaba 2008-06 SIN
    evento -> la baja se infiere en 2008-09 (3+ meses sin precio, gracia 2)
    con la etiqueta «(supuesto)»; y añadir un precio en 2008-10 (futuro
    respecto a la decisión) no cambia ni el exits_log ni la curva."""
    win, dead = _winner(), _dead()
    r = bt.simulate([win, dead], MONTHS, strategy="plano", exits={})
    assert r.exits_log[0]["symbol"] == "DEAD"
    assert r.exits_log[0]["month"] == "2008-09"
    assert r.exits_log[0]["kind"] == "unknown (supuesto)"

    barras = [b for b in _bars([0.01] * 46) if not (date(2008, 7, 1) <= b.day <= date(2008, 9, 30))]
    dead_con_octubre = bt.build_series("DEAD", barras)
    assert any(m == T0 + 9 for m in dead_con_octubre.first)  # 2008-10 existe
    r2 = bt.simulate([win, dead_con_octubre], MONTHS, strategy="plano", exits={})
    # PIT: en 2008-09 el precio de octubre aún no existía; la baja y toda la
    # curva son idénticas (la posición cerrada nunca se recompra).
    assert r2.exits_log == r.exits_log
    assert r2.curve == r.curve


def test_un_precio_posterior_no_cambia_el_patrimonio_previo():
    # PIT: anadir un precio en 2008-09 no puede cambiar julio.
    win = _winner()
    dead_a = _dead()
    bars_b = _bars([0.01] * 42) + [DailyBar(day=date(2008, 9, 15), close=150.0)]
    dead_b = bt.build_series("DEAD", bars_b)
    ra = bt.simulate([win, dead_a], MONTHS, strategy="plano")
    rb = bt.simulate([win, dead_b], MONTHS, strategy="plano")
    assert ra.curve[:7] == rb.curve[:7]  # enero-julio identicos


def test_evento_no_recompra_tras_la_baja():
    # Evento en 2008-03 con CSV que sigue hasta diciembre: una sola salida
    # (2008-04) y el valor nunca vuelve a ser comprable.
    win = _winner()
    dead = _series("DEAD", [0.01] * 48)  # datos hasta 2008-12
    ev = px.ExitEvent("DEAD", T0 + 2, "bankruptcy", -1.0)
    r = bt.simulate([win, dead], MONTHS, strategy="plano", exits={"DEAD": ev})
    assert len(r.exits_log) == 1  # una sola salida: nunca se recompra tras la baja
    assert r.exits_log[0]["month"] == "2008-04"


def test_nan_o_infinito_en_exit_return_se_rechaza(tmp_path):
    for raw in ("NaN", "nan", "inf", "-inf"):
        f = tmp_path / "x.csv"
        f.write_text(f"symbol,last_month,kind,exit_return\nX,2012-03,bankruptcy,{raw}\n")
        with pytest.raises(ValueError, match="no finito"):
            px.load_exits(f)


def test_retorno_inferido_es_supuesto_y_varia_entre_cotas(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("symbol,last_month,kind,exit_return\nDEAD,2008-06,bankruptcy,\n")
    exits = px.load_exits(f)
    assert exits["DEAD"].inferred is True
    win, dead = _winner(), _dead()
    inf = bt.simulate([win, dead], MONTHS, strategy="plano", exits=exits, unknown_exit=-1.0, cost=0.0)
    sup = bt.simulate([win, dead], MONTHS, strategy="plano", exits=exits, unknown_exit=0.0, cost=0.0)
    assert inf.exits_log[0]["kind"] == "bankruptcy (supuesto)"
    assert inf.exits_log[0]["recovered"] == 0.0
    assert sup.exits_log[0]["recovered"] > 0.0  # la cota superior SI varia el supuesto
    assert inf.irr <= sup.irr


def test_filing_posterior_a_t0_entra_en_folds_posteriores():
    # El universo ya no se filtra al t0 global: LATE presenta en 2008-07, asi que
    # no es elegible en la ventana pero SI en el primer fold (test 2008-07..09).
    win = _winner()
    late = _series("LATE", [0.02] * 60)
    late.eligible_from = T0 + 6
    base = bt.run_benchmark([win, late], _winner(), MONTHS, portfolios=1, sizes=(1,), seed=1)
    assert base["eligible"] == 1
    wf = bt.walk_forward_report(
        [win, late],
        _winner(),
        MONTHS,
        train=6,
        test=3,
        portfolios=1,
        sizes=(1,),
        seed=1,
        membership=None,
        exits=None,
        unknown_exit=-1.0,
    )
    assert wf["folds"][0]["test_window"][0] == "2008-07"
    assert wf["folds"][0]["eligible"] == 2


def test_data_hash_cubre_spy_sec_simbolos_y_config(tmp_path):
    pxdir = tmp_path / "px"
    secdir = tmp_path / "sec"
    pxdir.mkdir()
    secdir.mkdir()
    (pxdir / "WIN.csv").write_text("Date,Close\n2005-01-03,100\n")
    (pxdir / "SPY.csv").write_text("Date,Close\n2005-01-03,20\n")
    (secdir / "WIN.json.gz").write_bytes(_gz(b'{"facts": {}}'))
    syms = tmp_path / "symbols.txt"
    syms.write_text("WIN\n")
    cfg = {"seed": 1, "start": "2008-01"}
    base = bt._data_hash([pxdir], [secdir], ["WIN", "SPY"], syms, None, None, cfg)
    # SPY distinto -> hash distinto (regresion del hallazgo del auditor).
    (pxdir / "SPY.csv").write_text("Date,Close\n2005-01-03,2000\n")
    assert bt._data_hash([pxdir], [secdir], ["WIN", "SPY"], syms, None, None, cfg) != base
    # companyfacts distinto -> hash distinto.
    (pxdir / "SPY.csv").write_text("Date,Close\n2005-01-03,20\n")
    (secdir / "WIN.json.gz").write_bytes(_gz(b'{"facts": {"x": 1}}'))
    assert bt._data_hash([pxdir], [secdir], ["WIN", "SPY"], syms, None, None, cfg) != base
    # config distinta -> hash distinto; entrada identica -> mismo hash.
    (secdir / "WIN.json.gz").write_bytes(_gz(b'{"facts": {}}'))
    assert bt._data_hash([pxdir], [secdir], ["WIN", "SPY"], syms, None, None, {**cfg, "seed": 2}) != base
    assert bt._data_hash([pxdir], [secdir], ["WIN", "SPY"], syms, None, None, cfg) == base


def test_data_hash_igualdad_no_depende_del_segundo_en_que_se_escribe_el_gz(tmp_path, monkeypatch):
    # Reloj que avanza 1 s por llamada: antes de _gz, la misma entrada escrita dos
    # veces daba hashes distintos (mtime en la cabecera gzip).
    import time as _time

    clock = [1_700_000_000.0]

    def tick():
        clock[0] += 1.0
        return clock[0]

    monkeypatch.setattr(_time, "time", tick)
    pxdir, secdir = tmp_path / "px", tmp_path / "sec"
    pxdir.mkdir()
    secdir.mkdir()
    (pxdir / "WIN.csv").write_text("Date,Close\n2005-01-03,100\n")
    syms = tmp_path / "symbols.txt"
    syms.write_text("WIN\n")
    (secdir / "WIN.json.gz").write_bytes(_gz(b'{"facts": {}}'))
    first = bt._data_hash([pxdir], [secdir], ["WIN"], syms, None, None, {"seed": 1})
    (secdir / "WIN.json.gz").write_bytes(_gz(b'{"facts": {}}'))
    assert bt._data_hash([pxdir], [secdir], ["WIN"], syms, None, None, {"seed": 1}) == first


def test_data_hash_cubre_todos_los_candidatos_y_el_orden(tmp_path):
    # Regresion auditor: load_universe elige el CSV de inicio mas temprano y el
    # primer companyfacts en orden CLI; el hash debe cambiar al tocar CUALQUIER
    # candidato (usado o no) y al permutar el orden de --px/--sec.
    z, a = tmp_path / "z", tmp_path / "a"
    zsec, asec = tmp_path / "zsec", tmp_path / "asec"
    for d in (z, a, zsec, asec):
        d.mkdir()
    (z / "WIN.csv").write_text("Date,Close\n2006-01-03,1\n")
    (a / "WIN.csv").write_text("Date,Close\n2005-01-03,1\n")  # inicio mas temprano: el usado
    (zsec / "WIN.json.gz").write_bytes(_gz(b'{"facts": {}}'))
    (asec / "WIN.json.gz").write_bytes(_gz(b'{"facts": {"y": 2}}'))
    syms = tmp_path / "symbols.txt"
    syms.write_text("WIN\n")
    cfg = {"seed": 1}
    base = bt._data_hash([z, a], [zsec, asec], ["WIN"], syms, None, None, cfg)
    # Tocar el candidato NO usado (z tiene inicio posterior) cambia el hash.
    (z / "WIN.csv").write_text("Date,Close\n2006-01-03,2\n")
    assert bt._data_hash([z, a], [zsec, asec], ["WIN"], syms, None, None, cfg) != base
    (z / "WIN.csv").write_text("Date,Close\n2006-01-03,1\n")
    # Tocar el companyfacts NO usado (segundo en orden CLI) cambia el hash.
    (asec / "WIN.json.gz").write_bytes(_gz(b'{"facts": {"y": 3}}'))
    assert bt._data_hash([z, a], [zsec, asec], ["WIN"], syms, None, None, cfg) != base
    (asec / "WIN.json.gz").write_bytes(_gz(b'{"facts": {"y": 2}}'))
    assert bt._data_hash([z, a], [zsec, asec], ["WIN"], syms, None, None, cfg) == base
    # Permutar el orden de los directorios cambia el hash.
    assert bt._data_hash([a, z], [zsec, asec], ["WIN"], syms, None, None, cfg) != base
    assert bt._data_hash([z, a], [asec, zsec], ["WIN"], syms, None, None, cfg) != base


def test_data_hash_cubre_la_cartera_fija(tmp_path):
    # Regresion auditor: cambiar --fixed entre simbolos ya presentes debe
    # cambiar el hash (cambia los resultados).
    pxdir = tmp_path / "px"
    pxdir.mkdir()
    (pxdir / "WIN.csv").write_text("Date,Close\n2005-01-03,100\n")
    (pxdir / "SPY.csv").write_text("Date,Close\n2005-01-03,20\n")
    syms = tmp_path / "symbols.txt"
    syms.write_text("WIN\nSPY\n")
    fixed = tmp_path / "fixed.txt"
    fixed.write_text("WIN\n")
    cfg = {"seed": 1}
    base = bt._data_hash([pxdir], [], ["WIN", "SPY"], syms, None, None, cfg, fixed=fixed)
    fixed.write_text("SPY\n")
    assert bt._data_hash([pxdir], [], ["WIN", "SPY"], syms, None, None, cfg, fixed=fixed) != base
    fixed.write_text("WIN\n")
    assert bt._data_hash([pxdir], [], ["WIN", "SPY"], syms, None, None, cfg, fixed=fixed) == base
    # Sin --fixed no es lo mismo que con --fixed.
    assert bt._data_hash([pxdir], [], ["WIN", "SPY"], syms, None, None, cfg) != base


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


def test_cero_elegibles_sale_explicito_sin_datos():
    # Regresión auditor: membership que deja la ventana sin elegibles no debe
    # simular carteras vacías ni dividir tax_paid/invested 0: sale explícito.
    m = px.Membership({"WIN": [(T0 + 2, None)]})  # en t0 (T0) aún no es miembro
    out = bt.run_benchmark([_winner()], _winner(), MONTHS, portfolios=1, sizes=(1,), seed=1, membership=m)
    assert out["status"] == "sin_datos"
    assert out["eligible"] == 0 and out["portfolios"] == 0
    assert out["strategies"] == {}
    assert "no concluyente" in out["nota"]


def test_fold_tardio_sin_elegibles_queda_marcado():
    # Regresión auditor: un fold tardío fuera de la pertenencia queda marcado
    # sin_datos, con métricas None, y los folds con elegibles corren normal.
    m = px.Membership({"WIN": [(T0, T0 + 5)]})  # miembro solo hasta 2008-06
    rep = bt.walk_forward_report(
        [_winner()],
        _winner(),
        MONTHS,
        train=3,
        test=3,
        portfolios=1,
        sizes=(1,),
        seed=1,
        membership=m,
        exits=None,
        unknown_exit=-1.0,
    )
    folds = rep["folds"]
    assert len(folds) == 3
    assert folds[0].get("status") != "sin_datos" and folds[0]["eligible"] == 1
    for f in folds[1:]:
        assert f["status"] == "sin_datos"
        assert f["eligible"] == 0
        assert f["irr_diff_median"] is None
        assert f["app_irr_median"] is None and f["plano_irr_median"] is None
