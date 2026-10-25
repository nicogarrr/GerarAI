import asyncio
import logging
import sys
import threading
import time
import traceback

import anyio.to_thread
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.schemas import ChatRequest, ChatResponse
from app.services.async_bridge import run_from_any_context
from app.services.chat_service import ChatService
from app.services.chat_telemetry import classify_response, record_chat_event

router = APIRouter()
logger = logging.getLogger(__name__)

# Margen sobre el plazo cooperativo (chat_total_timeout_seconds). El plazo
# interno solo se aplica en los puntos de espera: un paso que bloquea el hilo
# (trabajo sincrono, CPU) lo deja vencido sin poder cortarlo y la peticion
# acababa tardando 70-100 s. Este muro corta desde el event loop principal,
# que no se bloquea con el trabajo del hilo.
CHAT_HARD_GRACE_SECONDS = 6.0
# anyio libera el hueco del pool al abandonar un hilo, asi que sin tope propio
# varios hilos atascados se acumularian. Cuenta hilos de chat realmente vivos
# (hasta que terminan, no hasta que se abandonan) y rechaza con honestidad.
CHAT_MAX_LIVE_WORKERS = 6
_live_workers = 0
_live_lock = threading.Lock()


def _log_stuck_worker(ident: int | None, waited: float) -> None:
    """Deja en el log DONDE esta parado el hilo (solo lineas de codigo, sin datos)."""
    frame = sys._current_frames().get(ident) if ident is not None else None
    where = "".join(traceback.format_stack(frame, limit=14)) if frame is not None else "hilo ya terminado"
    logger.warning("chat hard deadline after %.1fs; worker thread stack:\n%s", waited, where)


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    # ChatService.answer mezcla sqlalchemy sincrono y llamadas LLM entre sus
    # awaits: todo el servicio corre en un hilo del pool, con su corutina
    # puenteado. Awaitado inline bloqueaba el event loop del proceso.
    started = time.monotonic()
    tenant_id = db.info.get("tenant_id")
    worker: dict[str, int | None] = {"ident": None}
    slot = {"started": False, "cancelled": False, "released": False}
    tenant_info = dict(db.info)

    def _release() -> None:
        global _live_workers
        with _live_lock:
            if not slot["released"]:
                slot["released"] = True
                _live_workers -= 1

    def _work() -> ChatResponse:
        with _live_lock:
            if slot["cancelled"]:
                raise asyncio.CancelledError  # abandonado antes de arrancar
            slot["started"] = True
        worker["ident"] = threading.get_ident()
        try:
            return _work_inner()
        finally:
            _release()  # el hueco vuelve cuando el hilo TERMINA, no al abandonarlo

    def _work_inner() -> ChatResponse:
        # Sesion propia del hilo: si el muro corta la peticion, el hilo puede
        # seguir un rato y no debe compartir la sesion que get_db va a cerrar.
        with SessionLocal() as worker_db:
            worker_db.info.update(tenant_info)
            return run_from_any_context(
                ChatService().answer(
                    worker_db,
                    payload.question,
                    payload.scope,
                    payload.ticker,
                    enable_debate=payload.enable_debate,
                    page=payload.page,
                    history=payload.history,
                )
            )

    # Reserva atomica del hueco antes de despachar: el tope es exacto.
    global _live_workers
    with _live_lock:
        busy = _live_workers >= CHAT_MAX_LIVE_WORKERS
        if not busy:
            _live_workers += 1
    if busy:
        logger.warning("chat busy: %d live workers", CHAT_MAX_LIVE_WORKERS)
        return ChatResponse(
            answer="El asistente está ocupado con otras consultas; vuelve a intentarlo en un momento.",
            sources=[], model="deterministic", confidence=0,
            llm_trace={"path": "chat_busy", "fallback": True, "fallback_reason": "chat_busy"},
        )
    hard_limit = get_settings().chat_total_timeout_seconds + CHAT_HARD_GRACE_SECONDS
    try:
        try:
            response = await asyncio.wait_for(anyio.to_thread.run_sync(_work, abandon_on_cancel=True), timeout=hard_limit)
        except TimeoutError:
            waited = time.monotonic() - started
            if waited < hard_limit - 0.5:
                raise  # TimeoutError propio del servicio, no el muro
            _log_stuck_worker(worker["ident"], waited)
            response = ChatResponse(
                answer="La respuesta tardó demasiado; vuelve a intentarlo en un momento.",
                sources=[], model="deterministic", confidence=0,
                llm_trace={"path": "chat_hard_deadline", "fallback": True, "fallback_reason": "chat_hard_deadline",
                           "deadline_seconds": get_settings().chat_total_timeout_seconds},
            )
    except TimeoutError:
        response = ChatResponse(
            answer="La respuesta tardó demasiado; vuelve a intentarlo en un momento.",
            sources=[], model="deterministic", confidence=0,
            llm_trace={"fallback": True, "fallback_reason": "chat_total_deadline",
                       "deadline_seconds": get_settings().chat_total_timeout_seconds},
        )
    except Exception as exc:
        record_chat_event(
            tenant_id=tenant_id,
            question=payload.question,
            route="error",
            used_llm=False,
            model=None,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        with _live_lock:
            never_started = not slot["started"]
            if never_started:
                slot["cancelled"] = True
        if never_started:
            _release()
    route, used_llm = classify_response(response)
    record_chat_event(
        tenant_id=tenant_id,
        question=payload.question,
        route=route,
        used_llm=used_llm,
        model=response.model,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return response
