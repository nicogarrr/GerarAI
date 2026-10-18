from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.core.config import get_settings
from app.services.tracing import sanitize_metadata

_ERROR_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")


def _safe_status_message(error: str | None) -> str | None:
    """Only an exception class name may leave the process; free text may carry
    prompts, keys or user data, so anything else collapses to a generic marker."""
    if not error:
        return None
    return error if _ERROR_CLASS.match(error) else "error"


@dataclass
class TraceHandle:
    """Local trace mirror; it remains inspectable when Langfuse is disabled."""

    name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str | None = None

    def update(self, **metadata: Any) -> None:
        self.metadata.update(metadata)


def _remote_output(output: Any) -> Any:
    """Solo escalares no textuales salen a Langfuse: una cadena puede ser
    contenido de usuario, de documentos o de la respuesta del modelo."""
    if isinstance(output, dict):
        return {
            str(k): v for k, v in output.items() if isinstance(v, (bool, int, float)) or v is None
        }
    if isinstance(output, (bool, int, float)) or output is None:
        return output
    return None


class LangfuseTracer:
    def __init__(self) -> None:
        self.settings = get_settings()

    @contextmanager
    def workflow(
        self, name: str, metadata: dict[str, Any] | None = None
    ) -> Iterator[TraceHandle]:
        started = perf_counter()
        handle = TraceHandle(name=name, metadata=dict(metadata or {}))
        client = None
        remote_trace = None
        if self.settings.langfuse_enabled:
            try:
                from langfuse import Langfuse

                client = Langfuse(
                    public_key=self.settings.langfuse_public_key,
                    secret_key=self.settings.langfuse_secret_key,
                    host=self.settings.langfuse_host,
                )
                remote_trace = client.start_observation(
                    name=name, metadata=sanitize_metadata(handle.metadata)
                )
            except Exception as exc:  # observability must not break analysis
                handle.metadata["telemetry_setup_error"] = type(exc).__name__
        try:
            yield handle
        except Exception as exc:
            handle.error = type(exc).__name__
            raise
        finally:
            handle.metadata["latency_ms"] = round((perf_counter() - started) * 1000, 3)
            if remote_trace is not None:
                try:
                    remote_trace.update(
                        metadata=sanitize_metadata(handle.metadata),
                        output=_remote_output(handle.output),
                        level="ERROR" if handle.error else "DEFAULT",
                        status_message=_safe_status_message(handle.error),
                    )
                    remote_trace.end()
                    client.flush()
                except Exception as exc:  # keep a visible local failure counter
                    handle.metadata["telemetry_flush_error"] = type(exc).__name__
