"""Nota de tesis: componentes visibles, juez con poco peso y analistas como discrepancia (sin red ni BD)."""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.services import nota_tesis as nt

AUDIT = """# AUDIT
## Engine summary per ticker
| ticker | DCF engine | DCF status | DCF bear/base/bull | TIR method | TIR 5y bear/base/bull | TIR value/share base |
|---|---|---|---|---|---|---|
| CPT | standard_dcf | insufficient_data | None/None/None | tir_per (ok) | -0.04/0.25/0.74 | 275.41 |
| ASTS | pre_revenue | insufficient_data | None/None/None | sotp (not_applicable) | None/None/None | 12.5 |

## Inputs against the primary source
| ticker | input | app value | source value | link | verdict |
|---|---|---|---|---|---|
| CPT | price | 99.44 | 99.44 | Yahoo | OK |
| CPT | revenue FY25 | 12.97 M | 1,573.5 M | https://sec.gov/x | ERROR ×121 |
| CPT | net income FY25 | 384.46 | 383.64 | https://sec.gov/x | OK (−0.2 %) |
| CPT | diluted shares | 108.43 M | 100.07 M | https://sec.gov/x | REVIEW (−7.7 %) |
| CPT | method/type | operating | REIT | - | METHOD |
| BN | TIR | x | y | - | None |
"""


def perfect_rigor(**over):
    r = {
        "free_numbers_final": 0,
        "unknown_markers_final": 0,
        "guard_problems": {"free_numbers": 0, "false_positive_10b5_1": 0},
        "quotes_attributed": {"quotes": 4, "not_literal": 0, "translated": 0},
        "method": {"ok": True, "type": "operativa", "chosen": "tir_ev_ebitda"},
        "source": {"ok": {"price": True, "shares": True, "net_debt": True}},
        "sections": {"expected": 15, "filled": 15},
        "kill_switches": {"count": 8, "as_threshold": 8},
    }
    r.update(over)
    return r


def test_audit_reads_only_the_inputs_table_and_weights_errors():
    flags = nt.parse_audit_md(AUDIT)
    assert set(flags) == {"CPT"}  # el resumen de motores (ASTS «pre_revenue») no es una fila de dato
    by = {f["input"]: f for f in flags["CPT"]}
    assert set(by) == {"revenue FY25", "diluted shares", "method/type"}
    assert by["revenue FY25"]["puntos"] == 2 and by["diluted shares"]["puntos"] == 1
    assert by["method/type"]["dato"] is False  # el método se mide aparte, no se cuenta dos veces
    assert nt.audit_points(flags["CPT"]) == 3


def test_weights_add_up_and_every_component_has_a_formula():
    assert math.isclose(sum(nt.PESOS_RIGOR.values()), 1.0)
    assert set(nt.FORMULAS_RIGOR) == set(nt.PESOS_RIGOR)
    assert math.isclose(nt.PESO_RIGOR + nt.PESO_JUEZ, 1.0)
    assert nt.PESO_JUEZ <= 0.25  # el juez tiene ruido: parte menor


def test_perfect_thesis_gets_ten_of_rigor():
    rc = nt.rigor_components(perfect_rigor())
    assert rc["rigor_10"] == 10.0
    assert all(c["valor"] == 1 for c in rc["componentes"].values())


def test_free_numbers_left_in_final_text_zero_the_component():
    rc = nt.rigor_components(perfect_rigor(free_numbers_final=1))
    assert rc["componentes"]["cifras_libres"]["valor"] == 0
    assert rc["rigor_10"] == pytest.approx(10 - 10 * nt.PESOS_RIGOR["cifras_libres"])


def test_false_positives_10b5_1_do_not_count_as_free_numbers():
    rc = nt.rigor_components(perfect_rigor(guard_problems={"free_numbers": 6, "false_positive_10b5_1": 2}))
    assert rc["componentes"]["cifras_libres"]["valor"] == pytest.approx(0.6)


def test_translated_quotes_count_as_not_literal_and_no_quotes_is_fine():
    rc = nt.rigor_components(
        perfect_rigor(quotes_attributed={"quotes": 4, "not_literal": 3, "translated": 2})
    )
    assert rc["componentes"]["citas_literales"]["valor"] == pytest.approx(0.25)
    rc0 = nt.rigor_components(perfect_rigor(quotes_attributed={"quotes": 0, "not_literal": 0}))
    assert rc0["componentes"]["citas_literales"]["valor"] == 1.0


