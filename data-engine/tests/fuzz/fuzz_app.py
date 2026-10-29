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


def _disable_rate_limits() -> None:
    """Sin límite de peticiones durante el fuzzing.

    Todas las peticiones salen del mismo tenant y de la misma IP: con el
    límite activo, a los pocos segundos casi todo respondía 429 (o el 429 del
    middleware de fallos de auth tras 30 respuestas 401) y la mayoría de las
    operaciones no llegaban nunca al handler. El límite tiene sus propios tests.
    """
    from app.core import rate_limit
    from app.core.config import get_settings

    relaxed = get_settings().model_copy(update={"rate_limit_enabled": False})
    rate_limit.get_settings = lambda: relaxed  # type: ignore[assignment]


def _build_app():
    import main
    from app.core import auth as auth_module
    from app.core.database import init_db
    from app.seed import seed

    auth_module.get_settings = _auth_settings  # type: ignore[assignment]
    _disable_rate_limits()
    _stub_task_queue()
    _record_unhandled(main.app)
    init_db()
    seed()
    app = SigningASGI(main.app)
    _seed_tenant_data(app)
    return app


# Tickers del maestro sembrado. Sin ellos, cada {ticker}/{symbol} generado al
# azar respondía 404 y el handler de verdad no se ejecutaba nunca.
KNOWN_TICKERS = ["MSFT", "NVDA", "ASTS", "TSLA", "AMZN", "NVO", "BABA", "KRKNF"]


def _seed_tenant_data(app) -> None:
    """Datos reales para el tenant del fuzzing: cartera, plan, watchlist y tesis.

    Con la base vacía casi todos los handlers devolvían la rama «sin datos»;
    con esto el fuzzing recorre los cálculos (FIFO, divisas, fiscalidad, DCA,
    tesis ancladas). Solo se usa la API firmada y escrituras con el tenant fijado.
    """
    from datetime import UTC, datetime
    from decimal import Decimal

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import Company, Tenant
    from app.models.entities import ThesisVersion
    from app.models.paper_trading import PaperTrade

    client = TestClient(app)
    trades = [
        ("MSFT", "buy", 10, 300, "USD", "2024-01-15"),
        ("MSFT", "sell", 4, 410, "USD", "2025-03-10"),
        ("NVDA", "buy", 20, 45.5, "USD", "2024-06-03"),
        ("ASTS", "buy", 100, 9.25, "EUR", "2025-02-11"),
        ("ASTS", "sell", 100, 7.1, "EUR", "2025-05-02"),
        ("ASTS", "buy", 50, 7.0, "EUR", "2025-05-20"),
    ]
    for ticker, action, qty, price, currency, day in trades:
        client.post("/api/portfolio/transactions", json={
            "ticker": ticker, "action": action, "quantity": qty, "price": price,
            "currency": currency, "trade_date": day,
        })
    client.put("/api/plan", json={"monthly_contribution": 500, "start_date": "2025-01-01",
                                  "horizon_years": 20})
    client.put("/api/settings/dca", json={"up_min_level": 3, "down_max_level": 1})
    with SessionLocal() as db:
        tenant_id = db.scalar(select(Tenant.id).where(Tenant.external_id == DEFAULT_TENANT))
        if tenant_id is None:
            return
        db.info["tenant_id"] = tenant_id
        companies = {c.ticker: c.id for c in db.scalars(select(Company).where(Company.ticker.in_(KNOWN_TICKERS)))}
        now = datetime(2026, 10, 1, tzinfo=UTC)
        for ticker in ("MSFT", "NVDA"):
            if ticker not in companies:
                continue
            versions = [
                ThesisVersion(
                    tenant_id=tenant_id, company_id=companies[ticker], version=v, status="draft",
                    thesis_markdown=f"# Tesis {ticker} v{v}", executive_summary=f"Resumen {ticker} v{v}",
                    rating="watch", created_at=now, current_price=Decimal("100"), bear_value=Decimal("80"),
                    base_value=Decimal("120"), bull_value=Decimal("160"), expected_value=Decimal("125"),
                    invalidation_criteria=["Margen bruto < 60%"],
                )
                for v in (1, 2)
            ]
            db.add_all(versions)
            db.flush()
            db.add(PaperTrade(
                tenant_id=tenant_id, proposal_key=f"fuzz-{ticker}", ticker=ticker, direction="long",
                horizon="short", thesis="tesis de prueba", conviction=Decimal("0.5"),
                proposed_entry=Decimal("100"), stop=Decimal("90"), target=Decimal("120"),
                quantity=Decimal("1"), inference_basis="Inferencia: prueba", status="pending",
                thesis_version_id=versions[0].id,
            ))
        db.commit()


APP = _build_app()
schema = schemathesis.openapi.from_asgi("/openapi.json", APP)


@schema.hook
def flatmap_path_parameters(context, path_parameters):  # noqa: ARG001
    """La mitad de las veces, {ticker}/{symbol} es un ticker sembrado (ver KNOWN_TICKERS)."""
    from hypothesis import strategies as st

    keys = [key for key in (path_parameters or {}) if key in ("ticker", "symbol")]
    if not keys:
        return st.just(path_parameters)
    known = st.sampled_from(KNOWN_TICKERS).map(
        lambda ticker: {**path_parameters, **dict.fromkeys(keys, ticker)}
    )
    return st.one_of(st.just(path_parameters), known)
