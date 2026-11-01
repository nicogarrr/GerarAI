"""Laboratorio de carga de ingesta (noticias/precios) sin servicios externos.

Motivo (Nico, 1-nov-2026): que el lunes, con la entrada de noticias y precios,
no haya cuellos de botella silenciosos. Este harness encola mensajes
sinteticos en el formato wire de dramatiq 1.x (``<ns>:<cola>`` lista de ids +
``<ns>:<cola>.msgs`` hash id -> mensaje) sobre fakeredis, los drena a una
tasa configurable y mide por tick:

- throughput real (mensajes encolados y drenados por segundo),
- profundidad por cola (msgs + DQ.msgs, como kpi_queue_depth), y
- lo que haria el watchdog de colas (queue_watchdog.sample_tick) en ese tick.

El reloj es inyectable (ticks logicos, sin sleeps): la corrida es
determinista y rapida. No toca servicios externos, LLM ni la base de datos.

CLI: ``python -m scripts.ingest_load_lab.harness`` ejecuta el escenario
"lunes": rafaga de precios con drenaje insuficiente (cuota IP) y recuperacion.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services import queue_watchdog


@dataclass(frozen=True)
class Phase:
    """Fase de carga: durante `ticks`, `ingress` mensajes/tick entran y el
    consumidor drena `drain` mensajes/tick de la cola `queue`."""

    ticks: int
    ingress: int
    drain: int
    queue: str = "prices"


class LoadLab:
    """Productor/consumidor sintetico sobre el formato wire de dramatiq 1.x."""

    def __init__(self, client: Any, *, namespace: str = "dramatiq") -> None:
        self.client = client
        self.namespace = namespace
        self.enqueued = 0
        self.drained = 0
        self._seq = 0

    def enqueue(self, queue: str, n: int, *, now_ms: float) -> None:
        base = f"{self.namespace}:{queue}"
        pipe = self.client.pipeline()
        for _ in range(n):
            self._seq += 1
            mid = f"loadlab-{queue}-{self._seq}"
            message = {
                "queue_name": queue,
                "actor_name": "load_lab_actor",
                "args": (),
                "kwargs": {},
                "options": {},
                "message_id": mid,
                "message_timestamp": int(now_ms),
            }
            pipe.hset(f"{base}.msgs", mid, json.dumps(message))
            pipe.rpush(base, mid)
        pipe.execute()
        self.enqueued += n

    def oldest_true_age(self, queue: str, *, now_ms: float) -> float | None:
        """Edad real del mensaje listo mas antiguo (FIFO: el head).

        Usa message_timestamp (en el lab = instante de encolado; no hay
        RetryAfter). Es la referencia contra la que se compara la edad que
        ve el watchdog (persistencia del ready id): divergen cuando la cola
        drena despacio pero la cabeza avanza (backlog creciente).
        """
        base = f"{self.namespace}:{queue}"
        ids = self.client.lrange(base, 0, 0)
        if not ids:
            return None
        raw = self.client.hget(f"{base}.msgs", ids[0])
        if raw is None:
            return None
        ts = json.loads(raw).get("message_timestamp")
        return None if ts is None else max(0.0, (now_ms - float(ts)) / 1000.0)

    def drain(self, queue: str, n: int) -> int:
        """Consume n mensajes del head (LPOP + HDEL), como el broker real."""
        base = f"{self.namespace}:{queue}"
        consumed = 0
        pipe = self.client.pipeline()
        for _ in range(n):
            pipe.lpop(base)
        for mid in pipe.execute():
            if mid is None:
                break
            consumed += 1
            pipe.hdel(f"{base}.msgs", mid)
        pipe.execute()
        self.drained += consumed
        return consumed


@dataclass
class TickRecord:
    tick: int
    ts_ms: float
    enqueued_total: int
    drained_total: int
    depth: int
    ready_age_seconds: float | None
    oldest_true_age_seconds: float | None  # edad real del mensaje listo mas viejo (message_timestamp; en el lab no hay RetryAfter)
    stuck: list[str] = field(default_factory=list)


def run_scenario(
    lab: LoadLab,
    phases: list[Phase],
    *,
    tick_ms: int = 60_000,
    start_ms: float = 0.0,
    queues: tuple[str, ...] = ("prices",),
) -> list[TickRecord]:
    """Ejecuta las fases con reloj logico y muestrea colas + watchdog por tick."""
    timeline: list[TickRecord] = []
    now_ms = start_ms
    tick = 0
    for phase in phases:
        for _ in range(phase.ticks):
            tick += 1
            if phase.ingress:
                lab.enqueue(phase.queue, phase.ingress, now_ms=now_ms)
            if phase.drain:
                lab.drain(phase.queue, phase.drain)
            now_ms += tick_ms
            samples = {
                s.queue: s
                for s in queue_watchdog.sample_queues(
                    lab.client, namespace=lab.namespace, queues=queues, now_ms=now_ms
                )
            }
            watchdog = queue_watchdog.sample_tick(
                lab.client,
                namespace=lab.namespace,
                queues=queues,
                now=datetime.fromtimestamp(now_ms / 1000, UTC),
            )
            sample = samples[phase.queue]
            timeline.append(
                TickRecord(
                    tick=tick,
                    ts_ms=now_ms,
                    enqueued_total=lab.enqueued,
                    drained_total=lab.drained,
                    depth=sample.depth,
                    ready_age_seconds=sample.ready_age_seconds,
                    oldest_true_age_seconds=lab.oldest_true_age(phase.queue, now_ms=now_ms),
                    stuck=[item["queue"] for item in watchdog["stuck"]],
                )
            )
    return timeline


def render(timeline: list[TickRecord], *, tick_ms: int) -> str:
    lines = [
        f"{'tick':>4} {'t_s':>6} {'encolados':>9} {'drenados':>8} {'depth':>6} "
        f"{'edad_cabeza_s':>13} {'edad_real_s':>11} {'atascada':>8}"
    ]
    for r in timeline:
        age = "" if r.ready_age_seconds is None else f"{r.ready_age_seconds:.0f}"
        true_age = "" if r.oldest_true_age_seconds is None else f"{r.oldest_true_age_seconds:.0f}"
        lines.append(
            f"{r.tick:>4} {r.ts_ms / 1000:>6.0f} {r.enqueued_total:>9} {r.drained_total:>8} "
            f"{r.depth:>6} {age:>13} {true_age:>11} {('SI' if r.stuck else ''):>8}"
        )
    peak = max(timeline, key=lambda r: r.depth)
    first_stuck = next((r for r in timeline if r.stuck), None)
    lines.append(
        f"pico_depth={peak.depth} (tick {peak.tick}) "
        f"throughput_entrada={timeline[-1].enqueued_total / (timeline[-1].ts_ms / 1000):.2f} msg/s "
        f"throughput_salida={timeline[-1].drained_total / (timeline[-1].ts_ms / 1000):.2f} msg/s"
    )
    lines.append(
        "primera_alerta_watchdog="
        + (f"tick {first_stuck.tick} (t={first_stuck.ts_ms / 1000:.0f} s)" if first_stuck else "NUNCA")
    )
    return "\n".join(lines)


def monday_scenario() -> tuple[list[Phase], dict[str, int]]:
    """Lunes: 20 min de precios entrando a 2 msg/s con drenaje de 1,5 msg/s
    (cuota IP compartida), parada total de 5 min (worker caido) y recuperacion."""
    phases = [
        Phase(ticks=40, ingress=120, drain=90),   # backlog crece 30/tick (min); drenaje parcial
        Phase(ticks=5, ingress=120, drain=0),     # worker caido: nada drena
        Phase(ticks=35, ingress=60, drain=150),   # recuperacion: drena el backlog
    ]
    return phases, {"tick_ms": 60_000}


def main() -> None:
    import fakeredis

    os.environ.setdefault("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "600")
    lab = LoadLab(fakeredis.FakeRedis(decode_responses=False))
    phases, kwargs = monday_scenario()
    timeline = run_scenario(lab, phases, **kwargs)
    print(render(timeline, **kwargs))


if __name__ == "__main__":
    main()
