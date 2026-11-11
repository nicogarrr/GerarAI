
import pytest


def test_absent_consumer_blocks_new_work_without_touching_messages(redis_client):
    from app.workers.bounded_broker import BoundedRedisBroker, QueueCapacityError
    from tests.test_bounded_broker import message

    redis_client.delete("dramatiq:kpis:consumers")
    broker = BoundedRedisBroker(client=redis_client)
    with pytest.raises(QueueCapacityError, match="consumidor"):
        broker.enqueue(message())
    assert redis_client.hlen("dramatiq:kpis.msgs") == 0


def test_live_kpi_only_heartbeat_allows_admission_then_expires(redis_client):
    from app.workers.bounded_broker import BoundedRedisBroker, QueueCapacityError
    from tests.test_bounded_broker import message

    redis_client.delete("dramatiq:kpis:consumers")
    broker = BoundedRedisBroker(client=redis_client)
    now = int(redis_client.time()[0])
    redis_client.zadd("dramatiq:kpis:consumers", {"worker": now})
    broker.enqueue(message())
    redis_client.zadd("dramatiq:kpis:consumers", {"worker": now - 61})
    with pytest.raises(QueueCapacityError, match="consumidor"):
        broker.enqueue(message())
    assert redis_client.hlen("dramatiq:kpis.msgs") == 1


# Reuse the disposable local Redis fixture. Never production.
from tests.test_bounded_broker import redis_client  # noqa: E402,F401


