"""Redis caído al encolar un trabajo: 503 explícito, no un 500 genérico.

Con Redis caído, ``POST /api/paper-trading/refresh`` (y el resto de endpoints
que encolan con Dramatiq) devolvía 500 «Internal server error»: el
``redis.exceptions.ConnectionError`` del ``.send()`` no tenía manejador.
"""

import pytest
import redis.exceptions

from app.core.auth import ResearchPrincipal, get_research_principal
from app.core.database import init_db
from app.workers import dramatiq_app
from main import app
from tests.auth_helpers import csrf_client


@pytest.fixture
def client():
    init_db()
    app.dependency_overrides[get_research_principal] = lambda: ResearchPrincipal(
        user_id="u-queue", tenant_external_id="t-queue"
    )
    try:
        yield csrf_client(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_research_principal, None)


def _raise(exc):
    def _send(*_args, **_kwargs):
        raise exc

    return _send


@pytest.mark.parametrize(
    ("actor", "path"),
    [
        ("refresh_paper_trades", "/api/paper-trading/refresh"),
        ("propose_paper_trades", "/api/paper-trading/feed"),
        ("refresh_propicks_prices", "/api/propicks/prices/refresh"),
    ],
)
@pytest.mark.parametrize(
    "exc",
    [
        redis.exceptions.ConnectionError("Error 111 connecting to localhost:6379."),
        redis.exceptions.TimeoutError("Timeout reading from socket"),
    ],
)
def test_redis_caido_al_encolar_da_503_reintentable(client, monkeypatch, caplog, actor, path, exc):
    monkeypatch.setattr(getattr(dramatiq_app, actor), "send", _raise(exc))
    response = client.post(path, json={})
    assert response.status_code == 503
    assert response.json()["detail"].startswith("Background job queue unavailable")
    assert response.headers.get("retry-after") == "30"
    assert any("job_queue_unavailable" in r.getMessage() and path in r.getMessage() for r in caplog.records)
