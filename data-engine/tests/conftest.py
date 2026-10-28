"""Explicit test-only environment defaults.

Research authentication is mandatory in the application. Most service tests do
not exercise the HTTP identity bridge, so they opt out here. Dedicated security
tests override the dependency and verify signed, tenant-scoped requests.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ["RESEARCH_AUTH_REQUIRED"] = "false"
# Keep TestClient lifespans quiet: the worker scheduler must not start in tests.
os.environ["WORKERS_ENABLED"] = "false"
# Backend de matplotlib fijo y sin pantalla. Si el entorno hereda otro (p. ej. el
# de Jupyter/VS Code, `module://matplotlib_inline.backend_inline`, o TkAgg sin
# display), importar pyplot falla durante la recolección de los tests de riesgo.
# Se fuerza ANTES de que ningún test importe matplotlib.
os.environ["MPLBACKEND"] = "Agg"
# Hermetic tests: never inherit the local Postgres stack. Environment
# variables take precedence over the .env file in pydantic-settings, so this
# forces a disposable SQLite file for every test process.
#
# Fichero UNICO por sesion, no un `./cavaai_test.db` fijo. Con el nombre fijo
# el esquema y las filas de una corrida se arrastraban a la siguiente: 19 tests de
# test_calculated_metrics.py fallaban en la segunda ejecucion en la misma
# maquina y pasaban en un checkout limpio, porque sus fixtures de limpieza
# borran por ticker y no el resto. Un fichero por sesion hace la suite
# idempotente sin cambiar nada mas (sigue siendo un fichero real en disco, que
# es lo que necesitan los tests que usan SessionLocal() en lugar de :memory:,
# ya que cada conexion a :memory: abriria su propia base).
_TEST_DB_PATH = Path(
    os.environ.get("CAVAAI_TEST_DB")
    or f"cavaai_test_{os.getpid()}_{uuid4().hex[:8]}.db"
)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Borra la base de datos de la sesion al terminar.

    Hay que cerrar el engine antes: en Windows no se puede borrar un fichero
    con una conexion abierta, y el engine mantiene el pool vivo.
    """
    try:
        from app.core.database import engine

        engine.dispose()
    except Exception:  # pragma: no cover - best effort
        pass
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{_TEST_DB_PATH}{suffix}")
        try:
            candidate.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best effort
            pass

# Importing main no debe filtrar secretos locales al proceso de test. La API
# legacy (routers/) y los módulos de servicio (modules/) fueron retirados;
# los servicios de app/ pueden llamar load_dotenv() en import time.
# Tests must stay hermetic:
# Settings(_env_file=None) must observe no secrets.
_TEST_ISOLATED_ENV_VARS = (
    "RESEARCH_AUTH_SECRET",
    "LLM_SETTINGS_ENCRYPTION_KEY",
    "DOCUMENT_STORAGE_BACKEND",
    "FMP_API_KEY",
    "FINNHUB_API_KEY",
    "FRED_API_KEY",
    "OPENCODE_GO_API_KEY",
    "TELEGRAM_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_API_BASE_URL",
    "TELEGRAM_TIMEOUT_SECONDS",
    "TELEGRAM_APPROVAL_ENABLED",
    "TELEGRAM_APPROVAL_STATE_PATH",
    "TELEGRAM_APPROVAL_POLL_INTERVAL_SECONDS",
    "INSIDER_ALERTS_ENABLED",
    "ALERT_EMAIL_WEBHOOK_URL",
    "ALERT_PUSH_WEBHOOK_URL",
    "SMTP_HOST",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "ALERT_EMAIL_TO",
    # Respaldos LLM en modo auto: una clave del .env local no debe encenderlos.
    "GROQ_API_KEY",
    "GROQ_CHAT_FALLBACK_ENABLED",
    "GROQ_FREE_PLAN_CONFIRMED",
    "GROQ_ZDR_CONFIRMED",
    "GEMINI_API_KEY",
    "GEMINI_CHAT_FALLBACK_ENABLED",
    "GEMINI_FREE_PLAN_CONFIRMED",
    "OPENROUTER_API_KEY",
)

