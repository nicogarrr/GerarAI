"""Traza de actores Dramatiq por message_id, sin argumentos crudos.

Objetivo: poder reconstruir despues de un reinicio que mensaje (actor, cola,
reintento) estaba en vuelo y si termino. Los logs de Dramatiq no imprimen
message_id, y el payload desaparece del hash `*.msgs` al hacer ack.

Privacidad:
- Los logs llevan actor, cola, message_id, reintentos, numero de args, nombres
  de kwargs, resultado y duracion. Nunca valores de args/kwargs.
- `args_hash` es HMAC-SHA256 con `TRACE_HASH_KEY` (truncado). Sin clave no se
  emite hash ("-"): un hash sin clave de ids pequenos es reversible por fuerza
  bruta.
- La captura del payload completo antes de parar el worker es opt-in
  (`TRACE_SNAPSHOT_DIR`), dir 0700, ficheros 0600, retencion finita
  (`TRACE_SNAPSHOT_KEEP`, 5 por defecto). Contiene args reales: no exponer ni
  copiar fuera del host.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

from dramatiq.middleware import Middleware

logger = logging.getLogger("dramatiq.task_trace")


def _hash_key() -> bytes | None:
    key = os.getenv("TRACE_HASH_KEY", "")
    return key.encode() if len(key) >= 16 else None


def args_digest(message: Any) -> str:
    key = _hash_key()
    if key is None:
        return "-"
    try:
        raw = json.dumps([message.args, message.kwargs], sort_keys=True, default=str)
    except (TypeError, ValueError):
        return "-"
    return hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()[:16]


def _keep() -> int:
    try:
        return max(1, int(os.getenv("TRACE_SNAPSHOT_KEEP", "5")))
    except ValueError:
        return 5


class TaskTraceMiddleware(Middleware):
    """Registra inicio/fin por message_id y captura en vuelo al parar el worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _fields(message: Any) -> str:
        return (
            f"actor={message.actor_name} queue={message.queue_name} "
            f"message_id={message.message_id} "
            f"redis_message_id={message.options.get('redis_message_id', '-')} "
            f"retries={message.options.get('retries', 0)} "
            f"nargs={len(message.args)} kwargs={','.join(sorted(message.kwargs)) or '-'} "
            f"args_hash={args_digest(message)}"
        )

    def before_process_message(self, broker: Any, message: Any) -> None:
        with self._lock:
            self._inflight[message.message_id] = {
                "started": time.monotonic(),
                "started_at": datetime.now(UTC).isoformat(),
                "message": message,
            }
        logger.info("task_start %s", self._fields(message))

    def _finish(self, message: Any, outcome: str) -> None:
        with self._lock:
            entry = self._inflight.pop(message.message_id, None)
        ms = int((time.monotonic() - entry["started"]) * 1000) if entry else -1
        logger.info("task_end %s outcome=%s duration_ms=%d", self._fields(message), outcome, ms)

    def after_process_message(
        self, broker: Any, message: Any, *, result: Any = None, exception: BaseException | None = None
    ) -> None:
        self._finish(message, "ok" if exception is None else f"error:{type(exception).__name__}")

    def after_skip_message(self, broker: Any, message: Any) -> None:
        self._finish(message, "skipped")

    def inflight(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "message_id": mid,
                    "started_at": entry["started_at"],
                    "actor": entry["message"].actor_name,
                    "queue": entry["message"].queue_name,
                    "retries": entry["message"].options.get("retries", 0),
                    "args_hash": args_digest(entry["message"]),
                }
                for mid, entry in self._inflight.items()
            ]

    def before_worker_shutdown(self, broker: Any, worker: Any) -> None:
        directory = os.getenv("TRACE_SNAPSHOT_DIR", "")
        with self._lock:
            pending = [e["message"] for e in self._inflight.values()]
        logger.info("worker_shutdown inflight=%d", len(pending))
        if not directory or not pending:
            return
        try:
            self._write_snapshot(directory, pending)
        except OSError as exc:  # la parada no debe bloquearse por la traza
            logger.warning("snapshot_failed type=%s", type(exc).__name__)

    def _write_snapshot(self, directory: str, pending: list[Any]) -> None:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = os.path.join(directory, f"inflight-{stamp}-{os.getpid()}.json")
        body = {
            "ts": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "inflight": [m.asdict() for m in pending],
        }
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(body, handle, default=str)
        files = sorted(f for f in os.listdir(directory) if f.startswith("inflight-"))
        for old in files[: -_keep()]:
            try:
                os.remove(os.path.join(directory, old))
            except OSError:
                pass
        logger.info("snapshot_written n=%d file=%s", len(pending), os.path.basename(path))
