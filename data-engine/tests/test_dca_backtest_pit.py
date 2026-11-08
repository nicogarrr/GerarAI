"""Arnes PIT del sistema DCA (``scripts/dca_backtest_pit.py``): sin fugas y mismas reglas que la app."""

from __future__ import annotations

import gzip
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.services.dca_signal_engine import DailyBar
from scripts import dca_backtest_pit as bt


def _bars(rets, start=100.0, day0=date(2005, 1, 3)):
    """Dos cierres por mes (dias 3 y 20) a partir de rentabilidades mensuales."""
    out = []
    px = start
    for i, r in enumerate(rets):
        y, m = divmod(day0.month - 1 + i, 12)
        first = px
        px = px * (1 + r)
        out.append(DailyBar(day=date(day0.year + y, m + 1, 3), close=first))
        out.append(DailyBar(day=date(day0.year + y, m + 1, 20), close=px))
    return out


def _series(sym, rets, **kw):
    return bt.build_series(sym, _bars(rets, **kw))


def test_assert_no_leak_pasa_con_el_motor_real():
    s = _series("AAA", [0.03, -0.08, 0.05, -0.12, 0.10] * 12)
    assert bt.assert_no_leak([s], samples=30) == 30


def test_assert_no_leak_detecta_un_nivel_que_mira_al_futuro():
    s = _series("AAA", [0.03, -0.08, 0.05, -0.12, 0.10] * 12)
    months = sorted(s.level)
    # Fuga inyectada: el nivel de cada mes es el del mes siguiente.
    s.level = {m: s.level[n] for m, n in zip(months, months[1:], strict=False)}
    with pytest.raises(AssertionError, match="FUGA"):
        bt.assert_no_leak([s], samples=len(s.level))


def test_irr_anual_de_aportaciones_constantes():
    # 12 aportaciones de 100 al 0 % -> valor 1200 -> TIR 0.
    assert abs(bt.irr_annual([100.0] * 12, 1200.0)) < 1e-6
    # Una sola aportacion que crece un 10 % en un ano.
    flows = [100.0] + [0.0] * 11
    assert abs(bt.irr_annual(flows, 110.0) - 0.10) < 1e-6


def test_plano_reparte_a_partes_iguales_y_no_deja_caja():
    a = _series("AAA", [0.01] * 60)
    b = _series("BBB", [0.02] * 60)
    months = list(range(2008 * 12, 2009 * 12))
    r = bt.simulate([a, b], months, strategy="plano")
    assert r.invested == 200.0 * 12
    assert r.turnover == 0.0  # el plano nunca vende
    assert r.final > r.invested  # precios al alza


def test_la_app_pondera_por_nivel_al_cuadrado(monkeypatch):
    a = _series("AAA", [0.01] * 60)
    b = _series("BBB", [0.01] * 60)
    months = [2008 * 12]
    a.level = dict.fromkeys(a.level, 4)
    b.level = dict.fromkeys(b.level, 1)
    a.vol = dict.fromkeys(a.vol, 0.5)
    b.vol = dict.fromkeys(b.vol, 0.5)
    spent: dict[str, float] = {}
    real = bt.pcs.split_contribution

    def spy(amount, cands):
        out = real(amount, cands)
        spent.update({x["ticker"]: x["amount"] for x in out["allocations"]})
        return out

    monkeypatch.setattr(bt.pcs, "split_contribution", spy)
    bt.simulate([a, b], months, strategy="app")
    assert spent == {"AAA": 188.24, "BBB": 11.76}  # 16:1 de 200


def test_recorte_no_recibe_dinero_y_la_caja_pasa_al_mes_siguiente():
    a = _series("AAA", [0.01] * 60)
    b = _series("BBB", [0.01] * 60)
    months = [2008 * 12, 2008 * 12 + 1]
    t0, t1 = months
    a.level = {**a.level, t0 - 1: -1, t1 - 1: 1}
    b.level = {**b.level, t0 - 1: -2, t1 - 1: 1}
    r = bt.simulate([a, b], months, strategy="app")
    # Mes 1 todo en recorte: la cuota queda en liquidez; mes 2 se invierte todo.
    assert r.curve[0] == pytest.approx(200.0)
    assert r.curve[1] > 390.0


