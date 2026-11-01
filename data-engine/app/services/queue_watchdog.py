"""Watchdog de colas dramatiq/Redis: alerta in-app cuando una cola se atasca.

Motivo (Nico, 1-nov-2026): el lunes entra la carga de noticias y precios y no
puede haber colas atascadas silenciosas. Una cola se declara atascada por lo
MEDIDO, no por su profundidad:

- edad del mensaje listo mas antiguo (message_timestamp del formato dramatiq
  1.x: ``<ns>:<cola>`` lista de ids listos, ``<ns>:<cola>.msgs`` hash
  id -> mensaje) por encima del umbral, y
- tasa de drenaje <= 0 entre dos ticks: la profundidad (msgs + DQ.msgs, como
  en ``kpi_queue_depth``) no baja respecto a la muestra anterior guardada en
  Redis por este servicio.

El primer tick de una cola solo guarda la muestra (sin tasa medible aun, no se
alerta). Idempotente: una alerta por cola y dia (fingerprint unico), como
source_health_watchdog. Redis caido = fail-open (sin alerta, status skipped).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ResearchAlert

VERSION = "queue-stuck-v1"
ALERT_TYPE = "queue_stuck"

# Colas vigiladas por defecto (las de ingesta y derivados; ver queue_taxonomy).
DEFAULT_QUEUES = ("default", "prices", "yahoo", "finnhub", "externa", "kpis", "computed", "alerts")

_SAMPLE_PREFIX = "queue_watchdog:sample:"


def max_age_seconds() -> float:
    """Edad del mensaje listo mas antiguo a partir de la cual se evalua atasco."""
    try:
        return max(60.0, float(os.getenv("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "900")))
    except ValueError:
        return 900.0


def watched_queues() -> tuple[str, ...]:
    raw = os.getenv("QUEUE_WATCHDOG_QUEUES")
    if not raw:
        return DEFAULT_QUEUES
    queues = tuple(q.strip() for q in raw.split(",") if q.strip())
    return queues or DEFAULT_QUEUES


@dataclass(frozen=True)
class QueueSample:
    queue: str
    depth: int
    oldest_age_seconds: float | None  # None: cola vacia


def _oldest_ready_age(client: Any, base: str, now_ms: float) -> float | None:
    """Edad (s) del mensaje listo mas antiguo; None si la cola esta vacia."""
    ids = client.lrange(base, 0, 0)
    if not ids:
        return None
    raw = client.hget(f"{base}.msgs", ids[0])
    if raw is None:
        return None
    import dramatiq

    timestamp = getattr(dramatiq.Message.decode(raw), "message_timestamp", None)
    if not timestamp:
        return None
    return max(0.0, (now_ms - float(timestamp)) / 1000.0)


def sample_queues(client: Any, *, namespace: str = "dramatiq", queues: tuple[str, ...] = DEFAULT_QUEUES,
                  now_ms: float | None = None) -> list[QueueSample]:
    """Profundidad (msgs + DQ.msgs) y edad del mas antiguo por cola."""
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    samples = []
    for queue in queues:
        base = f"{namespace}:{queue}"
        depth = int(client.hlen(f"{base}.msgs")) + int(client.hlen(f"{base}.DQ.msgs"))
        samples.append(QueueSample(queue=queue, depth=depth,
                                   oldest_age_seconds=_oldest_ready_age(client, base, now_ms)))
    return samples


def load_previous(client: Any, queue: str) -> dict[str, float] | None:
    raw = client.get(f"{_SAMPLE_PREFIX}{queue}")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return {"ts": float(data["ts"]), "depth": float(data["depth"])}
    except (KeyError, TypeError, ValueError):
        return None


def save_sample(client: Any, queue: str, *, ts: float, depth: int) -> None:
    # Doble de la cadencia del scheduler (5 min): una muestra expirada cuenta
    # como primera (sin tasa, no alerta), nunca como drenaje falso.
    client.set(f"{_SAMPLE_PREFIX}{queue}", json.dumps({"ts": ts, "depth": depth}), ex=1800)


def detect_stuck(samples: list[QueueSample], previous: dict[str, dict[str, float] | None],
                 *, max_age: float, now: float) -> list[dict[str, Any]]:
    """Colas atascadas: mensaje viejo y sin drenaje entre muestras. Funcion pura."""
    stuck = []
    for sample in samples:
        age = sample.oldest_age_seconds
        prev = previous.get(sample.queue)
        if age is None or age < max_age or prev is None:
            continue
        elapsed = max(1.0, now - prev["ts"])
        drain_rate = (prev["depth"] - sample.depth) / elapsed  # msgs/s; <=0: no drena
        if drain_rate > 0:
            continue
        stuck.append({
            "queue": sample.queue,
            "depth": sample.depth,
            "oldest_age_seconds": round(age, 1),
            "drain_rate_per_s": round(drain_rate, 4),
        })
    return stuck


def _message(item: dict[str, Any]) -> tuple[str, str, str]:
    title = f"Cola {item['queue']} atascada"
    message = (
        f"La cola {item['queue']} no drena: {item['depth']} mensajes pendientes, "
        f"el mas antiguo lleva {item['oldest_age_seconds']:.0f} s en cola y la "
        f"tasa de drenaje medida entre ticks es {item['drain_rate_per_s']} msg/s. "
        "Revisar workers de esa cola (cuota IP, errores o proceso caido)."
    )
    return "high", title, message


def emit_queue_stuck_alerts(
    db: Session,
    *,
    client: Any = None,
    namespace: str = "dramatiq",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Muestrea las colas, detecta atascos y persiste ResearchAlert in-app."""
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    if client is None:
        from app.workers.dramatiq_app import _redis_client, broker

        client = _redis_client()
        namespace = broker.namespace
        if client is None:
            return {"status": "skipped", "reason": "redis_unavailable", "created": []}
    now = (now or datetime.now(UTC)).astimezone(UTC)
    now_ms = now.timestamp() * 1000
    queues = watched_queues()
    samples = sample_queues(client, namespace=namespace, queues=queues, now_ms=now_ms)
    previous = {sample.queue: load_previous(client, sample.queue) for sample in samples}
    stuck = detect_stuck(samples, previous, max_age=max_age_seconds(), now=now.timestamp())
    created: list[int] = []
    existing = 0
    for item in stuck:
        fingerprint = f"{VERSION}:{tenant_id}:{item['queue']}:{now.date().isoformat()}"
        if (
            db.scalar(
                select(ResearchAlert.id).where(
                    ResearchAlert.tenant_id == tenant_id,
                    ResearchAlert.fingerprint == fingerprint,
                )
            )
            is not None
        ):
            existing += 1
            continue
        severity, title, message = _message(item)
        alert = ResearchAlert(
            tenant_id=tenant_id,
            company_id=None,
            severity=severity,
            status="open",
            alert_type=ALERT_TYPE,
            title=title,
            message=message,
            fingerprint=fingerprint,
            channels=["in_app"],
            last_triggered_at=now,
            metadata_={"rule_version": VERSION, **item},
        )
        try:
            with db.begin_nested():
                db.add(alert)
                db.flush()
        except IntegrityError:
            existing += 1
            continue
        created.append(alert.id)
    db.commit()
    for sample in samples:
        save_sample(client, sample.queue, ts=now.timestamp(), depth=sample.depth)
    return {
        "status": "ok",
        "queues": len(samples),
        "stuck": len(stuck),
        "created": created,
        "existing": existing,
    }