# Pydantic Settings still reads .env when the environment variable is absent.
# Explicit safe values therefore win over a developer's local dotenv file.
_TEST_ISOLATED_ENV_DEFAULTS = {
    "TELEGRAM_ENABLED": "false",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "TELEGRAM_API_BASE_URL": "https://api.telegram.org",
    "TELEGRAM_TIMEOUT_SECONDS": "10",
    "TELEGRAM_APPROVAL_ENABLED": "false",
    "TELEGRAM_APPROVAL_STATE_PATH": "./storage/test-telegram-approval-offset",
    "TELEGRAM_APPROVAL_POLL_INTERVAL_SECONDS": "15",
    "INSIDER_ALERTS_ENABLED": "false",
    "ALERT_EMAIL_WEBHOOK_URL": "",
    "ALERT_PUSH_WEBHOOK_URL": "",
    "SMTP_HOST": "",
    "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "",
    "SMTP_FROM": "",
    "ALERT_EMAIL_TO": "",
    "GROQ_API_KEY": "",
    "GROQ_CHAT_FALLBACK_ENABLED": "auto",
    "GROQ_FREE_PLAN_CONFIRMED": "false",
    "GROQ_ZDR_CONFIRMED": "false",
    "GEMINI_API_KEY": "",
    "GEMINI_CHAT_FALLBACK_ENABLED": "auto",
    "GEMINI_FREE_PLAN_CONFIRMED": "false",
    "OPENROUTER_API_KEY": "",
}
os.environ.update(_TEST_ISOLATED_ENV_DEFAULTS)


@pytest.fixture(autouse=True)
def isolate_local_dotenv():
    """Remove local delivery config from every test, regardless of import order."""
    saved = {key: os.environ.pop(key) for key in _TEST_ISOLATED_ENV_VARS if key in os.environ}
    os.environ.update(_TEST_ISOLATED_ENV_DEFAULTS)
    try:
        yield
    finally:
        for key in _TEST_ISOLATED_ENV_VARS:
            os.environ.pop(key, None)
        os.environ.update(saved)


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Clear cached settings after isolation, not just before the test starts."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_sec_client_state():
    """Cache y reloj compartidos del SECClient son estado de proceso: sin
    reiniciarlos, un test veria la respuesta cacheada de otro (F351)."""
    from app.services.connectors.sec import reset_sec_client_state

    reset_sec_client_state()
    yield
    reset_sec_client_state()


@pytest.fixture(autouse=True)
def _no_live_benchmark(monkeypatch):
    """Los tests nunca llaman a Yahoo para el SPY de la comparativa."""
    from app.services import portfolio_intelligence_service as svc

    monkeypatch.setattr(svc, "_live_benchmark_prices", lambda cutoff: None)


@pytest.fixture(autouse=True)
def _reset_movers_cache():
    """La caché de Movers es por proceso; cada test parte de una BD distinta."""
    from app.services import movers_cache

    movers_cache.clear_local()
    yield
    movers_cache.clear_local()


@pytest.fixture(autouse=True)
def _reset_chat_quota_cooldowns():
    from app.llm.chat_provider import reset_quota_cooldowns

    reset_quota_cooldowns()
    yield
    reset_quota_cooldowns()


@pytest.fixture(autouse=True)
def isolate_llm_free_tier_breaker():
    """Quota cooldowns persist in production, never across hermetic test cases."""
    from app.llm import base
    base._free_tier_breaker.clear()
    base._free_tier_breaker_status.clear()
    base._interactive_quota_breaker.clear()
    yield
    base._free_tier_breaker.clear()
    base._free_tier_breaker_status.clear()
    base._interactive_quota_breaker.clear()


@pytest.fixture(autouse=True)
def _reset_filing_deadline_failure_cache():
    """La memoria corta de fallos de plazos 10-Q/10-K es estado global de proceso."""
    from app.services import catalyst_calendar_service

    catalyst_calendar_service._FAILED_UNTIL.clear()
    yield
    catalyst_calendar_service._FAILED_UNTIL.clear()


@pytest.fixture(autouse=True)
def _reset_historical_stress_failure_cache():
    from app.services import historical_stress_service

    historical_stress_service._FAILED_UNTIL.clear()
    yield
    historical_stress_service._FAILED_UNTIL.clear()
