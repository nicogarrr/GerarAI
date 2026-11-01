"""Que ha cambiado en una empresa desde la ultima visita del usuario.

Solo lee lo que ya esta guardado (documentos, hechos y cambios de tesis con su
``created_at``). No infiere nada: cuenta y lista. La fecha de "ultima visita"
la aporta el cliente (``since``); aqui no se guarda estado.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Document, FinancialFact, NewsEvent, ResearchReview, ThesisChange
from app.services.news_headline_translation import display_translation, original_headline
from app.services.thesis_change_identity import ChangeItem, group_change_items

MAX_ITEMS = 8


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def changes_since(db: Session, company_id: int, since: datetime) -> dict[str, Any]:
    since = _aware(since)
    docs = (
        db.execute(
            select(Document)
            .where(Document.company_id == company_id, Document.created_at > since)
            .order_by(Document.created_at.desc())
            .limit(MAX_ITEMS)
        )
        .scalars()
        .all()
    )
    docs_total = (
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.company_id == company_id,
                Document.created_at > since,
                *tenant_filters(db, Document),
            )
        )
        or 0
    )
    fact_rows = db.execute(
        select(FinancialFact.metric, func.count())
        .where(
            FinancialFact.company_id == company_id,
            FinancialFact.created_at > since,
            *tenant_filters(db, FinancialFact),
        )
        .group_by(FinancialFact.metric)
        .order_by(func.count().desc(), FinancialFact.metric)
        .limit(MAX_ITEMS)
    ).all()
    facts_total = (
        db.scalar(
            select(func.count())
            .select_from(FinancialFact)
            .where(
                FinancialFact.company_id == company_id,
                FinancialFact.created_at > since,
                *tenant_filters(db, FinancialFact),
            )
        )
        or 0
    )
    changes = (
        db.execute(
            select(ThesisChange)
            .where(ThesisChange.company_id == company_id, ThesisChange.created_at > since)
            .order_by(ThesisChange.created_at.desc())
            .limit(MAX_ITEMS)
        )
        .scalars()
        .all()
    )
    return {
        "since": since.isoformat(),
        "documentos": {
            "total": docs_total,
            "items": [
                {
                    "titulo": d.title,
                    "tipo": d.source_type,
                    "url": d.source_url,
                    "fecha": d.published_at.date().isoformat() if d.published_at else None,
                }
                for d in docs
            ],
        },
        "hechos": {
            "total": facts_total,
            "por_metrica": [{"metric": metric, "n": n} for metric, n in fact_rows],
        },
        "cambios_tesis": _project_changes(db, changes),
        # «Qué ha cambiado» (idea Jera Value): valor anterior → nuevo por métrica, de los hechos ya guardados.
        "cambios_metricas": _metric_changes(db, company_id, since, [metric for metric, _n in fact_rows]),
    }


def _fact_value(fact: FinancialFact) -> dict[str, Any]:
    return {
        "valor": float(fact.value),
        "periodo": fact.period,
        "fecha": fact.created_at.isoformat() if fact.created_at else None,
    }


def _metric_changes(
    db: Session, company_id: int, since: datetime, metrics: list[str]
) -> list[dict[str, Any]]:
    """Por métrica: el último dato guardado después de ``since`` y el que había antes.

    Si antes existía el mismo periodo, ese es el anterior (una revisión); si no, el último
    periodo que ya conocías. Sin dato previo, ``anterior`` es None (dato nuevo, no un cambio).
    """
    if not metrics:
        return []
    # Dos consultas en total (no 1+2 por metrica): una para los datos nuevos y
    # otra para el historico de solo esas metricas. El top-1 por metrica con
    # desempate por id se reproduce en Python sobre el mismo ORDER BY, asi la
    # salida es identica (medido: 40 metricas = 121 -> 2 consultas).
    order = (FinancialFact.created_at.desc(), FinancialFact.id.desc())
    new_rows = db.execute(
        select(
            FinancialFact.metric,
            FinancialFact.period,
            FinancialFact.value,
            FinancialFact.unit,
            FinancialFact.created_at,
            FinancialFact.source_type,
            FinancialFact.accession_number,
        )
        .where(
            FinancialFact.company_id == company_id,
            FinancialFact.metric.in_(metrics),
            FinancialFact.created_at > since,
            *tenant_filters(db, FinancialFact),
        )
        .order_by(FinancialFact.metric, *order)
    ).all()
    new_by_metric: dict[str, Any] = {}
    for row in new_rows:
        new_by_metric.setdefault(row.metric, row)  # primera = top-1 de su metrica
    if not new_by_metric:
        return []
    old_rows = db.execute(
        select(
            FinancialFact.metric,
            FinancialFact.period,
            FinancialFact.value,
            FinancialFact.unit,
            FinancialFact.created_at,
        )
        .where(
            FinancialFact.company_id == company_id,
            FinancialFact.metric.in_(list(new_by_metric)),
            FinancialFact.created_at <= since,
            *tenant_filters(db, FinancialFact),
        )
        .order_by(FinancialFact.metric, *order)
    ).all()
    history: dict[str, list[Any]] = {}
    for row in old_rows:
        history.setdefault(row.metric, []).append(row)
    out: list[dict[str, Any]] = []
    for metric in metrics:
        new = new_by_metric.get(metric)
        if new is None:
            continue
        hist = history.get(metric, [])
        # Mismo criterio que antes: revision del mismo periodo si existe
        # (primera en el orden), si no el ultimo dato conocido.
        old = next((r for r in hist if r.period == new.period), None) or (hist[0] if hist else None)
        out.append(
            {
                "metric": metric,
                "unidad": new.unit,
                "anterior": _fact_value(old) if old is not None else None,
                "nuevo": _fact_value(new),
                "fuente": new.source_type,
                "accession": new.accession_number,
            }
        )
    return out


def _project_changes(db: Session, changes: list[ThesisChange]) -> list[dict[str, Any]]:
    """Proyección de presentación con identidad atribuida del evento origen.

    El ThesisChange no enlaza con su NewsEvent; la ResearchReview creada con
    él sí. Por ese puente se recuperan URL, titular original y traducción
    cacheada del evento y se agrupa el mismo cambio publicado en dos idiomas
    (QA ASTS 21-oct-2026: el par ES/EN de TradingView salía dos veces en
    «Desde tu última visita»). Solo identidad atribuida, nunca similitud;
    las fuentes absorbidas quedan en ``tambien_en`` con su URL revisable.
    Sin puente (cambios antiguos o sin evento) el cambio se muestra tal cual.
    """
    if not changes:
        return []
    review_rows = db.execute(
        select(ResearchReview.thesis_change_id, ResearchReview.news_event_id).where(
            ResearchReview.thesis_change_id.in_([c.id for c in changes]),
            ResearchReview.news_event_id.is_not(None),
            *tenant_filters(db, ResearchReview),
        )
    ).all()
    event_id_by_change: dict[int, int] = {}
    for change_id, event_id in review_rows:
        event_id_by_change.setdefault(change_id, event_id)
    event_ids = set(event_id_by_change.values())
    events = (
        {e.id: e for e in db.scalars(select(NewsEvent).where(NewsEvent.id.in_(event_ids))).all()}
        if event_ids
        else {}
    )
    items: list[ChangeItem] = []
    for orden, change in enumerate(changes):
        event = events.get(event_id_by_change.get(change.id))
        translation = display_translation(event) if event is not None else None
        items.append(
            ChangeItem(
                resumen=change.summary,
                direccion=change.impact_direction,
                requiere_revision=bool(change.requires_review),
                fecha=_aware(change.created_at).date().isoformat(),
                orden=orden,
                news_event_id=event.id if event is not None else None,
                fuente_url=event.url if event is not None else None,
                fuente_nombre=event.source if event is not None else None,
                titular_original=original_headline(event) if event is not None else None,
                traduccion_titular=(
                    translation["text"]
                    if isinstance(translation, dict) and isinstance(translation.get("text"), str)
                    else None
                ),
            )
        )
    return [
        {
            "resumen": item.resumen,
            "direccion": item.direccion,
            "requiere_revision": item.requiere_revision,
            "fecha": item.fecha,
            "fuente_url": item.fuente_url,
            "fuente_nombre": item.fuente_nombre,
            "tambien_en": item.tambien_en or None,
        }
        for item in group_change_items(items)
    ]
