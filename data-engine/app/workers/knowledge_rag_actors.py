"""Actor Dramatiq de ingesta del RAG de conocimiento.

Modulo propio para no tocar dramatiq_app.py mas
de una linea. Registrado con ``import app.workers.knowledge_rag_actors`` en
dramatiq_app.py: sin ese import el actor se despacha pero nadie lo consume.

Cola dedicada ``knowledge``: Docling es pesado en RAM/CPU y no debe competir con
las colas default/kpis/theses. El worker que la consuma debe arrancarse con
``dramatiq app.workers.dramatiq_app --queues knowledge`` (ver docs/knowledge-rag.md).
"""

from __future__ import annotations

from typing import Any

import dramatiq

from app.services.knowledge_rag.runtime import INGEST_TIME_LIMIT_MS
from app.workers.dramatiq_app import _handle_actor_error, _session
from app.workers.dramatiq_app import broker as _broker  # noqa: F401

KNOWLEDGE_QUEUE_NAME = "knowledge"


@dramatiq.actor(max_retries=2, min_backoff=60_000, queue_name=KNOWLEDGE_QUEUE_NAME, time_limit=INGEST_TIME_LIMIT_MS)
def ingest_knowledge_source(
    source_id: int,
    *,
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Indexa una fuente ya registrada (checksum ya deduplicado por la API)."""
    from app.core.config import get_settings
    from app.services.knowledge_rag.jobs import run_ingest_job

    db = _session(tenant_id, user_id)
    try:
        return run_ingest_job(db, source_id, get_settings())
    except Exception as exc:
        # run_ingest_job ya dejo la fuente en failed; transitorio -> dramatiq reintenta.
        return _handle_actor_error("ingest_knowledge_source", exc, source_id=source_id)
    finally:
        db.close()
