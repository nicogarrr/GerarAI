"""Watchdog de colas dramatiq/Redis: alerta in-app cuando una cola se atasca.

Motivo (Nico, 1-nov-2026): el lunes entra la carga de noticias y precios y no
puede haber colas atascadas silenciosas. Una cola se declara atascada por lo
MEDIDO, no por su profundidad:

- el mismo mensaje lleva >= umbral en CABEZA de la lista ready (persistencia
  del ready id, no message_timestamp: ese incluye el tiempo de RetryAfter en
  la cola diferida y alertaria en un cooldown normal), y
- la variacion neta de profundidad entre ticks es <= 0: no decrece. Es la
  diferencia de pendientes entre muestras (msgs + DQ.msgs, como
  kpi_queue_depth), NO mensajes completados: si entran 50 y salen 50 la
  variacion neta es 0 y una cola asi, con cabeza vieja, esta atascada.

Una medicion por tick aunque el actor corra por tenant (las colas son
globales): el primer tenant que llega en la ventana del tick toma un lease
global, muestrea, guarda la muestra para el siguiente tick y publica el
resultado en Redis; el resto de tenants del mismo tick reutiliza ese
resultado y solo persiste sus ResearchAlert (idempotentes por tenant, cola y
dia; patron source_health_watchdog). Redis caido o lectura fallida =
fail-open (status skipped).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ResearchAlert

logger = logging.getLogger(__name__)

VERSION = "queue-stuck-v2"
ALERT_TYPE = "queue_stuck"

# Fallback estatico: todas las colas declaradas en app.workers (dramatiq_app +
# knowledge_rag_actors). En prod se prefiere broker.get_declared_queues().
DEFAULT_QUEUES = (
    "default", "prices", "thesis", "kpis", "alerts", "gdelt",
    "computed", "externa", "finnhub", "yahoo", "knowledge",
)

_SAMPLE_PREFIX = "queue_watchdog:sample:"  # {ts, depth} del ultimo tick muestreador
_HEAD_PREFIX = "queue_watchdog:head:"      # "<ready_id>:<ts_ms>": desde cuando es cabeza
_TICK_LOCK_KEY = "queue_watchdog:tick_lock"
_RESULT_KEY = "queue_watchdog:last_result"

# Ventana del tick: menor que la cadencia del scheduler (5 min) para que el
# siguiente tick vuelva a muestrear; los tenants del mismo tick reutilizan.
TICK_LOCK_SECONDS = 240
_RESULT_TTL_SECONDS = 900


def max_age_seconds() -> float:
    """Tiempo en cabeza de la lista ready a partir del cual se evalua atasco."""
    try:
        return max(60.0, float(os.getenv("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "900")))
    except ValueError:
        return 900.0


def watched_queues(broker: Any = None) -> tuple[str, ...]:
    raw = os.getenv("QUEUE_WATCHDOG_QUEUES")
    if raw:
        queues = tuple(q.strip() for q in raw.split(",") if q.strip())
        if queues:
            return queues
    if broker is not None:
        try:
            declared = tuple(sorted(broker.get_declared_queues()))
            if declared:
                return declared
        except Exception:  # noqa: BLE001 - el fallback estatico siempre vale
            logger.warning(
                "queue_watchdog: no se pudieron listar las colas declaradas del broker; "
                "se usa la lista estatica",
                exc_info=True,
            )
    return DEFAULT_QUEUES


@dataclass(frozen=True)
class QueueSample:
    queue: str
    depth: int
    ready_age_seconds: float | None  # None: cola vacia; 0: cabeza vista por primera vez


def _as_str(raw: Any) -> str:
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def _ready_head_age(client: Any, base: str, queue: str, now_ms: float) -> float | None:
    """Segundos que el mensaje en cabeza lleva listo sin consumir.

    Persistencia del ready id: la primera vez que un id es cabeza se anota su
    instante; mientras siga siendo cabeza, su edad crece. Cola vacia: se borra
    la anotacion (None). Nunca usa message_timestamp (incluye RetryAfter).
    """
    ids = client.lrange(base, 0, 0)
    key = f"{_HEAD_PREFIX}{queue}"
    if not ids:
        client.delete(key)
        return None
    head = _as_str(ids[0])
    raw = client.get(key)
    if raw is not None:
        stored_id, _, stored_ts = _as_str(raw).partition(":")
        if stored_id == head:
            return max(0.0, (now_ms - float(stored_ts)) / 1000.0)
    client.set(key, f"{head}:{now_ms}")
    return 0.0


def sample_queues(client: Any, *, namespace: str = "dramatiq", queues: tuple[str, ...] = DEFAULT_QUEUES,
                  now_ms: float | None = None) -> list[QueueSample]:
    """Profundidad (msgs + DQ.msgs) y edad de la cabeza ready por cola."""
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    samples = []
    for queue in queues:
        base = f"{namespace}:{queue}"
        depth = int(client.hlen(f"{base}.msgs")) + int(client.hlen(f"{base}.DQ.msgs"))
        samples.append(QueueSample(queue=queue, depth=depth,
                                   ready_age_seconds=_ready_head_age(client, base, queue, now_ms)))
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
    # como primera (sin variacion medible, no alerta), nunca como drenaje falso.
    client.set(f"{_SAMPLE_PREFIX}{queue}", json.dumps({"ts": ts, "depth": depth}), ex=1800)


def detect_stuck(samples: list[QueueSample], previous: dict[str, dict[str, float] | None],
                 *, max_age: float, now: float) -> list[dict[str, Any]]:
    """Colas atascadas: cabeza vieja y profundidad que no decrece. Funcion pura."""
    stuck = []
    for sample in samples:
        age = sample.ready_age_seconds
        prev = previous.get(sample.queue)
        if age is None or age < max_age or prev is None:
            continue
        elapsed = max(1.0, now - prev["ts"])
        # Variacion neta de profundidad (mensajes/s); <= 0: no decrece.
        net_rate = (prev["depth"] - sample.depth) / elapsed
        if net_rate > 0:
            continue
        stuck.append({
            "queue": sample.queue,
            "depth": sample.depth,
            "ready_age_seconds": round(age, 1),
            "net_rate_per_s": round(net_rate, 4),
        })
    return stuck


def sample_tick(client: Any, *, namespace: str, queues: tuple[str, ...], now: datetime) -> dict[str, Any]:
    """Muestrea, detecta y guarda la muestra para el siguiente tick."""
    now_ms = now.timestamp() * 1000
    samples = sample_queues(client, namespace=namespace, queues=queues, now_ms=now_ms)
    previous = {sample.queue: load_previous(client, sample.queue) for sample in samples}
    stuck = detect_stuck(samples, previous, max_age=max_age_seconds(), now=now.timestamp())
    for sample in samples:
        save_sample(client, sample.queue, ts=now.timestamp(), depth=sample.depth)
    return {"ts": now.timestamp(), "queues": len(samples), "stuck": stuck}


def tick_result(client: Any, *, namespace: str, queues: tuple[str, ...], now: datetime,
                tick_lock_seconds: int = TICK_LOCK_SECONDS) -> dict[str, Any]:
    """Una medicion por tick aunque el actor corra una vez por tenant.

    El primero de la ventana toma el lease global y muestrea; los demas
    reutilizan el resultado cacheado (y no pisan la muestra: sin el lease, el
    segundo tenant media contra la muestra de hace milisegundos).
    """
    if client.set(_TICK_LOCK_KEY, "1", nx=True, ex=tick_lock_seconds):
        result = sample_tick(client, namespace=namespace, queues=queues, now=now)
        client.set(_RESULT_KEY, json.dumps(result), ex=_RESULT_TTL_SECONDS)
        result["sampled"] = True
        return result
    raw = client.get(_RESULT_KEY)
    if raw is None:
        # El muestreador aun no publica (tick en curso): este tenant alertara
        # en el siguiente tick; el fingerprint por dia lo mantiene idempotente.
        return {"ts": now.timestamp(), "queues": 0, "stuck": [], "sampled": False,
                "deferred": True}
    result = json.loads(raw)
    result["sampled"] = False
    return result


def _message(item: dict[str, Any]) -> tuple[str, str, str]:
    title = f"Cola {item['queue']} atascada"
    message = (
        f"La cola {item['queue']} no decrece: {item['depth']} mensajes pendientes, "
        f"el mensaje en cabeza lleva {item['ready_age_seconds']:.0f} s listo sin "
        f"consumirse y la variacion neta de profundidad entre ticks es "
        f"{item['net_rate_per_s']} msg/s. Revisar workers de esa cola (cuota IP, "
        "errores o proceso caido)."
    )
    return "high", title, message


def emit_queue_stuck_alerts(
    db: Session,
    *,
    client: Any = None,
    namespace: str = "dramatiq",
    now: datetime | None = None,
    tick_lock_seconds: int = TICK_LOCK_SECONDS,
) -> dict[str, Any]:
    """Detecta colas atascadas y persiste ResearchAlert in-app por tenant."""
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    if client is None:
        from app.workers.dramatiq_app import _redis_client, broker

        client = _redis_client()
        namespace = broker.namespace
        if client is None:
            return {"status": "skipped", "reason": "redis_unavailable", "created": []}
        queues = watched_queues(broker)
    else:
        queues = watched_queues()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        result = tick_result(client, namespace=namespace, queues=queues, now=now,
                             tick_lock_seconds=tick_lock_seconds)
    except Exception:  # noqa: BLE001 - Redis caido o lectura corrupta: fail-open
        return {"status": "skipped", "reason": "redis_unavailable", "created": []}
    created: list[int] = []
    existing = 0
    for item in result["stuck"]:
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
    return {
        "status": "ok",
        "queues": result["queues"],
        "sampled": result["sampled"],
        "deferred": result.get("deferred", False),
        "stuck": len(result["stuck"]),
        "created": created,
        "existing": existing,
    }
