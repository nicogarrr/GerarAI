"""Modo stateful de Schemathesis: secuencias de llamadas encadenadas por links.

Schemathesis infiere links entre operaciones (p. ej. crear filtro → editarlo →
ejecutarlo → borrarlo; listar reglas → borrar una) y recorre cadenas de pasos
con ids reales devueltos por la propia API. Solo falla con un 500 no controlado.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("schemathesis")

from hypothesis import HealthCheck, Phase, settings  # noqa: E402

from tests.fuzz.fuzz_app import schema  # noqa: E402

STEPS = int(os.environ.get("FUZZ_STATEFUL_STEPS", "6"))
EXAMPLES = int(os.environ.get("FUZZ_STATEFUL_EXAMPLES", "10"))


class APIWorkflows(schema.as_state_machine()):
    def validate_response(self, response, case, **kwargs):  # noqa: ARG002
        if response.status_code == 500:
            raise AssertionError(
                f"500 no controlado en {case.operation.label}: {response.text[:300]}"
            )


TestAPIWorkflows = APIWorkflows.TestCase
TestAPIWorkflows.settings = settings(
    max_examples=EXAMPLES,
    stateful_step_count=STEPS,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    derandomize=os.environ.get("FUZZ_DERANDOMIZE", "1") == "1",
    # La API tiene estado (la BD persiste entre ejemplos): reproducir o encoger
    # una secuencia ya no ve los mismos ids y Hypothesis lo marca como
    # FlakyStrategyDefinition. Solo generamos; el fallo trae su traza.
    phases=[Phase.generate],
)
