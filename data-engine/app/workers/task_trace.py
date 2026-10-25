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
  copiar fuera del host. Tope de tamano (`TRACE_SNAPSHOT_MAX_BYTES`, 1 MiB; el
  resto se cuenta en `truncated`) y de tiempo (`TRACE_SNAPSHOT_TIMEOUT_S`, 3 s,
  hilo daemon). Limites: el hook corre antes de parar los workers, asi que
  mensajes que entren durante la captura no quedan incluidos, y no recupera
  nada tras SIGKILL.
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


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


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
        self._seq = 0

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
            # un message_id repetido en vuelo (reentrega) no pisa la entrada anterior
            self._seq += 1
            self._inflight[f"{message.message_id}#{self._seq}"] = {
                "started": time.monotonic(),
                "started_at": datetime.now(UTC).isoformat(),
                "message": message,
            }
        logger.info("task_start %s", self._fields(message))

    def _finish(self, message: Any, outcome: str) -> None:
        with self._lock:
            key = next(
                (k for k, e in self._inflight.items() if e["message"] is message), None
            )
            entry = self._inflight.pop(key, None) if key else None
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
                    "message_id": entry["message"].message_id,
                    "started_at": entry["started_at"],
                    "actor": entry["message"].actor_name,
                    "queue": entry["message"].queue_name,
                    "retries": entry["message"].options.get("retries", 0),
                    "args_hash": args_digest(entry["message"]),
                }
                for entry in self._inflight.values()
            ]

    def before_worker_shutdown(self, broker: Any, worker: Any) -> None:
        directory = os.getenv("TRACE_SNAPSHOT_DIR", "")
        with self._lock:
            pending = [e["message"] for e in self._inflight.values()]
        logger.info("worker_shutdown inflight=%d", len(pending))
        if not directory or not pending:
            return
        # Hilo daemon con tope de tiempo: un FS lento no bloquea la parada.
        timeout = _int_env("TRACE_SNAPSHOT_TIMEOUT_S", 3, 1)
        outcome: dict[str, str] = {}

        def run() -> None:
            try:
                self._write_snapshot(directory, pending)
            except Exception as exc:  # noqa: BLE001 - la traza nunca rompe la parada
                outcome["error"] = type(exc).__name__

        worker_thread = threading.Thread(target=run, name="task-trace-snapshot", daemon=True)
        worker_thread.start()
        worker_thread.join(timeout)
        if worker_thread.is_alive():
            logger.warning("snapshot_timeout seconds=%d", timeout)
        elif "error" in outcome:
            logger.warning("snapshot_failed type=%s", outcome["error"])

    def _write_snapshot(self, directory: str, pending: list[Any]) -> None:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = os.path.join(directory, f"inflight-{stamp}-{os.getpid()}.json")
        max_bytes = _int_env("TRACE_SNAPSHOT_MAX_BYTES", 1_048_576, 4096)
        items: list[dict[str, Any]] = []
        used = 0
        for m in pending:
            item = m.asdict()
            size = len(json.dumps(item, default=str))
            if used + size > max_bytes:
                break
            items.append(item)
            used += size
        body = {
            "ts": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "inflight": items,
            "truncated": len(pending) - len(items),
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
