"""Stage 3: Langfuse Cloud EU shadow tracing — SOLO observabilidad.

Reglas duras:
- Nunca es fuente de verdad: el estado de negocio vive en Postgres
  (workflow_runs, thesis_versions, ...). Langfuse solo observa.
- Sin contenido sensible: jamas se envian prompts, completaciones,
  payloads, filings, cabeceras auth ni IDs crudos de tenant/usuario. Solo
  la allowlist de metadatos (nombres, duraciones, estados, contadores,
  hashes). El tenant viaja como hash SHA-256 truncado.
- Muestreo estricto: LANGFUSE_SAMPLE_RATE (10% por defecto) decide las
  corridas OK; los FALLOS se trazan siempre (buffer en memoria de
  nombres/duraciones, sin contenido).
- Todo es best-effort: cualquier fallo del tracer se traga con log; el
  tracing nunca rompe una ejecucion de negocio.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import random
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Traza activa de la corrida en curso (request o actor). Los spans de
# generacion LLM se cuelgan de ella; sin traza activa no se emite nada.
_current_tracer: contextvars.ContextVar[ShadowTracer | None] = contextvars.ContextVar(
    "cavaai_current_tracer", default=None
)


def set_current_tracer(tracer: ShadowTracer | None) -> contextvars.Token:
    return _current_tracer.set(tracer)


def reset_current_tracer(token: contextvars.Token) -> None:
    _current_tracer.reset(token)


def trace_generation(
    *,
    name: str,
    model: str | None,
    metadata: dict[str, Any] | None = None,
    usage: dict[str, int] | None = None,
    error_class: str | None = None,
) -> None:
    """Span de generacion LLM sobre la traza activa, si la hay."""
    tracer = _current_tracer.get()
    if tracer is None:
        return
    tracer.generation(
        name=name, model=model, metadata=metadata, usage=usage, error_class=error_class
    )

# Unicas claves de metadatos que pueden salir hacia Langfuse.
METADATA_ALLOWLIST = {
    "workflow_name",
    "run_id",
    "step_run_id",
    "tenant_hash",
    "ticker",
    "trigger",
    "git_sha",
    "app_version",
    "input_fingerprint",
    "execution_mode",
    "step",
    "position",
    "attempt",
    "status",
    "error_class",
    "duration_ms",
    "retry_count",
    "provider",
    "model",
    "route",
    "task",
    "fallback",
    "fallback_trigger",
    "fallback_from",
    "primary_error",
    "degraded",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_tokens",
    "artifact_ids",
    "item_count",
    "prompt_name",
    "prompt_version",
    "prompt_hash",
    "prompt_source",
    "prompt_lang",
    # Escalares de observabilidad que el workflow de Langfuse ya emitia.
    "latency_ms",
    "cost",
}


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Solo pasa la allowlist; valores reducidos a tipos simples."""
    if not metadata:
        return {}
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in METADATA_ALLOWLIST:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, (list, tuple)):
            clean[key] = [str(item) for item in value][:20]
        else:
            clean[key] = str(value)[:200]
    return clean


def tenant_hash(tenant_id: int | None) -> str | None:
    if tenant_id is None:
        return None
    return hashlib.sha256(f"tenant:{tenant_id}".encode()).hexdigest()[:16]


