"""Ronda 3: fuzzing positivo + negativo con comprobación de fugas de texto interno.

Además de "sin 500", cualquier respuesta (también 4xx/502/503) no puede llevar
texto de excepción en bruto: tracebacks, rutas de fichero, nombres de clase de
excepción de Python/SQLAlchemy/drivers ni SQL. Ver docs/testing/api-fuzzing.md.
"""
from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("schemathesis")

from hypothesis import HealthCheck, settings  # noqa: E402
from schemathesis import GenerationMode  # noqa: E402

from tests.fuzz.fuzz_app import LAST_SERVER_ERRORS, schema  # noqa: E402
from tests.fuzz.test_schemathesis_api import _report  # noqa: E402

LEAK = re.compile(
    r"Traceback \(most recent call last\)"
    r"|File \"[^\"]+\.py\", line \d+"
    r"|\b(?:sqlalchemy|psycopg2?|sqlite3|pydantic_core|asyncpg|httpx|requests|urllib3)\.[A-Za-z_.]*(?:Error|Exception)\b"
    r"|\b(?:IntegrityError|OperationalError|ProgrammingError|DataError|InterfaceError|StatementError)\b"
    r"|\b(?:KeyError|TypeError|AttributeError|ZeroDivisionError|IndexError|UnboundLocalError|NameError|AssertionError|RecursionError|OverflowError|InvalidOperation|DecimalException)\b"
    r"|\(Background on this error at"
    r"|\[SQL: |\bSELECT .+ FROM \w+"
    r"|/home/|/app/app/|site-packages",
    re.S,
)
MODES = [GenerationMode.POSITIVE, GenerationMode.NEGATIVE] if os.environ.get("FUZZ_NEGATIVE", "1") == "1" else [GenerationMode.POSITIVE]
MAX = int(os.environ.get("FUZZ_MAX_EXAMPLES", "5"))


def no_server_error_or_leak(ctx, response, case):  # noqa: ARG001
    stats = os.environ.get("FUZZ_STATS")
    if stats:
        with open(stats, "a", encoding="utf-8") as fh:
            fh.write(f"{case.operation.label}\t{response.status_code}\n")
    if response.status_code == 500:
        raise AssertionError(f"500 no controlado en {case.operation.label}: {response.text[:300]}")
    ctype = response.headers.get("content-type", [""])
    ctype = ctype[0] if isinstance(ctype, list) else ctype
    if "json" not in ctype and "text" not in ctype:
        return
    text = response.text or ""
    if response.status_code < 400:
        return
    match = LEAK.search(text)
    if match:
        raise AssertionError(
            f"texto interno en la respuesta {response.status_code} de {case.operation.label}: "
            f"{text[max(0, match.start() - 150): match.end() + 150]!r}"
        )


r3_schema = schema.clone()
r3_schema.config.generation.update(modes=MODES)


@r3_schema.parametrize()
@settings(
    max_examples=MAX,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    derandomize=os.environ.get("FUZZ_DERANDOMIZE", "1") == "1",
)
def test_api_operation_negative_and_leaks(case):
    LAST_SERVER_ERRORS.clear()
    try:
        case.call_and_validate(checks=[no_server_error_or_leak])
    except BaseException as exc:
        _report(case, exc)
        raise
