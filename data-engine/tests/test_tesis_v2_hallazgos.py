"""Tesis v2: kill switch de apalancamiento vivo, guía con su divisa y tesis desactualizada sin mezclas
(hallazgos del auditor sobre #4764).

Antes: (a) el umbral era máx(2,5; deuda neta/EBITDA de hoy + 1) y se comparaba con el dato de hoy, así
que nunca saltaba; (b) una guía sin divisa salía en dólares; (c) una tesis cuya valoración había
cambiado servía el texto viejo con las tablas de hoy, sin decirlo."""
from __future__ import annotations

from app.services.expert_team import thesis_v2 as T
from tests.test_thesis_v2 import _ctx


def test_apalancamiento_salta_si_sube_mas_de_una_vuelta_sobre_el_ejercicio_anterior() -> None:
    ctx = _ctx()
    rows = [dict(r) for r in ctx.history]
    rows[-2]["net_debt_to_ebitda"] = 0.5  # el año anterior: 0,5×; hoy: 3.000 / 1.450 ≈ 2,1×
    sw = {s["key"]: s for s in T.kill_switches(ctx.valuation, rows)}
    lev = sw["apalancamiento"]
    assert lev["threshold"].startswith("> 2,5")  # máx(2,5; 0,5 + 1)
    assert lev["status"] == "ok"
    rows[-2]["net_debt_to_ebitda"] = 0.2
    ctx.valuation["starting_point"]["net_debt"] = 4000.0  # hoy ≈ 2,8× > 2,5×
    sw = {s["key"]: s for s in T.kill_switches(ctx.valuation, rows)}
    assert sw["apalancamiento"]["status"] == "saltado"


def test_umbral_de_apalancamiento_no_depende_del_dato_de_hoy() -> None:
    assert T.leverage_limit({"net_debt_to_ebitda": 3.0}) == 4.0
    assert T.leverage_limit({}) == T.LEVERAGE_FLOOR


def test_guia_sin_divisa_no_se_pinta_en_dolares() -> None:
    g = {"metric": "revenue", "period": "fy2026", "unit": "", "low": 9e9, "base": 9.5e9, "high": 1e10}
    assert "M$" not in T._guidance_value(g, 9.5e9) and "sin divisa" in T._guidance_value(g, 9.5e9)
    [sw] = T.estimate_switches([g], "EUR")
    assert sw["status"] == "no_comparable" and "no dice su divisa" in sw["current"]


def test_guia_en_otra_divisa_no_se_compara_con_los_informes() -> None:
    g = {"metric": "revenue", "period": "fy2026", "unit": "USD", "low": 9e9, "base": 9.5e9, "high": 1e10}
    [sw] = T.estimate_switches([g], "EUR")
    assert sw["status"] == "no_comparable" and "guía en USD, informes en EUR" in sw["current"]
    [ok] = T.estimate_switches([g], "USD")
    assert ok["status"] == "pendiente"


def test_tesis_desactualizada_sirve_sus_tablas_guardadas_y_lo_dice() -> None:
    ctx = _ctx()
    doc = {"status": "ok", "sections": {}}
    saved = {"tables": {"partida": {"title": "Punto de partida normalizado", "head": ["a"], "rows": [["viejo"]]}},
             "valuation_as_of": "2026-08-01", "warnings": ["aviso viejo"]}
    out = T.present(ctx, doc, {}, saved=saved)
    assert out["as_of"] == "2026-08-01"
    assert out["warnings"][0].startswith("tesis desactualizada") and "aviso viejo" in out["warnings"]
    tabs = [t for s in out["sections"] for t in s["tables"]]
    assert any(t["rows"] == [["viejo"]] for t in tabs)


def test_tesis_desactualizada_sin_tablas_guardadas_avisa_de_la_mezcla() -> None:
    out = T.present(_ctx(), {"status": "ok", "sections": {}}, {}, saved={"markers": {}})
    assert "las tablas son las de hoy" in out["warnings"][0]


def test_flujo_libre_sin_capex_es_nd_no_el_flujo_operativo() -> None:
    cites = {"annual": {"revenue": {"2024": {"value": 1e9}}, "operating_cash_flow": {"2024": {"value": 3e8}}}}
    [row] = T.history_rows(cites, "ev_ebitda", {})
    assert row["fcf"] is None and row["conversion"] is None