def input_fingerprint(payload: dict[str, Any] | None) -> str | None:
    """Hash del input para correlacionar sin enviar el contenido."""
    if not payload:
        return None
    try:
        import json

        canonical = json.dumps(payload, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        canonical = repr(payload)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class ShadowTracer:
    """Una traza de un workflow run. Inerte salvo que `active` sea True."""

    def __init__(
        self,
        *,
        client_factory,
        workflow_name: str,
        run_id: int | None,
        metadata: dict[str, Any],
        active: bool,
    ) -> None:
        self._client_factory = client_factory
        self.workflow_name = workflow_name
        self.run_id = run_id
        self.metadata = sanitize_metadata(
            {**(metadata or {}), "workflow_name": workflow_name, "run_id": run_id}
        )
        self.active = active
        self._client = None
        self._root = None
        self._failed = False
        # Buffer de pasos para trazar fallos aunque la corrida no muestreara.
        self._step_buffer: list[dict[str, Any]] = []

    def _ensure_client(self):
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def _start_root(self) -> None:
        if self._root is not None:
            return
        client = self._ensure_client()
        trace_id = client.create_trace_id()
        self._root = client.start_observation(
            trace_context={"trace_id": trace_id},
            name=self.workflow_name,
            metadata=self.metadata,
        )

    @contextmanager
    def step(self, position: int, name: str) -> Iterator[None]:
        started = time.monotonic()
        error_class: str | None = None
        try:
            yield
        except Exception as exc:
            error_class = type(exc).__name__
            raise
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            record = {
                "step": name,
                "position": position,
                "status": "failed" if error_class else "succeeded",
                "error_class": error_class,
                "duration_ms": duration_ms,
            }
            self._step_buffer.append(record)
            if error_class:
                self._failed = True
            if self.active:
                try:
                    self._start_root()
                    span = self._root.start_observation(
                        name=name,
                        metadata=sanitize_metadata(
                            {**self.metadata, **record}
                        ),
                        level="ERROR" if error_class else "DEFAULT",
                        status_message=error_class,
                    )
                    span.end()
                except Exception:  # noqa: BLE001 - tracing jamas rompe
                    logger.debug("langfuse step span failed", exc_info=True)

    def generation(
        self,
        *,
        name: str,
        model: str | None,
        metadata: dict[str, Any] | None = None,
        usage: dict[str, int] | None = None,
        error_class: str | None = None,
    ) -> None:
        if error_class:
            self._failed = True
        if not self.active:
            return
        try:
            self._start_root()
            generation = self._root.start_observation(
                as_type="generation",
                name=name,
                model=model,
                metadata=sanitize_metadata(metadata),
                usage_details=usage or None,
                level="ERROR" if error_class else "DEFAULT",
                status_message=error_class,
            )
            generation.end()
        except Exception:  # noqa: BLE001
            logger.debug("langfuse generation span failed", exc_info=True)

    def finish(self, *, status: str, error_class: str | None = None) -> None:
        failed = status != "succeeded" or error_class is not None or self._failed
        try:
            if not self.active:
                if not failed:
                    return
                # Traza tardia de fallo: solo el buffer de pasos (nombres,
                # duraciones, clases de error), nunca contenido.
                self.active = True
                self._start_root()
                for record in self._step_buffer:
                    span = self._root.start_observation(
                        name=record["step"],
                        metadata=sanitize_metadata({**self.metadata, **record}),
                        level="ERROR" if record["error_class"] else "DEFAULT",
                        status_message=record["error_class"],
                    )
                    span.end()
            else:
                self._start_root()
            self._root.update(
                metadata=sanitize_metadata(
                    {**self.metadata, "status": "failed" if failed else "succeeded",
                     "error_class": error_class}
                ),
                level="ERROR" if failed else "DEFAULT",
                status_message=error_class,
            )
            self._root.end()
            client = self._ensure_client()
            client.flush()
        except Exception:  # noqa: BLE001
            logger.debug("langfuse finish failed", exc_info=True)


def _default_client_factory():
    """Cliente Langfuse real (import perezoso; SDK opcional en tests)."""
    from langfuse import Langfuse

    from app.core.config import get_settings

    settings = get_settings()
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )


def begin_trace(
    workflow_name: str,
    *,
    run_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    client_factory=None,
    sample_decision: bool | None = None,
) -> ShadowTracer:
    """Crea el tracer de una corrida. Inerte si esta deshabilitado o sin keys."""
    from app.core.config import get_settings

    settings = get_settings()
    active = bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    )
    if active:
        if sample_decision is None:
            sample_decision = random.random() < settings.langfuse_sample_rate
        active = sample_decision
    return ShadowTracer(
        client_factory=client_factory or _default_client_factory,
        workflow_name=workflow_name,
        run_id=run_id,
        metadata=metadata or {},
        active=active,
    )
