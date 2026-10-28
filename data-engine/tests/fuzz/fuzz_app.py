"""Fuzzing de la API con Schemathesis contra el esquema OpenAPI del data-engine.

Ejecuta cada operación del esquema con ejemplos generados (property-based) y
comprueba: sin 500, respuesta conforme al esquema declarado, códigos de estado
documentados. Las peticiones van firmadas de verdad (HMAC ligado a método, ruta
y cuerpo) con la auth estricta activa: no se desactiva la verificación.

Uso:
    RUN_FUZZ=1 FUZZ_MAX_EXAMPLES=10 python -m pytest tests/fuzz -p no:cacheprovider
El número de ejemplos por operación está acotado (por defecto 5) para CI.
"""

from __future__ import annotations

import os
import socket

import pytest

pytest.importorskip("schemathesis")

import schemathesis  # noqa: E402

FUZZ_SECRET = "schemathesis-fuzz-secret-with-at-least-32-chars"
TENANT_HEADER = "x-fuzz-tenant"
DEFAULT_TENANT = "fuzz-tenant-a"
MAX_EXAMPLES = int(os.environ.get("FUZZ_MAX_EXAMPLES", "5"))

# Sin red: ni Yahoo, ni SEC, ni LLMs. Cualquier conexión saliente falla al
# instante (los handlers deben responder con un error controlado, no 500).
for _var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
    os.environ[_var] = "http://127.0.0.1:9"
os.environ["NO_PROXY"] = "testserver"
_real_create_connection = socket.create_connection


def _local_only(address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else address
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise OSError(f"network disabled in fuzz tests: {host}")
    return _real_create_connection(address, *args, **kwargs)


socket.create_connection = _local_only  # type: ignore[assignment]


def _auth_settings():
    from tests.auth_helpers import auth_settings

    return auth_settings(strict=True, secret=FUZZ_SECRET, app_env="test")


class SigningASGI:
    """Firma cada petición como lo hace el puente de identidad del frontend.

    No relaja la auth: el backend verifica la firma ligada real. El tenant se
    elige con la cabecera ``x-fuzz-tenant`` (por defecto ``fuzz-tenant-a``).
    Una petición con ``x-fuzz-unsigned: 1`` sale sin firma (sonda de bypass).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        headers = [(k, v) for k, v in scope["headers"] if not k.lower().startswith(b"x-cavaai-")]
        lookup = {k.lower(): v for k, v in headers}
        if lookup.get(b"x-fuzz-unsigned") != b"1":
            from tests.auth_helpers import bound_headers

            tenant = lookup.get(TENANT_HEADER.encode(), DEFAULT_TENANT.encode()).decode()
            signed = bound_headers(
                FUZZ_SECRET, tenant, f"user-{tenant}",
                method=scope["method"], path=scope["path"], body=body,
            )
            headers += [(k.lower().encode(), v.encode()) for k, v in signed.items()]
        scope = dict(scope, headers=headers)
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


LAST_SERVER_ERRORS: list[str] = []


def _stub_task_queue() -> None:
    """Los endpoints que encolan trabajo (dramatiq) no necesitan Redis aquí."""
    from app.workers import dramatiq_app

    def _enqueue(message, *, delay=None):  # noqa: ARG001
        return message

    dramatiq_app.broker.enqueue = _enqueue  # type: ignore[method-assign]


def _record_unhandled(app) -> None:
    """Guarda el traceback de cada 500 no controlado para el informe."""
    import traceback

    original = app.exception_handlers[Exception]

    async def handler(request, exc):
        LAST_SERVER_ERRORS.append(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:]
        )
        return await original(request, exc)

    app.exception_handlers[Exception] = handler


def _build_app():
    import main
    from app.core import auth as auth_module
    from app.core.database import init_db
    from app.seed import seed

    auth_module.get_settings = _auth_settings  # type: ignore[assignment]
    _stub_task_queue()
    _record_unhandled(main.app)
    init_db()
    seed()
    return SigningASGI(main.app)


APP = _build_app()
schema = schemathesis.openapi.from_asgi("/openapi.json", APP)