def test_poll_refreshes_own_queue_lease_and_close_revokes_it(redis_client, tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from app.workers import kpi_consumer_health as health

    monkeypatch.setattr(health, 'TOKEN_PATH', tmp_path / 'token')
    raw = MagicMock()
    raw.__next__.side_effect = [None, 'message', RuntimeError('broken poll')]
    consumer = health.KPIConsumer(raw, redis_client, 'isolated', 'own-worker')
    assert iter(consumer) is consumer
    assert next(consumer) is None  # idle consumer is healthy too
    assert health.healthy(redis_client, 'isolated', 'own-worker')
    assert not health.healthy(redis_client, 'isolated', 'other-worker')
    assert health.TOKEN_PATH.read_text() == 'own-worker'
    assert next(consumer) == 'message'
    redis_client.zadd('isolated:kpis:consumers', {'own-worker': 1})
    with pytest.raises(RuntimeError, match='broken poll'):
        next(consumer)
    assert not health.healthy(redis_client, 'isolated', 'own-worker')
    assert consumer.ack == raw.ack
    consumer.close()
    assert redis_client.zscore('isolated:kpis:consumers', 'own-worker') is None
    raw.close.assert_called_once()


def test_healthcheck_fails_closed_and_uses_local_worker_token(redis_client, tmp_path, monkeypatch):
    from app.workers import kpi_consumer_health as health

    path = tmp_path / 'token'
    monkeypatch.setattr(health, 'TOKEN_PATH', path)
    monkeypatch.setenv('REDIS_URL', 'redis://unused')
    monkeypatch.setattr('redis.Redis.from_url', lambda *a, **kw: redis_client)
    assert health.main() == 1  # missing local identity
    path.write_text('own')
    assert health.main() == 1  # other workers cannot pass health
    redis_client.zadd('dramatiq:kpis:consumers', {'own': int(redis_client.time()[0])})
    assert health.main() == 0
    redis_client.zadd('dramatiq:kpis:consumers', {'own': 1})
    assert health.main() == 1


def test_other_queue_heartbeat_cannot_admit_kpis(redis_client):
    from app.workers.bounded_broker import BoundedRedisBroker, QueueCapacityError
    from tests.test_bounded_broker import message

    redis_client.delete('dramatiq:kpis:consumers')
    redis_client.zadd('dramatiq:__heartbeats__', {'default-worker': int(redis_client.time()[0]) * 1000})
    with pytest.raises(QueueCapacityError, match='consumidor'):
        BoundedRedisBroker(client=redis_client).enqueue(message())


def test_kpi_consumer_can_boot_with_empty_queue_and_then_admit(redis_client, tmp_path, monkeypatch):
    from app.workers import kpi_consumer_health as health
    from app.workers.bounded_broker import BoundedRedisBroker
    from tests.test_bounded_broker import message

    monkeypatch.setattr(health, 'TOKEN_PATH', tmp_path / 'token')
    redis_client.delete('dramatiq:kpis:consumers')
    broker = BoundedRedisBroker(client=redis_client, middleware=[])
    consumer = broker.consume('kpis', prefetch=1, timeout=10)
    assert next(consumer) is None
    admitted = broker.enqueue(message())
    received = next(consumer)
    assert received.message_id == admitted.message_id
    consumer.ack(received)
    assert redis_client.hlen('dramatiq:kpis.msgs') == 0
    consumer.close()


def test_non_kpi_consumer_remains_native(redis_client):
    from app.workers.bounded_broker import BoundedRedisBroker
    from app.workers.kpi_consumer_health import KPIConsumer

    consumer = BoundedRedisBroker(client=redis_client, middleware=[]).consume('default', timeout=10)
    assert not isinstance(consumer, KPIConsumer)
    consumer.close()


def test_existing_backlog_over_cap_is_preserved_and_consumable(redis_client, tmp_path, monkeypatch):
    from app.workers import kpi_consumer_health as health
    from app.workers.bounded_broker import BoundedRedisBroker, QueueCapacityError
    from tests.test_bounded_broker import message

    monkeypatch.setattr(health, 'TOKEN_PATH', tmp_path / 'token')
    monkeypatch.setenv('KPI_QUEUE_MAX_PENDING', '100')
    broker = BoundedRedisBroker(client=redis_client, middleware=[])
    # Native path simulates already accepted legacy work, not new admission.
    from dramatiq.brokers.redis import RedisBroker

    for _ in range(105):
        RedisBroker.enqueue(broker, message())
    consumer = broker.consume('kpis', prefetch=1, timeout=10)
    received = next(consumer)
    assert received is not None
    with pytest.raises(QueueCapacityError):
        broker.enqueue(message())
    assert redis_client.hlen('dramatiq:kpis.msgs') == 105
    consumer.ack(received)
    assert redis_client.hlen('dramatiq:kpis.msgs') == 104
    consumer.close()


def test_retry_remains_accepted_even_without_consumer(redis_client):
    from app.workers.bounded_broker import BoundedRedisBroker
    from tests.test_bounded_broker import message

    redis_client.delete('dramatiq:kpis:consumers')
    broker = BoundedRedisBroker(client=redis_client, middleware=[])
    broker.enqueue(message(options={'retries': 1}), delay=1000)
    assert redis_client.hlen('dramatiq:kpis.DQ.msgs') == 1


def test_healthcheck_uses_authenticated_settings_url_without_retries(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from app.core.config import get_settings
    from app.workers import kpi_consumer_health as health

    expected = 'redis://:test-password@localhost:6399/0'
    monkeypatch.setattr(get_settings(), 'redis_url', expected)
    monkeypatch.setenv('REDIS_URL', 'redis://wrong-host:6379/0')
    path = tmp_path / 'identity'
    path.write_text('own')
    monkeypatch.setattr(health, 'TOKEN_PATH', path)
    client = MagicMock()
    client.zscore.return_value = 1000
    client.time.return_value = (1000, 0)
    captured = {}

    def build(url, **kwargs):
        captured.update(url=url, **kwargs)
        return client

    monkeypatch.setattr('redis.Redis.from_url', build)
    assert health.main() == 0
    assert captured['url'] == expected
    assert captured['retry']._retries == 0
    assert captured['socket_connect_timeout'] == captured['socket_timeout'] == 3
