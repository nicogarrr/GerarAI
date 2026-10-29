import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, false, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Company, NewsEvent
from app.schemas import ManualNewsRequest, ManualNewsResponse, NewsIngestRequest, NewsIngestResponse
from app.services.feed_ingestion_service import PRESS_WIRE_SOURCES
from app.services.news_headline_translation import (
    display_summary_translation,
    display_translation,
    original_headline,
    translate_headline,
    translate_summary,
)
from app.services.news_related_tickers import related_for_events
from app.services.news_service import (
    NewsService,
    is_position_change_headline,
    is_viewer_link_only,
    position_change_cluster_title,
)
from app.services.news_story_cluster import (
    StoryGroup,
    absorb,
    event_signature,
    exact_key,
    find_group,
)
from app.services.public_headline_translation import translate_external_headline
from app.services.second_order_news_service import analyze_second_order
from app.services.ticker_news_lane import (
    _only_ticker_prefix_mention,
    fails_strict_name,
    is_law_firm_solicitation,
)

logger = logging.getLogger(__name__)

router = APIRouter()

class ExternalHeadlineRequest(BaseModel):
    headline: str = Field(min_length=3, max_length=500)

@router.post("/translate-headline")
async def translate_external(payload: ExternalHeadlineRequest, db: Session = Depends(get_db)) -> dict:
    return await translate_external_headline(db, payload.headline)


_SCAN_CHUNK = 200
_SCAN_LIMIT = 2000


def _is_off_topic(event: NewsEvent, company: Company | None) -> bool:
    metadata = event.metadata_ or {}
    if company is None or not metadata.get("headline_from_source", True):
        return False
    if fails_strict_name(company, f"{event.title or ''} {event.summary or ''}"):
        return True
    return _only_ticker_prefix_mention(company, event.title or "", event.summary or "")


@router.post("/manual", response_model=ManualNewsResponse)
def manual_news(payload: ManualNewsRequest, db: Session = Depends(get_db)) -> ManualNewsResponse:
    return NewsService().analyze_manual_news(db, payload.text, payload.source, payload.url)


@router.post("/ingest", response_model=NewsIngestResponse)
def ingest_news(payload: NewsIngestRequest, db: Session = Depends(get_db)) -> NewsIngestResponse:
    return NewsService().ingest_news_items(db, payload.items, payload.source)


def _related_tickers_for_rows(db: Session, rows: list, clusters: dict, story_groups: list) -> dict[int, list[dict]]:
    """Relacionados por evento visible. Nunca rompe el feed: ante un error se
    omite la tira (el dato es complementario)."""
    items: list[tuple[int, object, str]] = []
    for item in rows:
        if isinstance(item[0], str) and item[0] == "cluster":
            continue  # titular 13F agrupado: boilerplate, sin tira
        if isinstance(item[0], str) and item[0] == "story":
            event, company = story_groups[item[1]].event, story_groups[item[1]].company
        else:
            event, company = item
        items.append((event.id, company, f"{original_headline(event)} {event.summary or ''}"))
    try:
        return related_for_events(db, items)
    except Exception:  # noqa: BLE001 - complemento: no tumba el feed
        logger.warning("related_tickers fallo; feed sin tira", exc_info=True)
        return {}


