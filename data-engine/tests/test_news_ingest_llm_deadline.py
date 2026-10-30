"""Deadline de presupuesto LLM/Jev propagado a la ingesta de noticias.

Prod (2026-10-29 22:07 UTC): refresh_rss_feeds murio con TimeLimitExceeded a
los 601,8 s DENTRO de un gate Jev (credit_status con la BD lenta) en mitad de
un lote; el reintento de dramatiq repitio el barrido. Con el deadline
propagado (actor -> ingest_news_result -> ingest_news_items -> _analyze_news),
agotado el presupuesto los items se ingieren con el analisis determinista y se
omite SOLO el enriquecimiento Jev/LLM - el mismo resultado degradado que
"sin key/fallo de Jev", que ya es el contrato best-effort de los gates.
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import NewsEvent
from app.schemas import NewsFeedItem
from app.services import jev_gates, jev_triage_service
from app.services.news_service import NewsService


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _item(i: int) -> NewsFeedItem:
    return NewsFeedItem(
        title=f"Resultados trimestrales de ACME {i}",
        text="ACME publica resultados con crecimiento de ingresos del 12%.",
        ticker=None,
        url=f"https://news.example/acme-{i}",
        source="rss",
        published_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
        headline_from_source=True,
    )


def _ingest(db, items, **kwargs):
    try:
        return NewsService().ingest_news_items(
            db, items, default_source="rss", connector="rss", **kwargs
        )
    except TypeError as exc:
        pytest.fail(f"ingest_news_items no acepta el deadline propagado: {exc}")


@pytest.fixture
def jev_spies(monkeypatch):
    calls = {"news_action": 0, "doc_type": 0}

    def fake_news_action(text):
        calls["news_action"] += 1
        return None

    def fake_doc_type(text):
        calls["doc_type"] += 1
        return None

    monkeypatch.setattr(jev_gates, "jev_news_action_sync", fake_news_action)
    monkeypatch.setattr(jev_triage_service, "classify_doc_type_sync", fake_doc_type)
    return calls


def test_deadline_exceeded_skips_jev_enrichment_but_ingests(jev_spies):
    engine = _db()
    with Session(engine) as db:
        response = _ingest(db, [_item(1)], llm_deadline=0.0)  # 0 <= monotonic(): agotado
        assert response.created == 1  # la noticia se ingiere igual (dato verdadero)
        assert jev_spies == {"news_action": 0, "doc_type": 0}  # cero llamadas Jev/LLM
        assert db.scalar(select(NewsEvent)) is not None


def test_deadline_in_future_keeps_jev_gates(jev_spies):
    import time as _time

    engine = _db()
    with Session(engine) as db:
        response = _ingest(db, [_item(2)], llm_deadline=_time.monotonic() + 3600)
        assert response.created == 1
        assert jev_spies == {"news_action": 1, "doc_type": 1}


def test_without_deadline_keeps_jev_gates(jev_spies):
    engine = _db()
    with Session(engine) as db:
        response = _ingest(db, [_item(3)])
        assert response.created == 1
        assert jev_spies == {"news_action": 1, "doc_type": 1}
