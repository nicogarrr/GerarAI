"""C2: los evals de los 8 motores de valoracion son un gate de CI.

El dataset congelado (``evals/valuation/valuation_engines_v1.json``) no es una
suite de tests: se ejecuta con el runner por subprocess, igual que
``tests/test_offline_eval_gates.py`` hace con las tesis. Estos tests son la
puerta de CI: el runner tiene que salir con 0, y el dataset tiene que seguir
teniendo la cobertura que el runner no puede exigir por si solo (un motor sin
controles negativos, un motor que desaparece del registro, un dataset que se
reduce a las pocas filas que todavia pasan).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "valuation" / "valuation_engines_v1.json"
RUNNER = ROOT / "scripts" / "run_valuation_evals.py"

EXPECTED_ENGINES = {
    "standard_dcf",
    "sotp",
    "pre_revenue",
    "holding_company",
    "commodity",
    "bank",
    "insurer",
    "reit",
    # Motor de escenarios (4-nov-2026): cubierto por el routing de TSLA, NBIS
    # y KRKNF del maestro y por tests/test_scenario_engine.py.
    "scenario",
}

# 8 motores x 12 casos = el minimo del encargo.
MIN_CASES = 96
MIN_CASES_PER_ENGINE = 12


@pytest.fixture(scope="module")
def dataset() -> dict:
    return json.loads(DATASET.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--json"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def human_run() -> str:
    result = subprocess.run(
        [sys.executable, str(RUNNER)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_valuation_eval_dataset_passes_all_gates(report: dict) -> None:
    assert report["failures"] == []
    assert report["ok"] is True
    assert report["gates_never_run"] == []
    assert report["checks"] > 0
    assert report["case_count"] >= MIN_CASES
    assert report["engine_count"] == len(EXPECTED_ENGINES)


def test_dataset_covers_every_engine_with_enough_cases(dataset: dict) -> None:
    per_engine = Counter(case["engine"] for case in dataset["cases"])
    assert set(per_engine) == EXPECTED_ENGINES, sorted(per_engine)
    assert len(dataset["cases"]) >= MIN_CASES, len(dataset["cases"])
    for engine, count in sorted(per_engine.items()):
        assert count >= MIN_CASES_PER_ENGINE, (engine, count)


def test_every_engine_has_at_least_one_negative_control(dataset: dict) -> None:
    """Un motor sin control negativo no demuestra que sus puertas muerdan."""
    controls = {
        case["engine"] for case in dataset["cases"] if case.get("expect_gate_failure")
    }
    assert not EXPECTED_ENGINES - controls, sorted(EXPECTED_ENGINES - controls)


def test_negative_controls_actually_failed_their_gate(dataset: dict, report: dict) -> None:
    """Los controles negativos se ejecutaron contra el artefacto REAL del motor.

    El runner exige que la puerta nombrada falle; el informe deja constancia de
    como fallo, asi que un control que dejara de morder sale del informe aqui y no
    de un exit 1 que nadie lee.
    """
    declared = {
        (case["id"], case["expect_gate_failure"]) for case in dataset["cases"]
        if case.get("expect_gate_failure")
    }
    observed = {(row["case"], row["gate"]) for row in report["negative_controls"]}
    assert declared == observed
    for row in report["negative_controls"]:
        assert row["passed"] is False, row
        assert row["details"], row


def test_runner_reports_every_engine_and_gate(human_run: str, report: dict) -> None:
    for engine in sorted(EXPECTED_ENGINES):
        assert f"  {engine}:" in human_run, engine
    for gate, count in report["coverage"]["gates"].items():
        assert count > 0, gate
    assert "NUNCA SE EJECUTO" not in human_run
    assert "Todos los gates en verde." in human_run


def test_every_registered_gate_is_applied_by_some_case(dataset: dict, report: dict) -> None:
    """Ninguna puerta puede quedarse sin ejecutar por un opt-out excesivo."""
    from evals.valuation.valuation_gates import GATES

    declared = {gate for case in dataset["cases"] for gate in case.get("applies_to", [])}
    assert set(GATES) <= declared, sorted(set(GATES) - declared)
    assert set(GATES) == set(report["coverage"]["gates"])


def test_registry_and_dataset_agree_on_the_engine_list(dataset: dict) -> None:
    """El dataset no puede cubrir un motor que el registro ya no tenga."""
    from app.valuation.engines.registry import VALUATION_ENGINES

    assert set(VALUATION_ENGINES) == EXPECTED_ENGINES
    assert {case["engine"] for case in dataset["cases"]} <= set(VALUATION_ENGINES)


def test_every_case_declares_its_obligations(dataset: dict) -> None:
    """Sin declaracion no hay puerta que pueda omitirse sin que se note.

    Cada caso declara lo que las puertas que EJERCITA necesitan: una puerta no
    aplicada no puede exigir su clave, pero una aplicada no puede prescindir de
    ella (eso es lo que devuelven las puertas de ``NON_SKIPPABLE_GATES``).
    """
    from evals.valuation.valuation_gates import NON_SKIPPABLE_GATES

    required_by_gate = {
        "engine_publishable_status": "status",
        "missing_inputs_declared": "missing_inputs",
        "value_matches_closed_form": "closed_form",
        "routing_expected": "engine_key",
        "adr_ratio_basis": "adr_ratio",
    }
    # These two read the ARTIFACT instead of the case declaration: one needs the
    # engine to have weighted its scenarios, the other needs the whole contract.
    assert set(NON_SKIPPABLE_GATES) - set(required_by_gate) == {
        "probabilities_sum_to_one",
        "gate_does_not_omit_itself",
    }
    for case in dataset["cases"]:
        expected = case.get("expected") or {}
        applies = set(case.get("applies_to", []))
        for gate, key in required_by_gate.items():
            if gate in applies:
                assert key in expected, (case["id"], gate, key)
        if "status" in expected:
            assert expected["status"] in {"ok", "partial", "insufficient_data"}, case["id"]
        if case.get("expect_gate_failure"):
            assert case["expect_gate_failure"] in applies, case["id"]


def test_dataset_is_frozen_against_the_engine_model_version(dataset: dict) -> None:
    """``MODEL_VERSION`` es parte del contrato: cambiarlo rompe los evals."""
    from app.valuation.engines.base import MODEL_VERSION

    assert dataset["model_version"] == MODEL_VERSION
