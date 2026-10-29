"""Read-only home inbox: actual thesis changes with an unresolved review."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, NewsEvent, Position, ResearchReview, ThesisChange, WatchItem
from app.services.news_headline_translation import display_translation, original_headline


def pending_thesis_changes(db: Session, limit: int = 100) -> list[dict]:
    watched = select(WatchItem.symbol).where(*tenant_filters(db, WatchItem))
    held = select(Position.company_id).where(Position.quantity > 0, *tenant_filters(db, Position))
    # EXISTS keeps several open reviews of one change from duplicating the item.
    unresolved = select(ResearchReview.id).where(
        ResearchReview.thesis_change_id == ThesisChange.id,
        ResearchReview.company_id == ThesisChange.company_id,
        ResearchReview.status.in_(["open", "in_progress"]),
        *tenant_filters(db, ResearchReview),
    ).exists()
    rows = db.execute(
        select(ThesisChange, Company.ticker)
        .join(Company, Company.id == ThesisChange.company_id)
        .where(
            Company.ticker.in_(watched) | Company.id.in_(held),
            unresolved,
            *tenant_filters(db, ThesisChange),
        )
        .order_by(ThesisChange.created_at.desc(), ThesisChange.id.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    events = _news_events_by_change(db, [change.id for change, _ in rows])
    return [{
        "id": change.id,
        "symbol": ticker,
        "summary": _summary_en_castellano(change, events.get(change.id)),
        "direction": change.impact_direction,
        "createdAt": change.created_at.isoformat(),
    } for change, ticker in rows]


def _news_events_by_change(db: Session, change_ids: list[int]) -> dict[int, NewsEvent]:
    """Evento de noticia origen de cada cambio, por el puente persistido.

    El ThesisChange no enlaza con su NewsEvent; la ResearchReview creada con
    él sí (mismo puente que company_changes_service._project_changes). Solo
    identidad atribuida, nunca similitud."""
    if not change_ids:
        return {}
    review_rows = db.execute(
        select(ResearchReview.thesis_change_id, ResearchReview.news_event_id).where(
            ResearchReview.thesis_change_id.in_(change_ids),
            ResearchReview.news_event_id.is_not(None),
            *tenant_filters(db, ResearchReview),
        )
    ).all()
    event_id_by_change: dict[int, int] = {}
    for change_id, event_id in review_rows:
        event_id_by_change.setdefault(change_id, event_id)
    if not event_id_by_change:
        return {}
    events = {
        event.id: event
        for event in db.scalars(
            select(NewsEvent).where(
                NewsEvent.id.in_(set(event_id_by_change.values())),
                *tenant_filters(db, NewsEvent),
            )
        ).all()
    }
    return {cid: events[eid] for cid, eid in event_id_by_change.items() if eid in events}


def _summary_en_castellano(change: ThesisChange, event: NewsEvent | None) -> str:
    """Summary con el titular en castellano cuando ya existe traducción.

    La plantilla del summary incrusta el titular original verbatim, a menudo
    en inglés («Noticia material que requiere revisión de la tesis: <titular
    EN>. …»), y la tarjeta de Inicio quedaba bilingüe mezclada. Si el evento
    origen tiene traducción cacheada válida y el titular original aparece
    verbatim en el summary, se sustituye por la traducción. Sin evento, sin
    traducción o sin coincidencia exacta el summary se devuelve tal cual:
    nunca se reescribe por similitud ni se traduce nada al vuelo (la caché la
    llena el carril de noticias con su presupuesto)."""
    if event is None:
        return change.summary
    translation = display_translation(event)
    if not isinstance(translation, dict):
        return change.summary
    text = translation.get("text")
    if not isinstance(text, str) or not text.strip():
        return change.summary
    original = original_headline(event).strip().rstrip(".")
    if original and original in change.summary:
        # Sin punto final: la plantilla ya pone «. » tras el titular.
        return change.summary.replace(original, text.strip().rstrip("."))
    return change.summary
