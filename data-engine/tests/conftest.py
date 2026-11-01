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
# Los tests gated a CI Postgres (round-trips reales de Alembic) necesitan la
# URL original del job; sin esta copia la pierden al forzar el sqlite hermetico.
os.environ.setdefault("CAVAAI_ORIGINAL_DATABASE_URL", os.environ.get("DATABASE_URL", ""))
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
    base._free_quota_breaker.clear()
    base._free_tier_breaker_until.clear()
    base._interactive_quota_breaker_until.clear()
    base._free_quota_breaker_until.clear()
    yield
    base._free_tier_breaker.clear()
    base._free_tier_breaker_status.clear()
    base._interactive_quota_breaker.clear()
    base._free_quota_breaker.clear()
    base._free_tier_breaker_until.clear()
    base._interactive_quota_breaker_until.clear()
    base._free_quota_breaker_until.clear()


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


# ---------------------------------------------------------------------------
# Aislamiento del Redis compartido del job de CI
# ---------------------------------------------------------------------------
#
# Backend quality instala un redis-server real y corre xdist -n 2. Los claims
# de coalescencia (coalesce:*, coalesce-enq:*, ventanas de hasta 20 h), los
# leases de jobs (cavaai:job-lease:*), el pacing global (global_pacer:*) y
# los disyuntores (gdelt:circuit:*, sec_breaker:*) sobreviven entre tests y
# se comparten entre los dos workers: el cluster DCA del 31-oct (77 fallos)
# era el claim coalesce:evaluate_dca_signals:7 (ventana 20 h) de un test
# haciendo fresh_or_running al siguiente, antes de sus monkeypatches.
#
# Dos medidas que se complementan:
# 1. Una DB logica por worker de xdist (gw0 -> db0, gw1 -> db1): el Redis deja
#    de ser compartido entre procesos y la limpieza de abajo ya no puede
#    borrar el claim fresco del otro worker.
# 2. Limpieza ANTES de cada test, solo de las claves de la app, dentro de la
#    DB propia del worker. Solo antes (no despues): el siguiente test ya
#    empieza limpio y cada borrado extra solo abre ventanas para pisar
#    estado que otro test aun esta usando.
#
# OPT-IN EXPLICITO (revision del piloto): TEST_REDIS_EPHEMERAL=1 declara que
# el Redis alcanzable es desechable; lo pone el workflow de CI, que instala
# un redis-server solo para el job. Sin el NO se limpia nada NI se reasigna
# DB: APP_ENV=test no prueba que el Redis sea desechable (este propio
# conftest lo fija con setdefault) y un REDIS_URL heredado del stack de
# desarrollo apunta a una BD con datos reales que no se toca.
#
# Sin Redis alcanzable la app usa su fallback local en proceso: fail-open.

_TEST_REDIS_EPHEMERAL_VAR = "TEST_REDIS_EPHEMERAL"

# Los tres primeros son dedup/lease del scheduler; global_pacer y los dos
# breakers son el estado compartido en Redis de los commits de colas del
# 31-oct (d2b567c pacing global, 9092063 disyuntores, d1f2578 cache live de
# fair-value): mismo patron de fuga.
_REDIS_TEST_KEY_PREFIXES = (
    "cavaai:*",
    "coalesce:*",
    "coalesce-enq:*",
    "global_pacer:*",
    "gdelt:circuit:*",
    "sec_breaker:*",
    "fair_value_live:*",
)


def _test_redis_ephemeral() -> bool:
    return os.environ.get(_TEST_REDIS_EPHEMERAL_VAR) == "1"


def _redis_test_url() -> str | None:
    try:
        from app.core.config import get_settings

        return get_settings().redis_url
    except Exception:  # noqa: BLE001 - sin settings no hay nada que limpiar
        return None


def _worker_redis_url() -> str | None:
    """URL de Redis con la DB logica propia del worker, o None si no procede.

    Solo con el opt-in explicito y bajo xdist: sin el no se reasigna nada,
    porque un REDIS_URL heredado apunta al Redis del stack de desarrollo.
    """
    if not _test_redis_ephemeral():
        return None
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return None
    import re
    from urllib.parse import urlsplit, urlunsplit

    match = re.fullmatch(r"gw(\d+)", worker)
    db = int(match.group(1)) if match else 0
    base = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    parts = urlsplit(base)
    return urlunsplit(parts._replace(path=f"/{db}"))


def reset_shared_redis_dedup_state() -> None:
    """Borra las claves de dedup/lease/pacing de la app en la DB del worker.

    Solo con el opt-in TEST_REDIS_EPHEMERAL=1 (Redis desechable declarado):
    sin el no se borra absolutamente nada.
    """
    if not _test_redis_ephemeral():
        return
    url = _redis_test_url()
    if not url:
        return
    try:
        import redis as redis_sync

        from app.core.redis_retry import no_retry

        client = redis_sync.Redis.from_url(
            url, socket_connect_timeout=0.25, socket_timeout=0.5, retry=no_retry()
        )
        try:
            for pattern in _REDIS_TEST_KEY_PREFIXES:
                cursor = 0
                while True:
                    cursor, keys = client.scan(cursor=cursor, match=pattern, count=200)
                    if keys:
                        client.delete(*keys)
                    if cursor == 0:
                        break
        finally:
            client.close()
    except Exception:  # noqa: BLE001 - sin Redis no hay estado compartido que limpiar
        pass


@pytest.fixture(autouse=True, scope="session")
def _redis_db_por_worker():
    """Una DB logica de Redis por worker de xdist (gw0 -> db0, gw1 -> db1).

    Se reescribe REDIS_URL antes de que corra ningun test: _redis_client() es
    perezoso por proceso y get_settings se re-levanta en cada test (ver
    reset_settings_cache), asi que todos los accesos posteriores usan la DB
    propia del worker. Sin TEST_REDIS_EPHEMERAL=1 no se toca la URL.
    """
    url = _worker_redis_url()
    if url is not None:
        os.environ["REDIS_URL"] = url
        from app.core.config import get_settings

        get_settings.cache_clear()
    yield


@pytest.fixture(autouse=True)
def _reset_shared_redis_dedup_state():
    reset_shared_redis_dedup_state()
    yield
