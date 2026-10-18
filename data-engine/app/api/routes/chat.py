from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.schemas import ChatRequest, ChatResponse
from app.services.async_bridge import run_from_any_context
from app.services.chat_service import ChatService

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    # ChatService.answer mezcla sqlalchemy sincrono y llamadas LLM entre sus
    # awaits: todo el servicio corre en un hilo del pool, con su corutina
    # puenteado. Awaitado inline bloqueaba el event loop del proceso.
    return await run_in_threadpool(
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