def test_method_partial_and_wrong():
    assert (
        nt.rigor_components(perfect_rigor(method={"ok": False, "partial": True}))["componentes"][
            "metodo_tipo"
        ]["valor"]
        == 0.5
    )
    assert (
        nt.rigor_components(perfect_rigor(method={"ok": False}))["componentes"]["metodo_tipo"]["valor"] == 0
    )


def test_audit_flags_and_source_mismatch_lower_data_component():
    flags = nt.parse_audit_md(AUDIT)["CPT"]  # 3 puntos
    rc = nt.rigor_components(
        perfect_rigor(source={"ok": {"price": True, "shares": False, "net_debt": True}}), flags
    )
    assert rc["componentes"]["datos_fuente"]["valor"] == pytest.approx(
        0.5 * 2 / 3 + 0.5 * (1 - 0.45), abs=1e-4
    )


def test_kill_switches_without_threshold_and_no_switches():
    rc = nt.rigor_components(perfect_rigor(kill_switches={"count": 8, "as_threshold": 7}))
    assert rc["componentes"]["kill_switches"]["valor"] == pytest.approx(7 / 8)
    rc0 = nt.rigor_components(perfect_rigor(kill_switches={"count": 0, "as_threshold": 0}))
    assert rc0["componentes"]["kill_switches"]["valor"] == 0


def test_judge_averages_both_orders_and_reports_the_anchor():
    first = {"preferido": "B", "score_A": 3.0, "score_B": 4.0}  # X en A
    swapped = {"preferido": "A", "score_A": 4.4, "score_B": 3.4}  # X en B
    r = nt.judge_result(first, swapped)
    assert r["nota_5"] == pytest.approx(3.2) and r["ancla_5"] == pytest.approx(4.2)
    assert r["delta_vs_ancla"] == pytest.approx(-1.0)
    assert r["consistente"] is True and r["dispersion_ordenes"] == pytest.approx(0.4)
    assert nt.judge_result(None, None)["nota_5"] is None


def test_placebo_measures_judge_noise():
    pairs = [
        {
            "first": {"preferido": "empate", "score_A": 3.0, "score_B": 3.0},
            "swapped": {"preferido": "A", "score_A": 3.4, "score_B": 3.0},
        },
    ]
    p = nt.placebo_noise(pairs)
    assert p["n"] == 2 and p["media_abs_diferencia_5"] == pytest.approx(0.2)
    assert p["preferencia_espuria"] == pytest.approx(0.5)
    assert p["entre_llamadas_media_5"] == pytest.approx(0.4)  # 3,0 en una llamada, 3,4 en la otra
    assert p["efecto_max_en_nota_10"] == pytest.approx(nt.PESO_JUEZ * 0.4)


def test_grade_judge_is_a_minor_share():
    lo, hi = nt.grade(7.0, 0.0)["nota"], nt.grade(7.0, 5.0)["nota"]
    assert hi - lo == pytest.approx(10 * nt.PESO_JUEZ)  # el juez mueve como mucho 2 puntos
    assert nt.grade(7.0, None) == {"nota": 7.0, "formula": "rigor solo (sin veredicto del juez)"}
    assert nt.grade(None, 4.0)["nota"] is None


def test_analyst_gap_measures_disagreement_in_the_same_currency():
    cons = {"status": "available", "mean": 5105.0, "low": 5100.0, "high": 5110.0, "currency": "GBX"}
    g = nt.analyst_gap({"bear": 30, "base": 40.84, "bull": 60}, "GBP", cons)
    assert g["comparable"] and g["consenso_medio"] == pytest.approx(51.05)
    assert g["base_vs_consenso"] == pytest.approx(40.84 / 51.05 - 1, abs=1e-4)
    assert g["base_en_rango_analistas"] is False
    assert (
        nt.analyst_gap({"base": 10}, "USD", {"status": "available", "mean": 10, "currency": "CAD"})[
            "comparable"
        ]
        is False
    )
    assert nt.analyst_gap({"base": 10}, "USD", None)["comparable"] is False
    assert nt.analyst_gap({}, "USD", cons)["motivo"] == "sin valor por acción propio"


def _record():
    return nt.forecast_record(
        ticker="CB",
        as_of=date(2026, 11, 8),
        price=100.0,
        currency="USD",
        value_per_share={"bear": 80, "base": 130, "bull": 160},
        irr5={"bear": 0, "base": 0.1, "bull": 0.2},
        method="tir_pb",
        analyst={
            "status": "available",
            "mean": 110.0,
            "currency": "USD",
            "n_analysts": 20,
            "source": "Yahoo",
            "source_url": "https://finance.yahoo.com/quote/CB/analysis/",
            "fetched_at": 1,
        },
        thesis_fingerprint="abc",
        commit="deadbeef",
        nota=7.1,
    )


