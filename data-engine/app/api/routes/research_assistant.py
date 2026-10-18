"""Isolated, read-only research exploration and guided review."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.schemas import ChatPageContext
from app.services.brain_service import resolve_page_context
from app.services.research_assistant_narrative import synthesize
from app.services.research_assistant_service import answer, guide_context

router = APIRouter()


class AssistantRequest(BaseModel):
    mode: Literal["explore", "guide"]
    question: str = Field(min_length=3, max_length=2000)
    ticker: str | None = Field(default=None, min_length=1, max_length=20)
    review_id: int | None = Field(default=None, ge=1)
    page: ChatPageContext | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        if self.mode == "guide" and not self.ticker:
            raise ValueError("El modo guía requiere un ticker")
        if self.review_id and not self.ticker:
            raise ValueError("El ticket requiere un ticker")
        return self


class AssistantSection(BaseModel):
    key: Literal["facts", "calculations", "hypotheses", "inferences", "contradictions", "insufficient_data", "conclusion"]
    body: str
    citation_ids: list[str] = Field(default_factory=list)


class AssistantCitation(BaseModel):
    id: str
    kind: Literal["news_event", "financial_fact", "document_chunk", "claim_evidence", "market_observation", "thesis_record"]
    source: str
    url: str | None = None
    as_of: str | None = None
    excerpt: str | None = None


class AssistantResponse(BaseModel):
    mode: Literal["explore", "guide"]
    status: Literal["answered", "insufficient_data"]
    answer: str
    sections: list[AssistantSection]
    citations: list[AssistantCitation]
    missing_data: list[str]
    suggested_next_steps: list[str]
    review_id: int | None
    writeback: Literal[False] = False
    # Eco del contexto de página resuelto en servidor (pastilla "Viendo X").
    context: dict | None = None


class ContextNews(BaseModel):
    id: int
    title: str
    source: str
    source_url: str | None
    date: datetime
    date_source: str


class ContextReview(BaseModel):
    id: int
    status: str
    summary: str


class GuideContextResponse(BaseModel):
    ticker: str
    review_id: int | None
    open_reviews: list[ContextReview]
    latest_news: list[ContextNews]
    missing_data: list[str]


@router.post("/assistant", response_model=AssistantResponse)
async def research_assistant(payload: AssistantRequest, db: Session = Depends(get_db)) -> AssistantResponse:
    # Contexto de página explícito: en modo explore el ticker de la página
    # (resuelto en catálogo; contenido privado acotado al tenant) completa la pregunta sin
    # ticker. El modo guía sigue exigiendo ticker explícito.
    # resolve_page_context y answer son sqlalchemy sincrono: hilo del pool.
    # synthesize (LLM) es async real y se queda awaitado.
    page_context = await run_in_threadpool(resolve_page_context, db, payload.page)
    if payload.mode == "explore" and not payload.ticker and page_context and page_context.company:
        payload = payload.model_copy(update={"ticker": page_context.company.ticker})
    try:
        baseline = await run_in_threadpool(answer, db, payload)
        response = AssistantResponse.model_validate(await synthesize(db, payload, baseline))
        response.context = page_context.echo() if page_context else None
        return response
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/guide-context", response_model=GuideContextResponse)
def research_guide_context(
    ticker: str = Query(min_length=1, max_length=20), db: Session = Depends(get_db),
) -> GuideContextResponse:
    try:
        return GuideContextResponse.model_validate(guide_context(db, ticker))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
