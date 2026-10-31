"""Politica de reintentos de la cadena IBKR (orden del piloto sobre #3723).

- Per-tenant (sync_one_tenant_ibkr y su variante dedicada): time_limit de
  30 min (una importacion aceptada no muere a los 5) y backoff de 1 h, el
  mismo ritmo que su Retry interno de PyG diferido (not_ready).
- Dispatcher (sync_tenant_ibkr_connections y dedicada): max_retries=2 solo
  es real si el error transitorio RELANZA; el permanente devuelve fallo
  estructurado sin quemar reintentos.
"""

from __future__ import annotations

import dramatiq
import pytest
from sqlalchemy import exc as sa_exc

from app.core import database as database_module
from app.workers import dramatiq_app as worker


@pytest.fixture(scope="module")
def registry():
    broker = dramatiq.get_broker()
    return {name: broker.get_actor(name) for name in broker.get_declared_actors()}


@pytest.mark.parametrize("name", ["sync_one_tenant_ibkr", "sync_one_tenant_ibkr_dedicated"])
def test_per_tenant_import_time_limit_30min_and_backoff_1h(registry, name: str) -> None:
    options = registry[name].options
    assert options["time_limit"] == 1_800_000
    assert options["min_backoff"] == 3_600_000
    assert options["max_retries"] == 2


@pytest.mark.parametrize(
    "name", ["sync_tenant_ibkr_connections", "sync_tenant_ibkr_connections_dedicated"]
)
def test_dispatcher_retries_twice_with_backoff(registry, name: str) -> None:
    options = registry[name].options
    assert options["max_retries"] == 2
    assert options["min_backoff"]


def test_dispatcher_reraises_transient_so_retry_is_real(monkeypatch) -> None:
    def _broken():
        raise sa_exc.OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(database_module, "SessionLocal", _broken)
    # El actor importa SessionLocal dentro del cuerpo: el monkeypatch del
    # modulo de database es el punto de entrada real.
    with pytest.raises(sa_exc.OperationalError):
        worker.sync_tenant_ibkr_connections.fn()


def test_dispatcher_permanent_error_is_structured_not_retried(monkeypatch) -> None:
    def _broken():
        raise ValueError("payload imposible")

    monkeypatch.setattr(database_module, "SessionLocal", _broken)
    result = worker.sync_tenant_ibkr_connections.fn()
    assert result["status"] == "error"
    assert result["actor"] == "sync_tenant_ibkr_connections"
    assert result["error"]["type"] == "ValueError"
