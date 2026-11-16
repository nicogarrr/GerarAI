"""Pruebas adversariales de ``scripts/pit_exits.py``."""

from __future__ import annotations

import pytest

from scripts import pit_exits as px

T0 = 2010 * 12


def test_quiebra_sin_cifra_pierde_todo(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("symbol,last_month,kind,exit_return\nBAD,2012-03,bankruptcy,\n")
    ev = px.load_exits(f)["BAD"]
    assert ev.exit_return == -1.0 and ev.last_month == 2012 * 12 + 2
    assert px.exit_value(10, 5.0, ev, cost=0.001, unknown=0.0) == 0.0


def test_adquisicion_con_prima_y_costes():
    ev = px.ExitEvent("ACQ", T0, "acquired", 0.25)
    assert px.exit_value(10, 10.0, ev, cost=0.001, unknown=-1.0) == pytest.approx(10 * 10 * 1.25 * 0.999)


def test_exit_return_menor_que_menos_uno_se_rechaza(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("symbol,last_month,kind,exit_return\nX,2012-03,delist_loss,-1.5\n")
    with pytest.raises(ValueError):
        px.load_exits(f)


def test_kind_invalido_se_rechaza(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("symbol,last_month,kind,exit_return\nX,2012-03,foo,0\n")
    with pytest.raises(ValueError):
        px.load_exits(f)


def test_hueco_no_es_baja_y_fin_de_datos_tampoco():
    end = T0 + 100
    assert not px.is_delisted(T0 + 5, None, end, None)
    assert not px.is_delisted(T0 + 5, T0 + 10, end, None)  # aun no paso su ultimo mes
    assert not px.is_delisted(end, end - 1, end, None)  # serie corta por fin de datos
    assert px.is_delisted(T0 + 20, T0 + 10, end, None)  # desaparece pronto sin evento
    assert px.is_delisted(end, end - 1, end, px.ExitEvent("A", end - 1, "acquired", 0.0))


def test_sin_evento_usa_cota_elegida():
    assert px.exit_value(1, 10.0, None, cost=0.0, unknown=-1.0) == 0.0
    assert px.exit_value(1, 10.0, None, cost=0.0, unknown=0.0) == 10.0


def test_elegibilidad_no_mira_el_futuro_y_conserva_quebradas():
    m = px.Membership({"DEAD": [(T0 - 12, T0 + 20)], "NEW": [(T0 + 5, None)]})
    got = px.eligible_at(
        ["DEAD", "NEW", "NOFILE", "LATE"],
        T0,
        has_price_at={"DEAD": True, "NEW": True, "NOFILE": True, "LATE": True},
        level_prev={"DEAD": True, "NEW": True, "NOFILE": True, "LATE": True},
        first_filing={"DEAD": T0 - 30, "NEW": T0 - 1, "NOFILE": None, "LATE": T0 + 3},
        membership=m,
    )
    assert "DEAD" in got  # quebrada despues: DEBE estar (el sesgo original la quitaba)
    assert "NEW" not in got and "LATE" not in got  # aun no era miembro / no habia filing
    assert "NOFILE" not in got  # sin pertenencia historica registrada


def test_membership_extremos_incluidos():
    m = px.Membership({"A": [(5, 8)]})
    assert [m.has("A", t) for t in (4, 5, 8, 9)] == [False, True, True, False]
    assert m.at(6) == ["A"]


def test_walk_forward_sin_solape_y_test_posterior():
    months = list(range(60))
    folds = px.walk_forward_folds(months, train=24, test=12)
    assert len(folds) == 3
    for tr, te in folds:
        assert max(tr) < min(te)
    assert folds[1][1][0] == 36


def test_costes_restan_y_validan_longitud():
    assert px.cost_adjusted([0.01, 0.02], [1.0, 0.0], bps=10) == pytest.approx([0.009, 0.02])
    with pytest.raises(ValueError):
        px.cost_adjusted([0.01], [], bps=10)
