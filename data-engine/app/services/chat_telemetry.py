"""Telemetría propia de /api/chat (€0, sin Langfuse).

Cada respuesta (o error) del chat se persiste con su pregunta, ruta,
latencia y modelo en ``chat_telemetry_events``. Best effort: un fallo de
escritura se registra y nunca rompe el chat.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.database import SessionLocal
from app.models import ChatTelemetryEvent

logger = logging.getLogger(__name__)

_MAX_TEXT = 500


def classify_response(response: Any) -> tuple[str, bool]:
    """Ruta y si respondió un LLM, derivados del contrato ChatResponse.

    LLM = la traza lleva proveedor y modelo real y no es el degradado
    determinista (fallback). Las rutas deterministas (small_talk,
    portfolio_*, fallback) quedan como no-LLM.
    """
    trace = getattr(response, "llm_trace", None) or {}
    route = str(trace.get("path") or "chat_synthesis")
    used_llm = bool(
        trace.get("provider")
        and trace.get("model") not in (None, "deterministic")
        and not trace.get("fallback")
    )
    return route[:60], used_llm


def record_chat_event(
    *,
    tenant_id: int | None,
    question: str,
    route: str,
    used_llm: bool,
    model: str | None,
    latency_ms: int,
    error: str | None = None,
) -> None:
    """Persiste un evento de telemetría; nunca lanza hacia el chat."""
    try:
        with SessionLocal() as db:
            if tenant_id is not None:
                db.info["tenant_id"] = tenant_id
            db.add(
                ChatTelemetryEvent(
                    question=(question or "")[:_MAX_TEXT],
                    route=route[:60],
                    used_llm=used_llm,
                    model=(model or None) and model[:160],
                    latency_ms=max(0, int(latency_ms)),
                    error=(error or None) and error[:_MAX_TEXT],
                )
            )
            db.commit()
    except Exception:  # noqa: BLE001 — la telemetría no rompe el chat
        logger.exception("chat telemetry write failed")