def test_forecast_log_holds_both_our_value_and_the_analyst_target():
    rec = _record()
    assert rec["value_per_share"]["base"] == 130 and rec["analyst"]["mean"] == 110.0
    assert rec["analyst"]["source_url"].startswith("https://")
    assert rec["score_at"] == {"1y": "2027-11-08", "3y": "2029-11-08"}
    assert rec["id"] == _record()["id"]


def test_scorer_grades_both_at_one_and_three_years():
    rec = _record()
    s = nt.score_vs_analysts(rec, horizon_years=1, price_then=125.0)
    assert s["mas_cerca"] == "nuestro"
    assert s["direccion_nuestro"] is True and s["direccion_analistas"] is True
    s3 = nt.score_vs_analysts(rec, horizon_years=3, price_then=105.0, dividends_per_share=3.0)
    assert s3["mas_cerca"] == "analistas"
    summ = nt.summarize_vs([s, s3])
    assert summ["n"] == 2 and summ["nuestro_mas_cerca"] == 1 and summ["analistas_mas_cerca"] == 1


def test_scorer_without_analyst_target_does_not_pick_a_winner():
    rec = _record()
    rec["analyst"] = {"status": "empty"}
    s = nt.score_vs_analysts(rec, horizon_years=1, price_then=120.0)
    assert s["mas_cerca"] is None and s["error_analistas"] is None
    assert nt.summarize_vs([s]) == {"n": 0}


def test_scorer_uses_the_target_converted_to_our_currency():
    rec = _record()
    rec["currency"] = "CAD"
    rec["analyst"] = {
        "status": "available",
        "mean": 50.0,
        "currency": "USD",
        "converted": {"mean": 70.0, "currency": "CAD", "status": "available", "fx": "50 USD × 1,40"},
    }
    s = nt.score_vs_analysts(rec, horizon_years=1, price_then=72.0)
    assert s["error_analistas"] == pytest.approx(abs(math.log(72 / 70)))


def test_module_grades_follow_their_stated_bar():
    v = nt.grade_valor_intrinseco(
        {
            "ic5_holdout": 0.006,
            "sesgo_nivel_pp": 5.5,
            "cobertura_bajista_alcista": 0.58,
            "datos_ok": 24,
            "datos_total": 53,
            "metodo_ok": 21,
            "metodo_total": 22,
        }
    )
    assert v["componentes"]["prediccion"]["valor"] == pytest.approx(0.06)
    assert 0 < v["nota"] < 5  # sin poder predictivo en el holdout no puede aprobar
    d_ns = nt.grade_dca(
        {
            "ventaja_mediana_pp": 0.61,
            "ic95_bajo_pp": -0.31,
            "ic95_alto_pp": 2.5,
            "tests_ok": 33,
            "tests_total": 33,
        }
    )
    d_sig = nt.grade_dca(
        {
            "ventaja_mediana_pp": 0.61,
            "ic95_bajo_pp": 0.1,
            "ic95_alto_pp": 2.5,
            "tests_ok": 33,
            "tests_total": 33,
        }
    )
    assert d_sig["nota"] > d_ns["nota"]  # una ventaja no significativa vale la mitad
    full = nt.grade_dca(
        {"ventaja_mediana_pp": 3, "ic95_bajo_pp": 1, "ic95_alto_pp": 4, "tests_ok": 1, "tests_total": 1}
    )
    assert full["nota"] == 10.0
    c = nt.grade_cerebro({"aciertos": 75, "casos": 80, "juez_5": 3.51, "p95_s": 16.4, "cifras_inventadas": 0})
    c1 = nt.grade_cerebro(
        {"aciertos": 75, "casos": 80, "juez_5": 3.51, "p95_s": 16.4, "cifras_inventadas": 1}
    )
    assert c1["nota"] == pytest.approx(c["nota"] / 2, abs=0.06)
    e = nt.grade_equipo(
        {"roles_con_aporte": 0, "roles_evaluados": 6, "tesis_en_suelo": 0, "tesis_juzgadas": 22}
    )
    assert e["nota"] == 0.0


# ------------------------------------------------------------------------------------- baremo estricto v2