def test_trim_exec_paga_impuesto_solo_sobre_plusvalia():
    a = _series("AAA", [0.05] * 60)
    months = list(range(2008 * 12, 2008 * 12 + 6))
    a.level = {**a.level, **{m - 1: 1 for m in months[:-1]}, months[-1] - 1: -2}
    r = bt.simulate([a], months, strategy="trim_exec")
    assert r.tax_paid > 0
    assert r.turnover > 0


def test_valor_joven_sin_nivel_pesa_1x():
    old = _series("OLD", [0.01] * 60)
    young = _series("NEW", [0.01] * 60, day0=date(2007, 9, 3))  # aun sin 12 meses en 2008-01
    months = [2008 * 12]
    assert months[0] - 1 not in young.level
    r = bt.simulate([old, young], months, strategy="app")
    assert r.invested == 200.0


def test_elegible_solo_desde_su_primer_filing_sec(tmp_path: Path):
    p = tmp_path / "AAA.json.gz"
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {"USD": [{"filed": "2009-03-02", "val": 1}, {"filed": "2008-02-27", "val": 1}]}
                }
            }
        }
    }
    with gzip.open(p, "wt") as fh:
        json.dump(facts, fh)
    assert bt.first_sec_filing_month(p) == 2008 * 12 + 1
    a = _series("AAA", [0.5] * 60)  # si recibiera dinero en 2008-01, el valor saltaria
    b = _series("BBB", [0.0] * 60)
    a.eligible_from = 2008 * 12 + 1
    months = [2008 * 12, 2008 * 12 + 1]
    r = bt.simulate([a, b], months, strategy="plano")
    # En 2008-01 AAA aun no tiene filing: todo va a BBB, nada a AAA.
    assert r.curve[0] == pytest.approx(200.0 * (1 - bt.COST), rel=1e-3)


def test_lectura_csv_ajustado_ignora_cierres_invalidos(tmp_path: Path):
    p = tmp_path / "X.csv"
    p.write_text(
        "Date,Close,Low,Adj Close\n2020-01-02,10,9,5\n2020-01-03,,9,\n2020-01-06,0,0,0\n2020-01-07,12,11,6\n"
    )
    bars = bt.read_price_csv(p)
    assert [b.close for b in bars] == [5.0, 6.0]
    assert bars[0].low == pytest.approx(4.5)  # el minimo se reescala con el factor del dia


def test_bootstrap_por_bloques_es_determinista_y_contiene_la_media():
    x = [math.sin(i / 3) / 100 + 0.001 for i in range(180)]
    m, lo, hi = bt.block_bootstrap_mean(x, draws=300)
    assert lo <= m <= hi
    assert bt.block_bootstrap_mean(x, draws=300) == (m, lo, hi)


def test_constantes_del_plan_se_restauran():
    before = (bt.pcs.LOW_VOLATILITY_THRESHOLD, bt.pcs.CONCENTRATION_CAP)
    with bt.plan_constants(low_vol=0.3, cap=2.4):
        assert bt.pcs.LOW_VOLATILITY_THRESHOLD == 0.3
    assert before == (bt.pcs.LOW_VOLATILITY_THRESHOLD, bt.pcs.CONCENTRATION_CAP)


def test_spy_dca_invierte_todo_en_spy():
    a = _series("AAA", [0.0] * 60)
    spy = _series("SPY", [0.01] * 60)
    months = list(range(2008 * 12, 2008 * 12 + 3))
    r = bt.simulate([a], months, strategy="spy", spy=spy)
    assert r.final > r.invested


def test_dia_de_mes_consistente():
    assert bt.month_label(bt.month_index(date(2024, 12, 31))) == "2024-12"
    assert bt.month_index(date(2010, 1, 1) - timedelta(days=1)) == 2009 * 12 + 11
