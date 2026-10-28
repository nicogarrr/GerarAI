"""Entrada pytest del fuzzing Schemathesis (ver fuzz_app.py)."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("schemathesis")

from hypothesis import HealthCheck, settings  # noqa: E402
from schemathesis import checks  # noqa: E402

from tests.fuzz.fuzz_app import LAST_SERVER_ERRORS, MAX_EXAMPLES, schema  # noqa: E402

# Por defecto solo cuenta lo que es un bug seguro: un 500 no controlado. Los
# 502/503 de funciones desactivadas (RAG, LLM, Telegram sin configurar) son
# deliberados. FUZZ_STRICT=1 añade la conformidad con el esquema (códigos no
# documentados, 422 con detail en texto, fechas sin zona en SQLite): útil para
# revisar el contrato, pero hoy da falsos positivos conocidos.
STRICT_CHECKS = [
    checks.response_schema_conformance,
    checks.status_code_conformance,
    checks.content_type_conformance,
]


def no_unhandled_server_error(ctx, response, case):  # noqa: ARG001
    if response.status_code == 500:
        detail = response.text[:300]
        raise AssertionError(f"500 no controlado en {case.operation.label}: {detail}")


CHECKS = [no_unhandled_server_error] + (
    STRICT_CHECKS if os.environ.get("FUZZ_STRICT") == "1" else []
)


@schema.parametrize()
@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    derandomize=os.environ.get("FUZZ_DERANDOMIZE", "1") == "1",
)
def test_api_operation(case):
    LAST_SERVER_ERRORS.clear()
    try:
        case.call_and_validate(checks=CHECKS)
    except BaseException as exc:
        _report(case, exc)
        raise


def _report(case, exc) -> None:
    path = os.environ.get("FUZZ_REPORT")
    if not path:
        return
    import json

    record = {
        "operation": f"{case.operation.method.upper()} {case.operation.path}",
        "error": repr(exc)[:3000],
        "server_errors": LAST_SERVER_ERRORS[-2:],
        "path_parameters": case.path_parameters,
        "query": case.query,
        "body": repr(getattr(case, "body", None))[:1000],
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
