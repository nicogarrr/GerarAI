from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Company, NewsEvent
from app.schemas import ManualNewsRequest, ManualNewsResponse, NewsIngestRequest, NewsIngestResponse
from app.services.news_headline_translation import display_translation, original_headline, translate_headline
from app.services.news_service import NewsService
from app.services.second_order_news_service import analyze_second_order
from app.services.ticker_news_lane import _only_ticker_prefix_mention

router = APIRouter()

_TICKER_SCAN_LIMIT = 400


def _is_off_topic(event: NewsEvent, company: Company | None) -> bool:
    metadata = event.metadata_ or {}
    if company is None or not metadata.get("headline_from_source", True):
        return False
    return _only_ticker_prefix_mention(company, event.title or "", event.summary or "")


@router.post("/manual", response_model=ManualNewsResponse)
def manual_news(payload: ManualNewsRequest, db: Session = Depends(get_db)) -> ManualNewsResponse:
    return NewsService().analyze_manual_news(db, payload.text, payload.source, payload.url)


@router.post("/ingest", response_model=NewsIngestResponse)
def ingest_news(payload: NewsIngestRequest, db: Session = Depends(get_db)) -> NewsIngestResponse:
    return NewsService().ingest_news_items(db, payload.items, payload.source)


@router.get("")
def news_events(
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    lane: Literal["empresa", "macro"] | None = None,
    ticker: Annotated[str | None, Query(max_length=20)] = None,
) -> list[dict]:
    """Eventos por pagina (scroll infinito). ``lane`` filtra en SQL:
    ``empresa`` = atribuido a una empresa real; ``macro`` = carril macro GDELT.
    ``ticker`` limita a los eventos de esa empresa (ficha de accion)."""
    stmt = select(NewsEvent, Company).outerjoin(Company, NewsEvent.company_id == Company.id)
    if ticker:
        stmt = stmt.where(Company.ticker == ticker.strip().upper())
    if lane == "empresa":
        stmt = stmt.where(NewsEvent.company_id.is_not(None))
    elif lane == "macro":
        stmt = stmt.where(NewsEvent.metadata_["news_lane"].as_string() == "macro")
    ordered = stmt.order_by(desc(NewsEvent.date), desc(NewsEvent.id))
    if ticker:
        # Lectura de la ficha: se ocultan filas etiquetadas con el ticker cuyo
        # titular y resumen no citan a la empresa (ticker pegado delante, nada
        # mas). Criterio sin LLM; las filas no se borran.
        candidates = db.execute(ordered.limit(_TICKER_SCAN_LIMIT)).all()
        rows = [
            (event, company)
            for event, company in candidates
            if not _is_off_topic(event, company)
        ][offset : offset + limit]
    else:
        rows = db.execute(ordered.limit(limit).offset(offset)).all()
    events = []
    for event, company in rows:
        # Solo lo persistido en ingesta (F314): recomputar por peticion
        # costaba una evaluacion por noticia y podia divergir de lo
        # persistido. Eventos legacy sin assessment persistido -> nulls
        # honestos (la UI los muestra como N/D).
        persisted = (event.metadata_ or {}).get("assessment") or {}
        events.append(
            {
                "id": event.id,
                "ticker": company.ticker if company else None,
                "date": event.date.isoformat(),
                "title": event.title,
                "original_headline": original_headline(event),
                "headline_translation": display_translation(event),
                "source": event.source,
                "url": event.url,
                "event_type": event.event_type,
                "materiality_score": event.materiality_score,
                "impact_direction": event.impact_direction,
                "requires_update": event.requires_update,
                "date_source": (event.metadata_ or {}).get("date_source"),
                # False solo en titulares de display generados por CavaAI
                # (ausente en filas legacy = titular real de la fuente).
                "headline_from_source": (event.metadata_ or {}).get("headline_from_source", True),
                # Carril macro GDELT (#564): None en eventos de empresa.
                "news_lane": (event.metadata_ or {}).get("news_lane"),
                "macro_theme": (event.metadata_ or {}).get("macro_theme"),
                "source_tier": persisted.get("source_tier"),
                "source_trust_score": persisted.get("source_trust_score"),
                "portfolio_weight": persisted.get("portfolio_weight"),
                "materiality_reasons": persisted.get("materiality_reasons"),
                "source_policy": persisted.get("source_policy"),
                "model_route": persisted.get("model_route"),
            }
        )
    return events


@router.get("/{event_id}/second-order")
def second_order_hypotheses(
    event_id: int,
    use_llm: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    event = db.get(NewsEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Noticia no encontrada")
    return analyze_second_order(db, event, use_llm=use_llm)


@router.post("/{event_id}/translation")
async def translate_news_headline(event_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return await translate_headline(db, event_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Tenant context required") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="News event not found") from exc
