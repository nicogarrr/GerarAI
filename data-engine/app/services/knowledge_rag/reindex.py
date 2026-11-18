"""Reindex masivo de la biblioteca de conocimiento (coleccion Qdrant).

Caso de uso: reconstruir la coleccion tras perder el volumen de Qdrant (o tras
cambiar el modelo de embeddings). Re-encola CADA fuente candidata al actor
``ingest_knowledge_source`` (cola ``knowledge``), que vuelve a extraer,
trocear, embeber (fastembed local: coste 0 EUR, solo CPU) y subir a Qdrant con
la logica idempotente de ``index_source`` (limpia lo parcial antes de grabar).

CONTRATO REAL DEL ACTOR (dramatiq_app._session, usado por el flujo normal via
``routes.knowledge_rag._dispatch``): toda entrega necesita ``tenant_id`` no
nulo de un tenant activo y ``user_id`` no vacio; si no, ``_session`` lanza
ValueError ANTES de abrir BD y la entrega muere como error permanente. En el
flujo API ambos salen de ``db.info`` (el principal autenticado); el modelo
KnowledgeRagSource NO guarda que usuario subio cada fuente, asi que el
operador lo aporta al lanzar el reindex.

Por eso cada fuente se encola con el tenant QUE LA POSEE: la sesion del actor
filtra por ``tenant_id == <tenant de la sesion>`` (with_loader_criteria en
database.py) y una fuente despachada bajo otro tenant seria INVISIBLE para el
job ("source not found"). Las fuentes GLOBALES (tenant_id NULL) no tienen
contexto de despacho valido bajo ese contrato: se SALTAN y se reportan, no se
encolan a ciegas.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_rag import (
    SOURCE_STATUS_FAILED,
    SOURCE_STATUS_INDEXED,
    KnowledgeRagSource,
)

#: Estados que el reindex masivo toca por defecto: solo lo que consta como
#: bien indexado. ``queued``/``processing`` son trabajo EN VUELO del pipeline
#: (reencolarlos duplicaria entregas del actor); ``failed`` solo a peticion.
DEFAULT_STATUSES: tuple[str, ...] = (SOURCE_STATUS_INDEXED,)

#: Firma del ``send`` del actor: ingest_knowledge_source.send(source_id,
#: tenant_id=..., user_id=...). Inyectable en tests.
SendFn = Callable[..., object]


@dataclass
class EnqueueError:
    source_id: int
    detail: str


@dataclass
class ReindexResult:
    candidates: int = 0
    enqueued: int = 0
    errors: list[EnqueueError] = field(default_factory=list)
    #: Fuentes globales (tenant_id NULL) no encoladas: el actor no admite un
    #: despacho sin tenant y bajo otro tenant serian invisibles para el job.
    skipped_no_tenant: list[int] = field(default_factory=list)


def select_candidates(
    db: Session,
    *,
    tenant_id: int | None = None,
    include_failed: bool = False,
    limit: int | None = None,
    source_ids: tuple[int, ...] = (),
) -> list[KnowledgeRagSource]:
    """Fuentes a re-encolar, ordenadas por id (determinista).

    ``source_ids`` explicitos prescinden del filtro de estado: el operador
    sabe que fuente quiere re-lanzar (p.ej. una ``processing`` abandonada).
    Sin ``source_ids`` se filtra por estado: ``indexed`` siempre y ``failed``
    solo con ``include_failed``. ``tenant_id=None`` no filtra por tenant
    (incluye las fuentes globales, cuyo tenant_id es NULL).
    """
    stmt = select(KnowledgeRagSource)
    if source_ids:
        stmt = stmt.where(KnowledgeRagSource.id.in_(source_ids))
    else:
        statuses = DEFAULT_STATUSES + ((SOURCE_STATUS_FAILED,) if include_failed else ())
        stmt = stmt.where(KnowledgeRagSource.status.in_(statuses))
    if tenant_id is not None:
        stmt = stmt.where(KnowledgeRagSource.tenant_id == tenant_id)
    stmt = stmt.order_by(KnowledgeRagSource.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def enqueue_sources(
    sources: list[KnowledgeRagSource],
    send: SendFn,
    *,
    user_id: str,
    sleep_s: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> ReindexResult:
    """Encola cada fuente con el tenant que la posee; un fallo no detiene el lote.

    ``user_id`` es obligatorio porque el actor abre sesion con
    ``_session(tenant_id, user_id)`` y rechaza entregas sin usuario: sin esta
    validacion todo contaria como encolado y el actor rechazaria cada ingesta.
    Las fuentes globales (tenant_id NULL) se saltan y se reportan en
    ``skipped_no_tenant`` (ver docstring del modulo).

    ``sleep_s`` > 0 espacia los envios para no inundar Redis en bibliotecas
    grandes; no duerme tras el ultimo item.
    """
    if not user_id:
        raise ValueError(
            "user_id es obligatorio: el actor rechaza entregas sin usuario "
            "(dramatiq_app._session exige tenant_id y user_id)"
        )
    result = ReindexResult(candidates=len(sources))
    for index, source in enumerate(sources):
        if source.tenant_id is None:
            result.skipped_no_tenant.append(source.id)
        else:
            try:
                outcome = send(source.id, tenant_id=source.tenant_id, user_id=user_id)
            except Exception as exc:  # noqa: BLE001 - el lote continua pese al fallo
                result.errors.append(
                    EnqueueError(source.id, f"{type(exc).__name__}: {exc}"[:500])
                )
            else:
                # Un send asincrono devuelve el mensaje encolado; un sender
                # sincrono (actor.fn, smoke tests) devuelve el dict del job:
                # un status error/failed ES un fallo aunque nadie haya lanzado.
                status = outcome.get("status") if isinstance(outcome, dict) else None
                if status in ("error", "failed"):
                    detail = outcome.get("error") or outcome
                    result.errors.append(
                        EnqueueError(source.id, f"status={status}: {detail}"[:500])
                    )
                else:
                    result.enqueued += 1
        if sleep_s > 0 and index < len(sources) - 1:
            sleep(sleep_s)
    return result