def _rig_v2(**over):
    base = {
        "status": "ok",
        "free_numbers_final": 0,
        "unknown_markers_final": 0,
        "guard_problems": {"free_numbers": 0, "false_positive_10b5_1": 0},
        "quotes": {"quotes": 4, "not_literal": 1, "translated": 0},
        "quotes_attributed": {"quotes": 0, "not_literal": 0},
        "sections": {"expected": 16, "filled": 16},
        "kill_switches": {"count": 4, "as_threshold": 4},
        "method": {"ok": True},
        "source": {
            "price": {"value": 100.0, "cited": 100.0},
            "shares": {"value": 50.0},
            "net_debt": {"value": 200.0},
        },
    }
    base.update(over)
    return base


def test_v2_pesos_suman_1_y_secciones_kill_son_menores():
    assert math.isclose(sum(nt.PESOS_RIGOR_V2.values()), 1.0)
    assert nt.PESOS_RIGOR_V2["secciones"] + nt.PESOS_RIGOR_V2["kill_switches"] <= 0.15 + 1e-9
    assert set(nt.FORMULAS_RIGOR_V2) == set(nt.PESOS_RIGOR_V2)


def test_v2_tesis_recortada_saca_0_en_cifras():
    v1 = nt.rigor_components(_rig_v2(status="stripped"))
    v2 = nt.rigor_components_v2(_rig_v2(status="stripped"))
    assert v1["componentes"]["cifras_libres"]["valor"] == 1.0  # v1 la premiaba
    assert v2["componentes"]["cifras_libres"]["valor"] == 0.0
    assert v2["recortada"] is True


def test_v2_error_de_audit_anula_datos():
    flags = [{"input": "debt", "dato": True, "puntos": 2}]
    v1 = nt.rigor_components(_rig_v2(), flags)
    v2 = nt.rigor_components_v2(_rig_v2(), flags, {"shares": 50.0, "net_debt": 200.0})
    assert v1["componentes"]["datos_fuente"]["valor"] > 0.3  # v1: un ERROR solo quitaba 0,15
    assert v2["componentes"]["datos_fuente"]["valor"] == 0.0


def test_v2_datos_contra_fuente_primaria_no_contra_la_propia_cita():
    # La tesis cita 50 M acciones y su cita dice 50 (coherente), pero la portada dice 60: mal.
    prim = {"shares": 60.0, "net_debt": 200.0}
    r = nt.rigor_components_v2(_rig_v2(), [], prim)
    fp = r["fuente_primaria"]
    assert (
        fp["shares"]["estado"] == "mal" and fp["price"]["estado"] == "ok" and fp["net_debt"]["estado"] == "ok"
    )
    assert math.isclose(r["componentes"]["datos_fuente"]["valor"], 2 / 3, rel_tol=1e-3)
    # Sin valor primario: «no verificado» vale 0,5, no 1.
    r2 = nt.rigor_components_v2(_rig_v2(), [], {})
    assert r2["fuente_primaria"]["shares"]["estado"] == "no_verificado"
    assert math.isclose(r2["componentes"]["datos_fuente"]["valor"], (1 + 0.5 + 0.5) / 3, rel_tol=1e-3)
    # Los avisos (no ERROR) restan 0,25 cada uno.
    r3 = nt.rigor_components_v2(_rig_v2(), [{"dato": True, "puntos": 1}], prim)
    assert math.isclose(r3["componentes"]["datos_fuente"]["valor"], 2 / 3 * 0.75, rel_tol=1e-3)


def test_v2_cuenta_todas_las_citas_y_sin_citas_no_es_el_maximo():
    sin = nt.rigor_components_v2(_rig_v2(quotes={"quotes": 0, "not_literal": 0}))
    assert sin["componentes"]["citas_literales"]["valor"] == nt.SIN_CITAS < 1
    # v1 miraba solo las atribuidas (0 → máximo); v2 cuenta las 4 citas, 1 no literal.
    assert nt.rigor_components(_rig_v2())["componentes"]["citas_literales"]["valor"] == 1.0
    assert nt.rigor_components_v2(_rig_v2())["componentes"]["citas_literales"]["valor"] == 0.75


