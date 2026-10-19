import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas import ChatRequest, ChatResponse
from app.services.async_bridge import run_from_any_context
from app.services.chat_service import ChatService
from app.services.chat_telemetry import classify_response, record_chat_event

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    # ChatService.answer mezcla sqlalchemy sincrono y llamadas LLM entre sus
    # awaits: todo el servicio corre en un hilo del pool, con su corutina
    # puenteado. Awaitado inline bloqueaba el event loop del proceso.
    started = time.monotonic()
    tenant_id = db.info.get("tenant_id")
    try:
        response = await run_in_threadpool(
            lambda: run_from_any_context(
                ChatService().answer(
                    db,
                    payload.question,
                    payload.scope,
                    payload.ticker,
                    enable_debate=payload.enable_debate,
                    page=payload.page,
                    history=payload.history,
                )
            )
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
