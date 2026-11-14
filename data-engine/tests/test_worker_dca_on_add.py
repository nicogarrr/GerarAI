"""Actor evaluate_dca_on_add: senal DCA al anadir simbolos, sin esperar al diario.

Contratos fijados:
- con el ajuste desactivado no trabaja (skipped/disabled, sin lease);
- lease ocupado = DcaOnAddLeaseHeld para que dramatiq reintente con backoff;
  solo en el ULTIMO intento se limpian las marcas de «preparando» (la ficha
  deja de esperar: el diario la cubrira);
- el lease se libera y la sesion se cierra en ok y en error; el error se
  relanza (reintenta) tras rollback.

Run from data-engine/:
    pytest tests/test_worker_dca_on_add.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core import config as config_module
from app.services import dca_on_add
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(
        db=MagicMock(),
        lease="LEASE",
        released=[],
        rolled=[],
        retries=0,
        enabled=True,
        cleared=[],
    )

    def acquire(key, **kw):
        return e.lease

    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(dca_evaluation_enabled=e.enabled))
    monkeypatch.setattr(worker, "acquire_job_lease", acquire)
    monkeypatch.setattr(worker, "release_job_lease", lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "_session", lambda tenant, user: e.db)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_current_message_retries", lambda: e.retries)
    monkeypatch.setattr(dca_on_add, "clear_marks", lambda tenant, symbols: e.cleared.append((tenant, symbols)))
    return e


def test_desactivado_no_trabaja(env, monkeypatch):
    e_enabled = False
    env.enabled = e_enabled
    called = []
    monkeypatch.setattr(dca_on_add, "run_on_add", lambda db, syms: called.append(syms))

    out = worker.evaluate_dca_on_add.fn(1, "u", ["AAPL"])

    assert out == {"status": "skipped", "actor": "evaluate_dca_on_add", "reason": "disabled"}
    assert called == []


def test_lease_ocupado_reintenta_sin_limpiar_marcas(env, monkeypatch):
    env.lease = None
    env.retries = 1  # quedan intentos (max_retries=3)

    with pytest.raises(worker.DcaOnAddLeaseHeld):
        worker.evaluate_dca_on_add.fn(1, "u", ["AAPL"])

    assert env.cleared == []


def test_lease_ocupado_ultimo_intento_limpia_marcas(env, monkeypatch):
    env.lease = None
    env.retries = 3  # max_retries alcanzado: no habra otro intento

    with pytest.raises(worker.DcaOnAddLeaseHeld):
        worker.evaluate_dca_on_add.fn(1, "u", ["AAPL", "MSFT"])

    assert env.cleared == [(1, ["AAPL", "MSFT"])]


def test_ok_libera_lease_y_cierra(env, monkeypatch):
    monkeypatch.setattr(dca_on_add, "run_on_add", lambda db, syms: {"status": "ok", "signals": len(syms)})

    out = worker.evaluate_dca_on_add.fn(1, "u", ["AAPL", "MSFT"])

    assert out == {"actor": "evaluate_dca_on_add", "status": "ok", "signals": 2}
    assert env.released == [("evaluate_dca_signals:1", "LEASE")]
    env.db.close.assert_called_once_with()


def test_error_rollback_relanza_y_libera_todo(env, monkeypatch):
    boom = ConnectionError("yahoo caido")
    def fail(db, syms):
        raise boom

    monkeypatch.setattr(dca_on_add, "run_on_add", fail)

    with pytest.raises(ConnectionError):
        worker.evaluate_dca_on_add.fn(1, "u", ["AAPL"])

    assert env.rolled == [env.db]
    assert env.released == [("evaluate_dca_signals:1", "LEASE")]
    env.db.close.assert_called_once_with()
