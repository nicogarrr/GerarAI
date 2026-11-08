"""Benchmark del equipo de expertos: métricas puras, juez ciego, tope de gasto/429 y registro de previsiones."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import expert_bench as eb

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("expert_bench_script", ROOT / "scripts" / "expert_bench.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------- cifras libres


def test_free_numbers_by_section_uses_thesis_guard():
    out = eb.free_numbers_by_section(
        {"a": "La TIR base es {{esc.base.tir10}} y el 10-K lo dice.", "b": "Crece un 12 % al año."}
    )
    assert "a" not in out
    assert out["b"] == ["12 %"]


def test_classify_problems_counts_free_unknown_and_10b5_1_false_positive():
    problems = [
        "directivos_capital: números sin marcador: 4, 10, 5, -1",
        "introduccion: números sin marcador: 172, 58.555",
        "riesgos: marcadores que no existen: vigilar.5.estado",
    ]
    out = eb.classify_problems(problems)
    assert out["free_numbers"] == 6
    assert out["unknown_markers"] == 1
    assert out["false_positive_10b5_1"] == 1
    assert out["sections_flagged"] == {"directivos_capital": 1, "introduccion": 1, "riesgos": 1}


def test_app_guard_still_flags_rule_10b5_1_as_numbers():
    """Hallazgo del benchmark: el guardián de la tesis v2 toma «Form 4» / «plan 10b5-1» por cifras libres.
    Si alguien lo arregla, este test avisa para quitar el contador de falsos positivos del benchmark."""
    from app.services.expert_team.thesis_v2 import loose_numbers

    assert loose_numbers("Vendió con un plan 10b5-1 según el formulario 4.") != []


# ------------------------------------------------------------------------------------------- citas


def test_quote_in_evidence_is_literal_modulo_case_accents_and_spaces():
    ev = ["We   expect   continued Growth in Résidential pools."]
    assert eb.quote_in_evidence("we expect continued growth in residential pools", ev)
    assert eb.quote_in_evidence("We expect … residential pools", ev)  # elipsis
    assert not eb.quote_in_evidence("we expect strong growth in residential pools", ev)


def test_check_quotes_flags_translation_presented_as_quote():
    ev = ["to support our efforts in AI and the core business, we will invest significantly"]
    out = eb.check_quotes(["apoyar nuestros esfuerzos en la IA y el negocio principal"], ev)
    assert out["quotes"] == 1 and out["not_literal"] == 1 and out["translated"] == 1


def test_attributed_quotes_skip_rhetorical_quotes():
    text = (
        "La pregunta es «a qué precio deja de ser una buena compra para nadie». Según el 10-K, "
        "«we expect continued growth in residential pools this year»."
    )
    assert eb.extract_quotes(text) == [
        "a qué precio deja de ser una buena compra para nadie",
        "we expect continued growth in residential pools this year",
    ]
    assert eb.extract_attributed_quotes(text) == ["we expect continued growth in residential pools this year"]


def test_quotes_in_json_and_evidence_strings():
    parsed = {"assets": [{"name": "x", "quote": "cash and equivalents of 1.2 billion"}], "segments": []}
    payload = {
        "evidence": [{"id": "ev-1", "text": "We held cash and equivalents of 1.2 billion at year end."}]
    }
    out = eb.check_quotes(eb.quotes_in_json(parsed), eb.evidence_strings(payload))
    assert out == {"quotes": 1, "not_literal": 0, "translated": 0, "examples": []}


# ------------------------------------------------------------------------------------------- método y fuentes


def test_method_fit_by_company_type():
    insurer = eb.method_fit(
        "aseguradora", "tir_per", "El valor contable crece y el ROE medio es alto.", "operating"
    )
    assert insurer["engine_ok"] is False and insurer["text_ok"] is True and insurer["ok"] is False
    assert insurer["kind_ok"] is False
    assert eb.method_fit("aseguradora", "tir_pb", kind="insurer")["ok"] is True
    manager = eb.method_fit("gestora", "tir_pb", kind="holding")
    assert manager["ok"] is False and manager["partial"] is True and manager["kind_ok"] is True
    assert eb.method_fit("reit", "tir_ffo")["ok"] is True
    assert eb.method_fit("operativa", "tir_ev_ebitda", "la TIR base")["ok"] is True
    assert eb.method_fit(None, "tir_per")["ok"] is None


def test_source_check_shares_in_millions_and_rebuilt_net_debt():
    val = {
        "starting_point": {
            "price": 100.0,
            "shares_diluted": 50.0,
            "net_debt": 300.0,
            "market_cap": 5000.0,
            "leases": 20.0,
            "hybrids": 0.0,
            "minorities": 0.0,
        },
        "citations": {
            "price": {"value": 100.0},
            "shares": {"value": 50_000_000.0},
            "total_debt": {"value": 400e6},
            "cash_and_equivalents": {"value": 100e6},
            "short_term_investments": {"value": 20e6},
        },
    }
    out = eb.source_check(val)
    assert out["ok"] == {"price": True, "shares": True, "net_debt": True}
    assert out["net_debt"]["rebuilt_from_citations"] == pytest.approx(300.0)
    val["starting_point"]["shares_diluted"] = 55.0
    assert eb.source_check(val)["ok"]["shares"] is False


def test_sections_and_kill_switches():
    assert eb.sections_filled({"a": "x" * 500, "b": "corta"}, ["a", "b", "c"]) == {
        "expected": 3,
        "filled": 1,
        "short_or_empty": ["b", "c"],
    }
    good = {
        "key": "crecimiento",
        "metric": "Crecimiento anual de ingresos",
        "threshold": "< 1,8 % dos ejercicios",
    }
    vague = {"key": "deuda", "metric": "Deuda", "threshold": "si sube mucho"}
    assert eb.kill_switch_is_threshold(good) and not eb.kill_switch_is_threshold(vague)
    assert eb.kill_switch_report([good, vague]) == {"count": 2, "as_threshold": 1, "not_threshold": ["deuda"]}


# ------------------------------------------------------------------------------------------- estabilidad


def test_agreement_jaccard_and_spread():
    assert eb.agreement(["a", "a", "b"]) == pytest.approx(2 / 3)
    assert eb.agreement([{"x": 1}, {"x": 1}]) == 1.0
    assert eb.mean_pairwise_jaccard([{1, 2}, {1, 2}, {1, 3}]) == pytest.approx((1 + 1 / 3 + 1 / 3) / 3)
    assert eb.relative_spread([10.0, 10.0, 12.0]) == pytest.approx(0.2)
    assert eb.relative_spread([5.0]) is None
    assert eb.markers_used("{{a.b}} y {{ c }} y {{a.b}}") == {"a.b", "c"}


# ------------------------------------------------------------------------------------------- juez


def test_judge_parse_and_position_bias_cancellation():
    a_wins = json.dumps(
        {"A": dict.fromkeys(eb.CRITERIA, 4), "B": dict.fromkeys(eb.CRITERIA, 2), "preferido": "A"}
    )
    b_wins = json.dumps(
        {"A": dict.fromkeys(eb.CRITERIA, 2), "B": dict.fromkeys(eb.CRITERIA, 4), "preferido": "B"}
    )
    first, swapped = eb.parse_judge("texto " + a_wins), eb.parse_judge(b_wins)
    assert first is not None and swapped is not None
    assert first["preferido"] == "A" and first["score_A"] == 4
    # X fue A en la primera y B en la segunda: gana en las dos órdenes.
    assert eb.combine_orders(first, swapped) == {"pref_x": 1, "consistent": True, "score_diff": 2.0}
    # El juez prefiere siempre el primero: sesgo de posición, no cuenta.
    biased = eb.combine_orders(first, eb.parse_judge(a_wins))
    assert biased["pref_x"] == 0 and biased["consistent"] is False and biased["score_diff"] == 0.0
    assert eb.parse_judge("sin json") is None
    assert eb.combine_orders(None, first)["pref_x"] is None


def test_judge_prompt_is_blind():
    msg = json.loads(eb.judge_user_message("POOL", "texto uno", "texto dos"))
    assert set(msg) == {"empresa", "A", "B"}
    for word in ("completa", "sin_pasajes", "sin_guia", "numantia", "variante"):
        assert word not in eb.JUDGE_RUBRIC.lower() and word not in json.dumps(msg).lower()


def test_sign_test_small_n_is_not_significant():
    assert eb.sign_test_p(5, 0) == pytest.approx(0.0625)
    assert eb.sign_test_p(3, 3) == 1.0
    assert eb.sign_test_p(0, 0) is None


# ------------------------------------------------------------------------------------------- coste y 429


class _Resp:
    def __init__(self):
        self.usage = SimpleNamespace(input_tokens=1000, output_tokens=500)
        self.model = "deepseek-v4.1-flash"
        self.text = "{}"


class _Provider:
    def __init__(self, fail_with: Exception | None = None):
        self.calls, self.fail_with = 0, fail_with

    async def complete(self, request):
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return _Resp()


def _req(task="expert_team.tesis_v2_a"):
    return SimpleNamespace(metadata={"expert_team_task": task}, task="main_financial_analysis")


def test_meter_records_role_cost_and_stops_on_429(tmp_path):
    mod = _script()
    prov = _Provider(fail_with=RuntimeError("HTTP 429 Too Many Requests"))
    meter = mod.Meter(prov, cap_eur=1.0, log_path=tmp_path / "calls.jsonl")
    with pytest.raises(RuntimeError):
        asyncio.run(meter.complete(_req()))
    assert meter.stopped and "429" in meter.stopped
    with pytest.raises(mod.Stop):  # sin reintentos: la siguiente ni sale
        asyncio.run(meter.complete(_req()))
    assert prov.calls == 1


def test_meter_cap_and_cost_by_role(tmp_path):
    mod = _script()
    prov = _Provider()
    meter = mod.Meter(prov, cap_eur=1e-9, log_path=tmp_path / "calls.jsonl")
    asyncio.run(meter.complete(_req("expert_team.valorador_sotp")))
    with pytest.raises(mod.Stop):
        asyncio.run(meter.complete(_req()))
    assert prov.calls == 1
    rows = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]
    by = eb.cost_by_role(rows)
    assert by["expert_team.valorador_sotp"]["calls"] == 1
    assert by["expert_team.valorador_sotp"]["input_tokens"] == 1000
    assert by["expert_team.valorador_sotp"]["cost_eur"] > 0


def test_ablation_only_removes_that_role_input():
    mod = _script()
    ctx = SimpleNamespace(
        passages=[{"text": "p"}],
        guidance=[{"g": 1}],
        analysts=[{"a": 1}],
        price_targets=[],
        insiders={"n": 3},
        optional={"consenso_guia": "x", "deuda_balance": "y"},
        switches=[{"key": "crecimiento"}, {"key": "guia.revenue.fy2026"}],
    )
    a = mod._ablate(ctx, "sin_pasajes")
    assert a.passages == [] and a.guidance == ctx.guidance and ctx.passages  # el original no se toca
    b = mod._ablate(ctx, "sin_guia")
    assert b.guidance == [] and b.switches == [{"key": "crecimiento"}] and b.passages == ctx.passages
    assert b.optional == {
        "deuda_balance": "y",
        "consenso_guia": "hay estimaciones de analistas citadas de la prensa",
    }
    c = mod._ablate(ctx, "sin_analistas")
    assert c.analysts == [] and c.guidance == ctx.guidance and "consenso_guia" in c.optional
    d = mod._ablate(SimpleNamespace(**{**ctx.__dict__, "guidance": []}), "sin_analistas")
    assert d.optional == {"deuda_balance": "y"}
    assert mod._ablate(ctx, "sin_insiders").insiders is None


# ------------------------------------------------------------------------------------------- previsiones


def _rec():
    scen = {
        k: {"horizons": {"5": {"irr": v}, "10": {"irr": v / 2}}}
        for k, v in (("bear", -0.05), ("base", 0.08), ("bull", 0.20))
    }
    return eb.forecast_record(
        ticker="POOL",
        as_of=date(2026, 11, 8),
        price=211.7,
        currency="USD",
        scenarios=scen,
        weighted={"5": 0.077, "10": 0.08},
        method="tir_ev_ebitda",
        probability_choice="neutral",
        kill_switches=[{"key": "margen", "metric": "Margen", "threshold": "< 14 %"}],
        claims=["La tesis descansa en el margen."],
        thesis_fingerprint="f",
        commit="abc",
    )


def test_forecast_record_and_score():
    rec = _rec()
    assert rec["irr"]["5"] == {"bear": -0.05, "base": 0.08, "bull": 0.20}
    assert rec["score_at"] == {"1y": "2027-11-08", "3y": "2029-11-08"}
    assert rec["id"] == _rec()["id"]  # estable
    s = eb.score_forecast(rec, horizon_years=1, price_then=211.7 * 1.10)
    assert s["realized_annual"] == pytest.approx(0.10)
    assert s["inside_bear_bull"] is True and s["error_vs_base"] == pytest.approx(0.02)
    s3 = eb.score_forecast(rec, horizon_years=3, price_then=211.7 * 0.5)
    assert s3["inside_bear_bull"] is False


def test_rank_ic_and_summary():
    assert eb.rank_ic([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert eb.rank_ic([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert eb.rank_ic([1, 2], [1, 2]) is None
    rec = _rec()
    scores = [eb.score_forecast(rec, horizon_years=1, price_then=p) for p in (200.0, 230.0, 260.0)]
    out = eb.summarize_scores(scores)
    assert out["n"] == 3 and out["share_inside_bear_bull"] is not None


def test_committed_forecast_log_is_valid():
    files = sorted((ROOT / "benchmarks").glob("prediccion_log_*.jsonl"))
    assert files, "falta el registro de previsiones versionado"
    for f in files:
        for line in f.read_text().splitlines():
            rec = json.loads(line)
            assert rec["v"] == eb.FORECAST_VERSION
            for key in ("ticker", "as_of", "price", "irr", "kill_switches", "score_at", "id"):
                assert key in rec
            assert set(rec["irr"]["5"]) == {"bear", "base", "bull"}
