"""Pruebas del laboratorio de carga de ingesta (scripts/ingest_load_lab).

Fulfills: VAL-PERF-queues (Nico 1-nov-2026: carga de ingesta de
noticias/precios con fixtures, sin servicios externos ni LLM, midiendo
throughput y colas en el laboratorio).
Expected Behavior:
- Enqueue/drain sobre el formato wire dramatiq 1.x (fakeredis) con contadores
  exactos; drenar de más no inventa mensajes
- El escenario mide profundidad, throughput y edad real del más antiguo por
  tick, y registra lo que el watchdog declararía atascado
- Entrada sostenida > drenaje acaba en alerta del watchdog; drenaje suficiente
  no alerta nunca
"""

from __future__ import annotations

import pytest

from scripts.ingest_load_lab.harness import LoadLab, Phase, render, run_scenario


@pytest.fixture
def redis_client():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeRedis(decode_responses=False)


def test_enqueue_drain_wire_format_y_contadores(redis_client):
    lab = LoadLab(redis_client)
    lab.enqueue("prices", 10, now_ms=0)
    assert redis_client.llen("dramatiq:prices") == 10
    assert redis_client.hlen("dramatiq:prices.msgs") == 10
    # Mensaje decodificable por dramatiq (formato wire real).
    import dramatiq

    mid = redis_client.lrange("dramatiq:prices", 0, 0)[0]
    raw = redis_client.hget("dramatiq:prices.msgs", mid)
    assert dramatiq.Message.decode(raw).queue_name == "prices"
    assert lab.drain("prices", 4) == 4
    assert lab.drain("prices", 99) == 6  # drenar de más no inventa
    assert (lab.enqueued, lab.drained) == (10, 10)
    assert redis_client.hlen("dramatiq:prices.msgs") == 0


def test_edad_real_del_mas_antiguo(redis_client):
    lab = LoadLab(redis_client)
    lab.enqueue("prices", 2, now_ms=1000)
    assert lab.oldest_true_age("prices", now_ms=61_000) == 60.0
    lab.drain("prices", 1)
    assert lab.oldest_true_age("prices", now_ms=61_000) == 60.0  # el segundo tiene la misma edad
    lab.drain("prices", 1)
    assert lab.oldest_true_age("prices", now_ms=61_000) is None


def test_escenario_crecimiento_sostenido_alerta(redis_client, monkeypatch):
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "120")
    lab = LoadLab(redis_client)
    timeline = run_scenario(
        lab, [Phase(ticks=10, ingress=100, drain=50)], tick_ms=60_000
    )
    assert timeline[-1].depth == 500
    assert timeline[-1].oldest_true_age_seconds >= 120
    primeras_alertas = [r.tick for r in timeline if r.stuck]
    assert primeras_alertas, "entrada sostenida > drenaje debe acabar alertando"
    # La edad del watchdog nunca sobrestima la real.
    for r in timeline:
        if r.ready_age_seconds is not None:
            assert r.ready_age_seconds <= r.oldest_true_age_seconds + 1


def test_escenario_drenaje_suficiente_no_alerta(redis_client, monkeypatch):
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "120")
    lab = LoadLab(redis_client)
    timeline = run_scenario(
        lab, [Phase(ticks=10, ingress=50, drain=100)], tick_ms=60_000
    )
    assert timeline[-1].depth == 0
    assert all(not r.stuck for r in timeline)


# --- Auditoría del piloto a #4021 ---------------------------------------------

def test_throughput_con_start_ms_no_cero(redis_client, monkeypatch):
    """El throughput divide por el tiempo transcurrido del escenario, no por
    el timestamp absoluto: con start_ms != 0 la tasa sigue siendo la real."""
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "120")
    lab = LoadLab(redis_client)
    timeline = run_scenario(
        lab, [Phase(ticks=5, ingress=10, drain=10)], tick_ms=1000, start_ms=5_000_000
    )
    out = render(timeline, tick_ms=1000)
    # 50 mensajes en 5 s = 10 msg/s, no 50/5005 s.
    assert "throughput_entrada=10.00 msg/s" in out
    assert "throughput_salida=10.00 msg/s" in out


def test_render_timeline_vacio(redis_client):
    assert "sin ticks" in render([], tick_ms=1000)


def test_un_solo_muestreo_por_tick(redis_client, monkeypatch):
    """Un tick = un muestreo de Redis por cola, como prod (no dos)."""
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "120")

    class CountingRedis:
        def __init__(self, inner):
            self._inner = inner
            self.hlen_calls = 0

        def hlen(self, *a, **k):
            self.hlen_calls += 1
            return self._inner.hlen(*a, **k)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    client = CountingRedis(redis_client)
    lab = LoadLab(client)
    run_scenario(lab, [Phase(ticks=3, ingress=5, drain=5)], tick_ms=1000)
    # sample_queues hace 2 HLEN por cola (msgs + DQ.msgs): 2 x 1 cola x 3 ticks.
    assert client.hlen_calls == 6