def test_v2_kill_switch_solo_cuenta_si_el_codigo_puede_comprobarlo():
    sw = [
        {"key": "a", "metric": "Deuda neta / EBITDA", "threshold": "> 2,7x", "current": "1,7x"},
        {"key": "b", "metric": "Crecimiento", "threshold": "< −4,0 % dos años", "current": "−0,4 %"},
        {"key": "c", "metric": "Meses de caja", "threshold": "< 12 meses", "current": "sin consumo"},
        {"key": "d", "metric": "Calidad del equipo", "threshold": "si empeora", "current": "buena"},
        {"key": "e", "metric": "Margen", "threshold": "< 10 %", "current": None},
    ]
    rep = nt.kill_switch_report_v2(sw)
    assert rep == {"count": 5, "checkable": 2, "not_checkable": ["c", "d", "e"]}
    r = nt.rigor_components_v2(_rig_v2(), kill_v2=rep)
    assert math.isclose(r["componentes"]["kill_switches"]["valor"], 0.4)


def test_v2_juez_numantia_es_el_objetivo():
    assert nt.judge_vs_numantia_10(0.0) == 10.0
    assert nt.judge_vs_numantia_10(0.3) == 10.0
    assert nt.judge_vs_numantia_10(-1.0) == 5.0
    assert nt.judge_vs_numantia_10(-2.5) == 0.0
    assert nt.judge_vs_numantia_10(None, 3.5) == 7.0


def test_v2_nota_y_modulo_sin_tesis_cuenta_cero():
    assert nt.grade_v2(None, None)["nota"] == 0.0
    assert nt.grade_v2(8.0, 5.0)["nota"] == 7.4
    m = nt.module_tesis_v2({"A": 8.0, "B": 6.0, "C": None}, ["A", "B", "C"])
    assert m["nota"] == 4.7 and m["sin_tesis"] == ["C"] and m["min"] == 0.0


def test_v2_estricto_baja_la_nota_de_una_tesis_que_v1_llenaba_sola():
    rig = _rig_v2(status="stripped", quotes={"quotes": 0, "not_literal": 0})
    flags = [{"dato": True, "puntos": 2}]
    v1 = nt.grade(nt.rigor_components(rig, flags)["rigor_10"], 3.5)["nota"]
    v2r = nt.rigor_components_v2(rig, flags, {})["rigor_10"]
    v2 = nt.grade_v2(v2r, nt.judge_vs_numantia_10(-1.0))["nota"]
    assert v1 >= 8.0 and v2 < 6.0


def test_cerebro_v2_aciertos_del_control_y_muestra_aparte():
    x = {
        "holdout_aciertos": 24,
        "holdout_casos": 30,
        "muestra_aciertos": 66,
        "muestra_casos": 80,
        "juez_antes_5": 3.17,
        "p95_s": 16.4,
        "cifras_inventadas": 0,
    }
    g = nt.grade_cerebro_v2(x)
    assert g["componentes"]["aciertos_control"]["valor"] == 0.8
    assert g["dentro_de_muestra"] == 8.2
    assert g["nota"] == round(10 * (0.6 * 0.8 + 0.2 * 3.17 / 5 + 0.2 * 10 / 16.4), 1)
    assert nt.grade_cerebro_v2({**x, "cifras_inventadas": 1})["nota"] == round(g["nota"] / 2, 1)


def test_cerebro_no_puedo_no_es_acierto():
    from evals.cerebro import bench_grade as G

    case = {
        "id": "x",
        "category": "valoracion_tesis",
        "q": "¿Cuál es el margen de seguridad de CB?",
        "expect": {"must_any": ["CB|Chubb"]},
    }
    ans = "No puedo medir el margen de seguridad de CB: no hay valor justo guardado en la cartera de hoy."
    r = G.grade_case(case, {"answer": ans}, latency_s=3.0, ground=[], fact_values={})
    assert r.checks["contesta"] is False and not r.passed
    # Fuera de ámbito, negarse es la respuesta correcta…
    fuera = {"id": "f", "category": "fuera_ambito", "q": "¿Qué tiempo hará?", "expect": {}}
    ok = G.grade_case(
        fuera,
        {"answer": "No puedo darte el tiempo: solo trato tu cartera e inversiones."},
        latency_s=3.0,
        ground=[],
        fact_values={},
    )
    assert ok.checks["contesta"] is True
    # …pero la reserva genérica es un fallo del sistema en cualquier categoría.
    res = "No puedo responderte con fuentes ahora mismo; prueba de nuevo en un momento."
    bad = G.grade_case(fuera, {"answer": res}, latency_s=3.0, ground=[], fact_values={})
    assert bad.checks["contesta"] is False
    assert G.cannot_answer("no puedo, lo siento") and not G.cannot_answer(
        "Tienes 10 acciones; no puedo decir más."
    )