@router.get("")
def news_events(
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    lane: Literal["empresa", "macro", "gobierno"] | None = None,
    ticker: Annotated[str | None, Query(max_length=20)] = None,
    tickers: Annotated[str | None, Query(max_length=1000)] = None,
) -> list[dict]:
    """Eventos por pagina (scroll infinito). ``lane`` filtra en SQL:
    ``empresa`` = atribuido a una empresa real; ``macro`` = carril macro GDELT;
    ``gobierno`` = fuentes oficiales (Fed, BCE, Casa Blanca...).
    ``ticker`` limita a los eventos de esa empresa (ficha de accion).
    Las filas etiquetadas con un ticker que no citan a la empresa se omiten.
    En portada (sin ``ticker``) la misma historia publicada por varios medios
    se agrupa en la fila mas reciente: ``coverage_count``/``coverage`` declaran
    las fuentes absorbidas (regla determinista, ver news_story_cluster).
    ``tickers`` (csv, max 50) limita a esas empresas: carril «Para ti»
    (cartera + watchlist del usuario, que el cliente ya conoce)."""
    stmt = select(NewsEvent, Company).outerjoin(Company, NewsEvent.company_id == Company.id)
    # Retired social stream: preserve stored rows but never serve them as news.
    retired_lane = NewsEvent.metadata_["news_lane"].as_string()
    stmt = stmt.where((retired_lane.is_(None)) | (retired_lane != "social"))
    if ticker:
        stmt = stmt.where(Company.ticker == ticker.strip().upper())
    elif tickers:
        # Carril «Para ti»: el cliente manda los tickers de su cartera y
        # watchlist (los conoce él; el backend no tiene la watchlist). Lista
        # acotada y saneada; los eventos sin empresa (macro) no aplican.
        wanted = [
            token.strip().upper()
            for token in tickers.split(",")
            if 0 < len(token.strip()) <= 20 and token.strip().replace(".", "").isalnum()
        ][:50]
        stmt = stmt.where(Company.ticker.in_(wanted)) if wanted else stmt.where(false())
    if lane == "empresa":
        stmt = stmt.where(NewsEvent.company_id.is_not(None))
    elif lane == "gobierno":
        # Fuentes oficiales RSS, sin empresa.
        stmt = stmt.where(NewsEvent.metadata_["news_lane"].as_string() == lane)
    elif lane == "macro":
        stmt = stmt.where(NewsEvent.metadata_["news_lane"].as_string() == "macro")
        # Frescura: el carril se refresca cada hora (macro_news_refresh); un
        # titular macro de más de 72 h ya no es contexto actual y ensuciaba el
        # carril. Solo lectura: las filas no se borran.
        macro_cutoff = datetime.now(UTC) - timedelta(hours=72)
        stmt = stmt.where(NewsEvent.date >= macro_cutoff)
    ordered = stmt.order_by(desc(NewsEvent.date), desc(NewsEvent.id))
    # Lectura: se ocultan filas etiquetadas con un ticker cuyo titular y resumen
    # no citan a la empresa (ticker pegado delante, nada mas). Criterio sin LLM;
    # las filas no se borran. El offset cuenta filas visibles.
    rows: list = []
    skipped = 0
    scanned = 0
    # Agrupación de titulares 13F (boilerplate de MarketBeat y agregadores):
    # una fila visible por empresa y día con recuento, representada por el
    # primer evento del grupo. En la ficha de empresa se muestran sin agrupar.
    clusters: dict[tuple, dict] = {}
    story_groups: list[StoryGroup] = []
    while len(rows) < limit and scanned < _SCAN_LIMIT:
        chunk = db.execute(ordered.limit(_SCAN_CHUNK).offset(scanned)).all()
        if not chunk:
            break
        scanned += len(chunk)
        for event, company in chunk:
            if _is_off_topic(event, company):
                continue
            # Filas legacy sin contenido (titular y resumen = enlace del visor):
            # no se borran, no se muestran.
            if is_viewer_link_only(event.title, event.summary):
                continue
            item = None
            if ticker is None:
                # Portada (sin filtro de empresa): fuera el spam legal de
                # bufetes ("SHAREHOLDER ALERT"...) y los titulares literales
                # repetidos. En la ficha de una empresa se muestra todo lo
                # de esa empresa, incluidas las solicitudes de bufetes.
                if is_law_firm_solicitation(original_headline(event), event.summary):
                    continue
                # Nota de prensa de agencia sin empresa detectada y fuera del
                # carril macro: anuncios de producto/lifestyle que inundaban
                # «Todas» (medido en prod 19-oct-2026: 24/30 de agencia,
                # 23/30 sin empresa). Solo portada; las filas no se borran y
                # cualquier evento con empresa detectada sigue entrando.
                if (
                    company is None
                    and (event.metadata_ or {}).get("news_lane") != "macro"
                    and (event.source or "") in PRESS_WIRE_SOURCES
                ):
                    continue
                headline = original_headline(event)
                if is_position_change_headline(headline):
                    key = (company.id if company else None, event.date.date())
                    cluster = clusters.get(key)
                    if cluster is None:
                        clusters[key] = {"event": event, "company": company, "count": 1}
                        item = ("cluster", key)
                    else:
                        cluster["count"] += 1
                elif (event.metadata_ or {}).get("news_lane") == "social":
                    # Conversación social sin verificar: nunca entra en los
                    # clústeres de historia ni en el recuento «N fuentes».
                    item = (event, company)
                else:
                    # Misma historia reescrita por otro medio (o traducida): se
                    # agrupa en la fila más reciente y queda como cobertura
                    # («N fuentes») en vez de repetirse en portada. La dedup
                    # literal queda absorbida por la firma (Jaccard 1.0).
                    sig = event_signature(event, company)
                    group = find_group(story_groups, event, company, sig)
                    if group is not None:
                        absorb(group, event)
                        continue
                    story_groups.append(
                        StoryGroup(
                            event=event,
                            company=company,
                            signature=sig,
                            text_key=exact_key(original_headline(event)),
                        )
                    )
                    item = ("story", len(story_groups) - 1)
            else:
                item = (event, company)
            if item is None:
                continue
            if skipped < offset:
                skipped += 1
            elif len(rows) < limit:
                rows.append(item)
        if len(chunk) < _SCAN_CHUNK:
            break
    events = []
    related_by_event = _related_tickers_for_rows(db, rows, clusters, story_groups)
    for item in rows:
        cluster_count = 0
        story_coverage: list[dict] = []
        if isinstance(item[0], str) and item[0] == "cluster":
            cluster = clusters[item[1]]
            event, company = cluster["event"], cluster["company"]
            cluster_count = cluster["count"]
        elif isinstance(item[0], str) and item[0] == "story":
            group = story_groups[item[1]]
            event, company = group.event, group.company
            story_coverage = group.coverage
        else:
            event, company = item
        clustered = cluster_count > 1
        # Solo lo persistido en ingesta (F314): recomputar por peticion
        # costaba una evaluacion por noticia y podia divergir de lo
        # persistido. Eventos legacy sin assessment persistido -> nulls
        # honestos (la UI los muestra como N/D).
        persisted = (event.metadata_ or {}).get("assessment") or {}
        # Legacy rows predate the ingestion solicitation filter. A deterministic
        # read projection marks recruitment noise without rewriting provenance.
        solicitation = is_law_firm_solicitation(original_headline(event), event.summary)
        events.append(
            {
                "id": event.id,
                "ticker": company.ticker if company else None,
                "date": event.date.isoformat(),
                "title": (
                    position_change_cluster_title(
                        company.ticker if company else None, event.source, cluster_count
                    )
                    if clustered
                    else event.title
                ),
                "original_headline": original_headline(event),
                "headline_translation": display_translation(event),
                # Resumen/cuerpo ingerido con su traduccion cacheada (Nico:
                # traducir cada noticia desde la ficha y el feed).
                "summary": event.summary,
                "summary_translation": display_summary_translation(event),
                "source": event.source,
                "url": event.url,
                "event_type": "legal_solicitation" if solicitation else event.event_type,
                "materiality_score": 1 if solicitation else event.materiality_score,
                "impact_direction": event.impact_direction,
                "requires_update": False if solicitation else event.requires_update,
                "date_source": (event.metadata_ or {}).get("date_source"),
                # False solo en titulares de display generados por GerarAI
                # (ausente en filas legacy = titular real de la fuente).
                "headline_from_source": (
                    False
                    if clustered
                    else (event.metadata_ or {}).get("headline_from_source", True)
                ),
                "cluster_count": cluster_count if clustered else None,
                # Misma historia en otros medios, agrupada (portada). La fila
                # representante es la más reciente; coverage lista fuente/URL
                # absorbidas, en orden de llegada (más reciente primero).
                "coverage_count": len(story_coverage) + 1 if story_coverage else None,
                "coverage": story_coverage or None,
                # Carril macro GDELT (#564): None en eventos de empresa.
                "news_lane": (event.metadata_ or {}).get("news_lane"),
                "macro_theme": (event.metadata_ or {}).get("macro_theme"),
                "source_tier": persisted.get("source_tier"),
                "source_trust_score": persisted.get("source_trust_score"),
                "portfolio_weight": persisted.get("portfolio_weight"),
                "materiality_reasons": persisted.get("materiality_reasons"),
                "source_policy": persisted.get("source_policy"),
                "model_route": persisted.get("model_route"),
                # Tira de tickers relacionados (solo evidencia explicita en el
                # texto) con ultimo cierre y variacion; ausente si no hay.
                "related_tickers": related_by_event.get(event.id) or None,
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


@router.post("/{event_id}/translation/summary")
async def translate_news_summary(event_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return await translate_summary(db, event_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Tenant context required") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="News event not found") from exc
