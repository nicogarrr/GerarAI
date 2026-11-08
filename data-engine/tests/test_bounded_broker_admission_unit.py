"""Admision atomica de la cola KPI sin redis-server: el script Lua emulado.

Los tests de integracion de test_bounded_broker.py necesitan redis-server
(Lua real) y se saltan sin el. Estos cubren la misma logica de admision con
un cliente falso que emula la semantica del script _ADMIT (profundidad =
hashes ready + delayed; admite o rechaza atomico), el presupuesto
KPI_QUEUE_MAX_PENDING y el requisito del docstring: una cola llena nunca
descarta el documento, lo difiere con QueueCapacityError.
"""

from __future__ import annotations

import dramatiq
import pytest

from app.workers.bounded_broker import (
    BoundedRedisBroker,
    QueueCapacityError,
    max_pending,
)


def _message(queue="kpis", options=None):
    return dramatiq.Message(queue, "extract_document_kpis", (1,), {}, options or {})


class _FakeRedis:
    """Emula _ADMIT: hlen(msgs) + hlen(DQ.msgs) >= max -> 0; si no, hset+rpush."""

    def __init__(self, depth=0):
        self.msgs = {f"prev-{i}": b"x" for i in range(depth)}
        self.dq = {}
        self.queue = [f"prev-{i}" for i in range(depth)]
        self.eval_calls = 0

    def register_script(self, script):
        return lambda *args, **kwargs: None

    def eval(self, script, numkeys, k_msgs, k_dq, k_queue, maxp, msgid, payload):
        self.eval_calls += 1
        if len(self.msgs) + len(self.dq) >= int(maxp):
            return 0
        self.msgs[msgid] = payload
        self.queue.append(msgid)
        return 1


class TestMaxPending:
    def test_sin_variable_500(self, monkeypatch):
        monkeypatch.delenv("KPI_QUEUE_MAX_PENDING", raising=False)
        assert max_pending() == 500

    def test_variable_valida_manda(self, monkeypatch):
        monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "250")
        assert max_pending() == 250

    def test_variable_corrupta_cae_al_defecto(self, monkeypatch):
        monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "muchas")
        assert max_pending() == 500

    def test_nunca_baja_de_uno(self, monkeypatch):
        monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "0")
        assert max_pending() == 1


class TestAdmission:
    def test_admite_con_hueco_y_devuelve_el_mensaje(self, monkeypatch):
        monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "10")
        client = _FakeRedis(depth=3)
        broker = BoundedRedisBroker(client=client)
        admitted = broker.enqueue(_message())
        assert admitted.options["redis_message_id"] in client.msgs
        assert client.msgs[admitted.options["redis_message_id"]] == admitted.encode()
        assert client.queue[-1] == admitted.options["redis_message_id"]
        assert client.eval_calls == 1

    def test_llena_rechaza_con_capacidad_no_con_descarte(self, monkeypatch):
        monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "4")
        client = _FakeRedis(depth=4)
        broker = BoundedRedisBroker(client=client)
        with pytest.raises(QueueCapacityError, match="diferido"):
            broker.enqueue(_message())
        assert len(client.msgs) == 4  # nada nuevo admitido
        assert client.eval_calls == 1

    def test_el_trabajo_diferido_cuenta_para_el_tope(self, monkeypatch):
        monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "5")
        client = _FakeRedis(depth=3)
        client.dq["delayed-1"] = b"x"
        client.dq["delayed-2"] = b"x"
        broker = BoundedRedisBroker(client=client)
        with pytest.raises(QueueCapacityError):
            broker.enqueue(_message())

    def test_cada_admision_lleva_id_unico(self, monkeypatch):
        monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "10")
        client = _FakeRedis()
        broker = BoundedRedisBroker(client=client)
        first = broker.enqueue(_message())
        second = broker.enqueue(_message())
        assert first.options["redis_message_id"] != second.options["redis_message_id"]
        assert len(client.msgs) == 2
