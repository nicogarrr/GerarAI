"""Real Lua admission semantics via disposable Redis, no external services/LLM."""
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import dramatiq
import pytest
import redis

from app.workers import dramatiq_app as workers
from app.workers.bounded_broker import BoundedRedisBroker, QueueCapacityError


def message(queue="kpis", options=None):
    return dramatiq.Message(queue, "extract_document_kpis", (1,), {}, options or {})


@pytest.fixture
def redis_client(tmp_path):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server needed for Lua integration tests")
    socket = str(tmp_path / "redis.sock")
    process = subprocess.Popen(
        [binary, "--port", "0", "--unixsocket", socket, "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    client = redis.Redis(unix_socket_path=socket)
    try:
        for _ in range(100):
            try:
                if client.ping():
                    break
            except redis.RedisError:
                time.sleep(0.02)
        else:
            raise RuntimeError("test Redis did not start")
        yield client
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)


def test_concurrent_admission_never_overflows(monkeypatch, redis_client):
    monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "10")
    broker = BoundedRedisBroker(client=redis_client)

    def send(_):
        try:
            broker.enqueue(message())
            return 1
        except QueueCapacityError:
            return 0

    with ThreadPoolExecutor(16) as pool:
        assert sum(pool.map(send, range(200))) == 10
    assert broker.client.hlen("dramatiq:kpis.msgs") == 10
    assert broker.client.llen("dramatiq:kpis") == 10
    # Payloads carry the redis_message_id required by native consumers.
    raw = broker.client.hvals("dramatiq:kpis.msgs")[0]
    assert dramatiq.Message.decode(raw).options["redis_message_id"]


def test_delayed_and_inflight_work_reduce_capacity(monkeypatch, redis_client):
    monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "2")
    broker = BoundedRedisBroker(client=redis_client, namespace="custom")
    broker.client.hset("custom:kpis.DQ.msgs", "retry", "delayed")
    broker.enqueue(message())
    broker.client.lpop("custom:kpis")  # consumer fetched it, not acknowledged
    with pytest.raises(QueueCapacityError):
        broker.enqueue(message())
    broker.client.hdel("custom:kpis.msgs", *broker.client.hkeys("custom:kpis.msgs"))
    broker.enqueue(message())


@pytest.mark.parametrize("msg,delay", [
    (message("alerts"), None), (message(options={"retries": 1}), 15000),
    (message(options={"eta": 100}), None),
])
def test_existing_work_and_other_lanes_use_native_broker(msg, delay):
    with patch("dramatiq.brokers.redis.RedisBroker.enqueue", return_value=msg) as send:
        assert BoundedRedisBroker(client=MagicMock()).enqueue(msg, delay=delay) == msg
    send.assert_called_once_with(msg, delay=delay)


def test_outage_is_not_empty_queue():
    client = MagicMock()
    client.hlen.side_effect = ConnectionError("offline")
    assert workers.kpi_queue_depth(client) is None
    assert not workers.kpi_queue_has_capacity(client)
    with patch.object(workers, "_redis_client", return_value=client):
        assert workers.backfill_document_kpis()["reason"] == "queue_unavailable"


@pytest.mark.parametrize("error,status,has_reservation", [
    (QueueCapacityError("full"), "deferred_backpressure", False),
    (ConnectionError("ambiguous timeout"), "queue_unavailable", True),
    (None, "queued", True),
])
def test_ingestion_persists_recovery_before_send(error, status, has_reservation):
    db, doc = MagicMock(), MagicMock()
    doc.metadata_, doc.id = {}, 7
    db.info = {"tenant_id": 1, "user_id": "u"}

    def send(*args, **kwargs):
        assert db.commit.call_count == 1
        assert doc.metadata_["kpi_deferred"]["queued_at"]
        if error:
            raise error
        return MagicMock(message_id="id")

    with patch.object(workers.extract_document_kpis, "send", side_effect=send):
        result = workers.enqueue_document_kpis(db, doc)
    assert result["status"] == status
    assert ("queued_at" in doc.metadata_["kpi_deferred"]) == has_reservation


