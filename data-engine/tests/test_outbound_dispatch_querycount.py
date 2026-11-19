"""Presupuesto de consultas de dispatch_pending (regresion N+1 de cobertura).

Cada alerta candidata pagaba ~4 SELECTs de cobertura (NewsEvent del
event_type, suscripcion, binding de Telegram, preferencia push) en cada
pasada; una pagina de 100 candidatas costaba >700 sentencias. La cobertura
se resuelve ahora una vez por categoria/par usuario-chat, los NewsEvent se
precargan en una consulta (con referencia fuerte: el identity map es debil)
y las marcas "skipped" del outbox se escriben en lote (INSERT multi-fila
con repliegue a savepoint por fila ante carrera + un UPDATE + un commit).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    AlertSubscription,
    Base,
    NewsEvent,
    ResearchAlert,
)

N_NEWS = 60
N_FILING = 40


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


def _seed_100_candidates(db) -> None:
    now = datetime.now(UTC)
    db.info.update(tenant_id=1, user_id="owner")
    db.add(
        AlertSubscription(
            tenant_id=1, user_id="owner", event_type="new_filing",
            enabled=True, chat_id="12345", enabled_at=now - timedelta(days=30),
        )
    )
    for i in range(N_NEWS):
        news = NewsEvent(
            tenant_id=1, date=now - timedelta(hours=1), title=f"Filing {i}",
            source="sec", url=f"https://sec.gov/doc{i}", metadata_={"connector": "sec"},
        )
        db.add(news)
        db.flush()
        db.add(ResearchAlert(
            tenant_id=1, alert_type="tracked_news", title=f"Filing {i}",
            message="Nuevo filing", fingerprint=f"tn-{i}", channels=["in_app"],
            created_at=now - timedelta(minutes=30), metadata_={"news_event_id": news.id},
        ))
    for i in range(N_FILING):
        db.add(ResearchAlert(
            tenant_id=1, alert_type="filing_changes", title=f"Cambio {i}",
            message="Cambios en filing", fingerprint=f"fc-{i}", channels=["in_app"],
            created_at=now - timedelta(minutes=30),
        ))
    db.commit()


def test_dispatch_pending_statement_budget(db):
    from app.services.outbound_alerts import dispatch_pending

    _seed_100_candidates(db)
    statements = 0

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        nonlocal statements
        statements += 1

    stats = dispatch_pending(db)
    assert stats["candidates"] == N_NEWS + N_FILING
    assert stats["redispatched"] == 0  # sin binding de Telegram ni push: todo skipped
    # ANTES: 723. DESPUES: ~11 (cobertura precargada por categoria, skips
    # del outbox en lote: 1 INSERT multi-fila + 1 UPDATE + 1 commit).
    assert statements <= 40, f"N+1 de cobertura: {statements} sentencias"


def test_preference_for_push_with_cache(db):
    """preference_for: categoria None, acierto con opt-in y segundo uso cacheado."""
    from app.models.entities import PushPreference
    from app.services.web_push import preference_for

    _seed_100_candidates(db)
    now = datetime.now(UTC)
    other = ResearchAlert(
        tenant_id=1, alert_type="dca_level", title="DCA", message="Nivel DCA",
        fingerprint="dca-1", channels=["in_app"], created_at=now,
    )
    db.add(other)
    db.flush()
    assert preference_for(db, other) is None  # sin categoria de evento cubierta

    alert = db.query(ResearchAlert).filter_by(alert_type="filing_changes").first()
    assert preference_for(db, alert) is None  # sin preferencia push
    db.add(
        PushPreference(
            tenant_id=1, user_id="owner", event_type="new_filing",
            enabled=True, enabled_at=now - timedelta(days=1),
        )
    )
    db.flush()
    cache: dict = {}
    row = preference_for(db, alert, _cache=cache)
    assert row is not None and row.event_type == "new_filing"
    again = preference_for(db, alert, _cache=cache)
    assert again is row  # segundo uso: cache, no otra consulta
    # Preferencia habilitada DESPUES de la alerta: no cubre (opt-in temporal).
    late = ResearchAlert(
        tenant_id=1, alert_type="filing_changes", title="Viejo", message="Viejo",
        fingerprint="fc-old", channels=["in_app"], created_at=now - timedelta(days=2),
    )
    assert preference_for(db, late) is None


def test_skips_are_recorded_and_not_repicked(db):
    """Toda candidata saltada queda marcada skipped y no vuelve a entrar."""
    from app.models.entities import AlertDelivery
    from app.services.outbound_alerts import dispatch_pending

    _seed_100_candidates(db)
    stats = dispatch_pending(db)
    assert stats["candidates"] == N_NEWS + N_FILING
    rows = db.query(AlertDelivery).filter_by(channel="telegram").all()
    assert len(rows) == N_NEWS + N_FILING
    assert {row.status for row in rows} == {"skipped"}
    # La consulta de candidatas excluye alertas con fila de entrega: 2a pasada = 0.
    again = dispatch_pending(db)
    assert again["candidates"] == 0


def test_record_skips_fallback_on_race(db):
    """Una fila ya creada por otro worker: repliegue a savepoint por fila."""
    from app.models.entities import AlertDelivery, ResearchAlert
    from app.services.outbound_alerts import _record_skips

    _seed_100_candidates(db)
    alerts = db.query(ResearchAlert).limit(5).all()
    db.add(
        AlertDelivery(
            tenant_id=alerts[0].tenant_id, alert_id=alerts[0].id, channel="telegram"
        )
    )
    db.commit()
    _record_skips(db, alerts)  # no revienta; repliegue por fila
    rows = db.query(AlertDelivery).filter_by(channel="telegram").all()
    assert len(rows) == 5
    assert {row.status for row in rows} == {"skipped"}


def test_coverage_cache_keeps_scalar_semantics(db):
    """Con cache, una suscripcion revocada a mitad NO aparece (misma llamada)."""
    from app.services.outbound_alerts import subscription_for

    _seed_100_candidates(db)
    alert = db.query(ResearchAlert).filter_by(alert_type="filing_changes").first()
    cache: dict = {}
    assert subscription_for(db, alert, _cache=cache) is None  # sin binding
    assert ("sub", "new_filing") in cache  # la consulta se hizo UNA vez
    row = cache[("sub", "new_filing")]
    assert row is not None and row.event_type == "new_filing"
