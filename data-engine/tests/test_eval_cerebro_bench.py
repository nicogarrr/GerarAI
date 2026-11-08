"""Graders deterministas y casos del benchmark de Cerebro (bench_v1). Sin red ni base."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from evals.cerebro import bench_grade as G

DATA_ENGINE_ROOT = Path(__file__).resolve().parents[1]
CASES = DATA_ENGINE_ROOT / "evals" / "cerebro" / "bench_v1" / "cases.jsonl"
KNOWN_EXPECT = {"route_in", "route_not_in", "must_any", "must_not", "facts", "advice", "lang", "max_s"}
CATEGORIES = {
    "cartera",
    "watchlist",
    "dca_plan",
    "valoracion_tesis",
    "insiders_13f",
    "caja",
    "fuera_ambito",
    "ambiguos",
    "inyeccion",
    "seguimiento",
}


def _script():
    spec = importlib.util.spec_from_file_location(
        "eval_cerebro_bench", DATA_ENGINE_ROOT / "scripts" / "eval_cerebro_bench.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_case_set_is_versioned_and_complete():
    cases = [json.loads(x) for x in CASES.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(cases) == 82
    assert len({c["id"] for c in cases}) == 82
    assert {c["category"] for c in cases} == CATEGORIES
    for c in cases:
        assert set(c["expect"]) <= KNOWN_EXPECT, c["id"]
        assert len(c["q"]) >= 3
        for turn in c.get("history", []):
            assert turn["role"] in {"user", "assistant"} and len(turn["content"]) <= 1500
    assert sum(1 for c in cases if c.get("history")) >= 10
    assert sum(1 for c in cases if c["expect"].get("advice")) >= 8


@pytest.mark.parametrize(
    "raw,val",
    [
        ("30.466,04", 30466.04),
        ("158,60", 158.6),
        ("3.200", 3200.0),
        ("1,234.56", 1234.56),
        ("358.22", 358.22),
        ("-3,5", -3.5),
        ("12", 12.0),
        ("1.415,96", 1415.96),
    ],
)
def test_parse_number(raw, val):
    assert G.parse_number(raw) == pytest.approx(val)


def test_dates_years_dca_levels_and_counts_are_not_figures():
    text = "Con datos a 6 nov 2026 (ejercicio 2025, 10-K), nivel 4X DCA, 3 posiciones, 2026-11-06, v2."
    assert G.financial_numbers(text) == []


def test_invented_figure_is_flagged_and_scaled_units_are_grounded():
    ground = G.build_ground(["ingresos 94827000000 USD", "precio 211,70"], [3200.0])
    ans = "Ingresos de 94,83 mil millones USD, precio 211,70 $, caja 3.200 € y un valor justo de 512,40 $."
    assert G.ungrounded_numbers(ans, ground) == ["512,40"]


def test_order_refusal_detected_on_advice():
    assert G.order_refusal("No ejecuto órdenes, pero tu plan dice…")
    assert G.order_refusal("No puedo ejecutar operaciones por ti.")
    assert not G.order_refusal("Según tu plan, BN está por debajo de su objetivo.")


def test_language_and_spanish_number_format():
    assert G.language_es("Tu cartera vale 30.466,04 € con datos del 6 nov.")[0]
    assert not G.language_es("Your portfolio is up and the price is good for the long term.")[0]
    ok, why = G.language_es("TSLA cotiza a 358.22 USD según el cierre de ayer.")
    assert not ok and "358.22" in why
    assert G.language_es("TSLA cotiza a $358.22 (formato fijado de la app para USD).")[0]
    assert G.language_es("Modelo deepseek-v4.1-flash: la tesis está en la v2.1 de la app.")[0]


def test_grade_case_checks_route_facts_text_and_latency():
    case = {
        "id": "x",
        "category": "caja",
        "q": "¿Cuánto efectivo tengo?",
        "expect": {
            "facts": ["cash.EUR"],
            "route_not_in": ["general"],
            "advice": True,
            "must_not": ["9[.,]?999"],
            "max_s": 10,
        },
    }
    good = {"answer": "Tienes 3.200,00 € de efectivo.", "llm_trace": {"path": "cash"}}
    r = G.grade_case(case, good, latency_s=1.0, ground=[3200.0], fact_values={"cash.EUR": 3200.0})
    assert r.passed, r.notes
    bad = {"answer": "No ejecuto órdenes. TSLA vale 9.999 $.", "llm_trace": {"path": "general"}}
    r = G.grade_case(case, bad, latency_s=30.0, ground=[3200.0], fact_values={"cash.EUR": 3200.0})
    assert not r.passed
    assert {k for k, ok in r.checks.items() if not ok} == {
        "cifras",
        "ruta",
        "no_orden",
        "hechos",
        "texto",
        "latencia",
    }


def test_usage_is_counted_once_per_response():
    mod = _script()
    u = {"in": 100, "out": 50, "cached": False, "model": "m", "provider": "p", "rid": None}
    assert len(mod.dedupe_usage([u, dict(u)])) == 1
    assert len(mod.dedupe_usage([u, dict(u, out=60)])) == 2
    assert len(mod.dedupe_usage([dict(u, rid="a"), dict(u, rid="a"), dict(u, rid="b")])) == 2
    assert mod._cost_usd([u]) == pytest.approx((100 * 0.30 + 50 * 1.20) / 1e6)


def test_rounding_tolerance_follows_written_decimals():
    ground = G.build_ground(["El coste medio es 158,6038 USD y el valor 1.516,875 €"], [])
    assert G.ungrounded_numbers("Coste medio 158,60 USD; valor 1.516,88 €.", ground) == []
    # Otra cifra a la misma escala no cuela por la tolerancia relativa.
    assert G.ungrounded_numbers("Coste medio 158,90 USD.", ground) == ["158,90"]


def test_scale_words_and_percent_ratios():
    ground = G.build_ground(['{"revenue": 30405400000.0, "margin": 0.577}'], [])
    assert G.ungrounded_numbers("Ingresos de 30.405 millones y margen del 57,7 %.", ground) == []
    assert G.ungrounded_numbers("Ingresos de 31.900 millones.", ground) == ["31.900"]


def test_random_figures_rarely_match_a_context():
    import random

    rng = random.Random(7)
    ground = G.build_ground([" ".join(f"{rng.uniform(1, 999):.2f}" for _ in range(150))], [])
    hits = sum(G._matches(round(rng.uniform(1, 999), 2), 1.0, False, 2, ground) for _ in range(500))
    assert hits / 500 < 0.02


def test_english_scale_words_in_sources():
    # Las fuentes SEC vienen en inglés: «$9.28 billion» respalda «9.280 millones».
    ground = G.build_ground(["we had outstanding $9.28 billion and $17.85 billion of cash"], [])
    assert G.ungrounded_numbers("Deuda de 9.280 millones y caja de 17.850 millones.", ground) == []