def test_backfill_full_race_restores_attempt_and_stops():
    from datetime import datetime

    from tests.test_kpi_backpressure import TestBackfillFunctional

    fixture = TestBackfillFunctional()
    db = fixture._db()
    doc = fixture._doc(db, "deferred", {"attempts": 0}, datetime(2026, 1, 1))
    doc_id = doc.id
    with (
        patch.object(workers, "tenant_contexts", return_value=[(1, "u")]),
        patch.object(workers, "_session", return_value=db),
        patch.object(workers, "_redis_client", return_value=None),
        patch.object(workers, "kpi_queue_depth", return_value=0),
        patch.object(workers.extract_document_kpis, "send", side_effect=QueueCapacityError("full")),
    ):
        result = workers.backfill_document_kpis()
    assert result["queued"] == 0
    from app.models import Document

    assert db.get(Document, doc_id).metadata_["kpi_deferred"] == {"attempts": 0}


def test_compose_dedicated_queues_and_fixed_connection_pool():
    from pathlib import Path

    import yaml

    class _ComposeLoader(yaml.SafeLoader):
        """SafeLoader que tolera los tags de merge de Compose (!override/!reset).
    
        Los tags son sintaxis de docker compose, no errores de YAML; los tests
        solo afirman sobre la estructura de servicios resultante.
        """
    
    
    def _compose_unknown_tag(loader, tag_suffix, node):
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return loader.construct_scalar(node)
    
    
    _ComposeLoader.add_multi_constructor("!", _compose_unknown_tag)

    root = Path(__file__).resolve().parents[2]
    services = yaml.load((root / "docker-compose.prod.yml").read_text(), Loader=_ComposeLoader)["services"]
    expected = {"worker": ["default", "prices"], "worker-kpis": ["kpis"],
                # #3028: el carril "computed" (ProPicks, calculos cortos) lo
                # consume worker-alerts en vez de anadir un contenedor nuevo.
                "worker-thesis": ["thesis"], "worker-alerts": ["alerts", "computed"],
                "worker-gdelt": ["gdelt"]}
    for name, queues in expected.items():
        command = services[name]["command"]
        assert command[command.index("-Q") + 1:] == queues
        assert command[command.index("--processes") + 1] == "1"
    assert services["worker-kpis"]["command"][5] == "4"
    # Runtime SQLAlchemy defaults remain 5 + 10, no larger database pool.
    from app.core.database import engine

    assert engine.pool.size() == 5
    assert engine.pool._max_overflow == 10


def test_native_consumer_decodes_and_acknowledges_admitted_message(redis_client):
    broker = BoundedRedisBroker(client=redis_client, middleware=[])
    msg = broker.enqueue(message())
    consumer = broker.consume("kpis", prefetch=1, timeout=100)
    received = next(consumer)
    assert received.message_id == msg.message_id
    assert received.args == (1,)
    assert redis_client.hlen("dramatiq:kpis.msgs") == 1
    consumer.ack(received)
    assert redis_client.hlen("dramatiq:kpis.msgs") == 0
    consumer.close()


def test_retry_is_not_rejected_at_full_capacity(monkeypatch, redis_client):
    monkeypatch.setenv("KPI_QUEUE_MAX_PENDING", "1")
    broker = BoundedRedisBroker(client=redis_client, middleware=[])
    broker.enqueue(message())
    broker.enqueue(message(options={"retries": 1}), delay=1000)
    assert redis_client.hlen("dramatiq:kpis.DQ.msgs") == 1
    with patch.object(workers, "broker", broker):
        assert workers.kpi_queue_depth(redis_client) == 2
    with pytest.raises(QueueCapacityError):
        broker.enqueue(message())
