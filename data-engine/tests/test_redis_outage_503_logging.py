"""Los 503 fail-closed por Redis caído dejan log estructurado (PR #3089).

La ráfaga de lecturas de una ficha (una llamada por sección a
``/api/companies/<ticker>/...``) con el Redis de producción caído devolvía
503s que solo se veían en el access log, sin ticker ni causa: no se podía
acotar la avería a una empresa. El parche registra un warning estructurado
por 503 (rate_limit_backend_unavailable, auth_nonce_backend_unavailable,
llm_test y public_feed) con método, ruta, ticker y causa redactada.

Cobertura de este fichero:
1. ráfaga de 6 lecturas de la ficha de AMZN con Redis caído en producción:
   seis 503 y seis eventos con ticker=AMZN y cause=ConnectionError;
2. el 503 del nonce de auth también queda logueado;
3. sin avería: 200 y ningún warning;
4. un DSN con credenciales en la causa llega al log con REDACTED;
5. tests directos de exc_summary y ticker_from_path;
6. el fail-closed no cambia: mismo status y mismo detail que antes del log.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.core.rate_limit as rate_limit_module
from app.core import auth
from app.core.auth import ResearchPrincipal, get_research_principal
from app.core.config import Settings
from app.core.errors import exc_summary, ticker_from_path
from app.core.rate_limit import (
    RateLimitBackendUnavailable,
    enforce_llm_test_rate_limit,
    enforce_public_ip_rate_limit,
    enforce_rate_limit,
)
from tests.auth_helpers import bound_headers

SECRET = "0123456789abcdef0123456789abcdef"
DEAD_REDIS = "redis://127.0.0.1:6399/15"

# Postgres "fuerte" ficticio para Settings en producción, armado por trozos
# para no parecer una URI con credenciales reales en el diff (mismo criterio
# que tests/test_rate_limit.py).
PROD_TEST_DATABASE_URL = "postgresql:" + "//app_user" + ":" + "not-a-real-secret-fixture" + "@db:5432/app"

# Seis lecturas de la ficha: la página dispara una llamada por sección.
AMZN_SECTIONS = ("overview", "financials", "kpis", "news", "filings", "tesis")

PRODUCTION_OVERRIDES = dict(
    app_env="production",
    # El suite apaga la auth por defecto; un test que afirma "esto es
    # producción" tiene que decirlo explícitamente.
    research_auth_required=True,
    research_auth_secret=SECRET,
    minio_secret_key="production-minio-secret-not-a-default",
    minio_access_key="production-minio-access-not-a-default",
    database_url=PROD_TEST_DATABASE_URL,
)


def _settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        app_env="test",
        rate_limit_enabled=True,
        rate_limit_requests_per_minute=10,
        rate_limit_expensive_requests_per_minute=2,
        # Sin el suelo, estos tests ejercitarían el límite configurado.
        rate_limit_local_request_floor=0,
        redis_url=DEAD_REDIS,
    )
    base.update(overrides)
    return Settings(**base)


def _principal() -> ResearchPrincipal:
    return ResearchPrincipal(user_id="user-a", tenant_external_id="tenant-a")


def _companies_app() -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_research_principal] = _principal

    @app.get("/api/companies/{ticker}/{section}", dependencies=[Depends(enforce_rate_limit)])
    def company_section():
        return {"ok": True}

    @app.get("/api/settings/llm/test", dependencies=[Depends(enforce_llm_test_rate_limit)])
    def llm_test():
        return {"ok": True}

    @app.get("/api/public/feed.ics", dependencies=[Depends(enforce_public_ip_rate_limit)])
    def public_feed():
        return {"ok": True}

    return app


def _auth_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/companies/{ticker}/{section}")
    def company_section(principal=Depends(auth.get_research_principal)):
        return {"tenant": principal.tenant_external_id}

    return app


def _production_auth_settings() -> SimpleNamespace:
    """Settings de auth en producción con el Redis de nonces inalcanzable."""
    return SimpleNamespace(
        research_auth_required=True,
        research_auth_secret=SECRET,
        research_auth_max_age_seconds=300,
        research_auth_strict_binding=True,
        is_production=True,
        is_local_environment=False,
        redis_url=DEAD_REDIS,
    )


@pytest.fixture(autouse=True)
def _clear_local_hits():
    rate_limit_module._local_hits.clear()
    yield
    rate_limit_module._local_hits.clear()


def _client(monkeypatch, **overrides) -> TestClient:
    monkeypatch.setattr(rate_limit_module, "get_settings", lambda: _settings(**overrides))
    return TestClient(_companies_app())


def _rate_limit_records(caplog) -> list:
    return [r for r in caplog.records if r.name == "app.core.rate_limit"]


def test_rafaga_amzn_con_redis_caido_seis_503_y_seis_eventos(monkeypatch, caplog):
    """Seis lecturas de la ficha de AMZN: seis 503 y seis warnings con ticker."""
    client = _client(monkeypatch, **PRODUCTION_OVERRIDES)
    paths = [f"/api/companies/AMZN/{section}" for section in AMZN_SECTIONS]
    with caplog.at_level(logging.WARNING, logger="app.core.rate_limit"):
        responses = [client.get(path) for path in paths]

    assert [r.status_code for r in responses] == [503] * len(paths)
    for response in responses:
        assert response.json() == {"detail": "Rate limit backend unavailable"}

    records = _rate_limit_records(caplog)
    assert len(records) == len(paths)
    for record in records:
        message = record.getMessage()
        assert message.startswith("rate_limit_backend_unavailable ")
        assert "method=GET" in message
        assert "ticker=AMZN" in message
        assert "tier=standard" in message
        assert "cause=ConnectionError:" in message
    logged_paths = {r.getMessage().split(" path=")[1].split(" ")[0] for r in records}
    assert logged_paths == set(paths)


def test_503_del_nonce_queda_logueado_con_ruta_ticker_y_causa(monkeypatch, caplog):
    """El almacén de nonces caído en producción: 503 + auth_nonce_backend_unavailable."""
    monkeypatch.setattr(auth, "get_settings", _production_auth_settings)
    client = TestClient(_auth_app())
    headers = bound_headers(SECRET, "tenant-a", "user-a", method="GET", path="/api/companies/AMZN/overview")
    with caplog.at_level(logging.WARNING, logger="app.core.auth"):
        response = client.get("/api/companies/AMZN/overview", headers=headers)

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication backend unavailable"}
    records = [r for r in caplog.records if r.name == "app.core.auth"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith("auth_nonce_backend_unavailable ")
    assert "method=GET" in message
    assert "path=/api/companies/AMZN/overview" in message
    assert "ticker=AMZN" in message
    assert "cause=ConnectionError:" in message


def test_sin_averia_200_y_sin_ruido_en_logs(monkeypatch, caplog):
    """Sin avería (contador en proceso en local/test): 200 y ningún warning.

    Fuera de producción el rate limiter ni siquiera abre conexión a Redis
    (``use_redis = is_production``), así que la salud de Redis es irrelevante
    aquí y el log debe quedar en silencio.
    """
    client = _client(monkeypatch)
    with caplog.at_level(logging.WARNING):
        responses = [client.get(f"/api/companies/AMZN/{section}") for section in AMZN_SECTIONS]

    assert [r.status_code for r in responses] == [200] * len(AMZN_SECTIONS)
    for response in responses:
        assert response.headers["X-RateLimit-Limit"] == "10"
    assert "backend_unavailable" not in caplog.text
    assert not [r for r in caplog.records if r.name in {"app.core.rate_limit", "app.core.auth"}]


def test_dsn_con_credenciales_en_la_causa_llega_redactado_al_log(monkeypatch, caplog):
    """La excepción de redis/httpx puede llevar el DSN con password: REDACTED."""

    async def _down(*_args, **_kwargs):
        raise RateLimitBackendUnavailable("rate-limit store unreachable") from ConnectionError(
            "Error 111 connecting to redis://default:Sup3rSecretPw@redis.prod.internal:6379/0"
        )

    monkeypatch.setattr(rate_limit_module, "_record_hit", _down)
    client = _client(monkeypatch, **PRODUCTION_OVERRIDES)
    with caplog.at_level(logging.WARNING, logger="app.core.rate_limit"):
        response = client.get("/api/companies/AMZN/overview")

    assert response.status_code == 503
    assert "Sup3rSecretPw" not in response.text
    records = _rate_limit_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    # La forma exacta depende de la capa que enmascara: redact_secrets conserva
    # el usuario (redis://default:REDACTED@) y el filtro de logs enmascara todo
    # el userinfo (redis://[REDACTED]@). Lo fijo es que la password no aparece
    # y el host sigue visible para acotar la avería.
    assert "Sup3rSecretPw" not in message
    assert "REDACTED" in message
    assert "redis.prod.internal:6379" in message
    assert "Sup3rSecretPw" not in caplog.text


def test_llm_test_y_public_feed_tambien_loguean_su_503(monkeypatch, caplog):
    """Cobertura de las otras dos ramas nuevas: llm_test y public_feed."""
    client = _client(monkeypatch, **PRODUCTION_OVERRIDES)
    with caplog.at_level(logging.WARNING, logger="app.core.rate_limit"):
        llm = client.get("/api/settings/llm/test")
        feed = client.get("/api/public/feed.ics")

    assert llm.status_code == 503
    assert llm.json() == {"detail": "Rate limit backend unavailable"}
    assert feed.status_code == 503
    assert feed.json() == {"detail": "Rate limit backend unavailable"}

    messages = [r.getMessage() for r in _rate_limit_records(caplog)]
    llm_messages = [m for m in messages if m.startswith("llm_test_rate_limit_backend_unavailable ")]
    feed_messages = [m for m in messages if m.startswith("public_feed_rate_limit_backend_unavailable ")]
    assert len(llm_messages) == 1
    assert "method=GET" in llm_messages[0]
    assert "path=/api/settings/llm/test" in llm_messages[0]
    assert "cause=ConnectionError:" in llm_messages[0]
    assert len(feed_messages) == 1
    assert "method=GET" in feed_messages[0]
    assert "path=/api/public/feed.ics" in feed_messages[0]
    assert "client=" in feed_messages[0]
    assert "cause=ConnectionError:" in feed_messages[0]


def test_el_fail_closed_no_cambia_mismo_status_y_detail(monkeypatch):
    """El parche solo añade el log: status y detail del 503 son los de antes."""
    client = _client(monkeypatch, **PRODUCTION_OVERRIDES)
    response = client.get("/api/companies/AMZN/overview")
    assert response.status_code == 503
    assert response.json() == {"detail": "Rate limit backend unavailable"}
    assert "X-RateLimit-Limit" not in response.headers

    monkeypatch.setattr(auth, "get_settings", _production_auth_settings)
    headers = bound_headers(SECRET, "tenant-a", "user-a", method="GET", path="/api/companies/AMZN/overview")
    auth_response = TestClient(_auth_app()).get("/api/companies/AMZN/overview", headers=headers)
    assert auth_response.status_code == 503
    assert auth_response.json() == {"detail": "Authentication backend unavailable"}


def test_exc_summary_sin_causa_usa_la_propia_excepcion():
    assert exc_summary(ValueError("entrada inválida")) == "ValueError: entrada inválida"


def test_exc_summary_con_causa_resume_la_causa_y_la_redacta():
    try:
        try:
            raise ConnectionError("Error 111 connecting to redis://default:pw-secreta@redis:6379/0")
        except ConnectionError as cause:
            raise RateLimitBackendUnavailable("rate-limit store unreachable") from cause
    except RateLimitBackendUnavailable as exc:
        summary = exc_summary(exc)
    assert summary.startswith("ConnectionError: ")
    assert "pw-secreta" not in summary
    assert "redis://default:REDACTED@redis:6379/0" in summary


def test_exc_summary_redacta_query_params_y_passwords():
    summary = exc_summary(
        RuntimeError("GET https://api.vendor.com/q?apikey=K3YSECRET&format=json falló: password=hunter2")
    )
    assert "K3YSECRET" not in summary
    assert "hunter2" not in summary
    assert "apikey=REDACTED" in summary
    assert "password=REDACTED" in summary


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/companies/AMZN", "AMZN"),
        ("/api/companies/AMZN/financials", "AMZN"),
        ("/api/companies/AMZN/kpis/ttm", "AMZN"),
        ("/api/companies/amzn/overview", "amzn"),  # no normaliza: se loguea tal cual
        ("/api/companies/", None),
        ("/api/companies", None),
        ("/api/companies//overview", None),  # ticker vacío no vale
        ("/api/market/quote/AMZN", None),
        ("/health", None),
        ("", None),
    ],
)
def test_ticker_from_path(path, expected):
    assert ticker_from_path(path) == expected
