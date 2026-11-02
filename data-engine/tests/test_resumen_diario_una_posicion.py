"""Resumen diario con una sola posición: singular, no «1 posiciones».

Con una única posición el aviso decía «1 de 1 posiciones con variacion» o
«1 posiciones seguidas, sin datos de cierre» (en inglés «1 positions»).
"""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.models import PortfolioMoveDigest, Tenant
from app.models.entities import Base
from app.services.daily_digest_alerts import emit_digest_alert

AS_OF = date(2026, 10, 9)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id="owner"))
        db.commit()
        db.info.update(tenant_id=1, user_id="owner")
        yield db
    engine.dispose()


def _emit(db, items):
    row = PortfolioMoveDigest(tenant_id=1, digest_date=AS_OF, version="test-v1", input_hash="abc",
                              items=items, coverage="complete",
                              generated_at=datetime(2026, 10, 10, 5, 15, tzinfo=UTC))
    db.add(row)
    db.commit()
    return emit_digest_alert(db, row, AS_OF)


def test_one_position_moved_is_singular(db):
    alert = _emit(db, [{"ticker": "ASTS", "status": "disponible", "price_change_pct": 2.5}])
    assert alert.message.startswith("1 de 1 posición con variación: ASTS +2,50 %.")


def test_one_position_without_close_is_singular(db):
    alert = _emit(db, [{"ticker": "ASTS", "status": "sin datos"}])
    assert alert.message.startswith("1 posición seguida, sin datos de cierre para el 9 oct 2026")


def test_two_positions_stay_plural(db):
    alert = _emit(db, [{"ticker": "ASTS", "status": "sin datos"}, {"ticker": "NBIS", "status": "sin datos"}])
    assert alert.message.startswith("2 posiciones seguidas, sin datos de cierre")


@pytest.fixture
def english(monkeypatch):
    monkeypatch.setattr("app.services.daily_digest_alerts.generation_language", lambda db: "en")
    yield
    get_settings.cache_clear()


def test_english_singular(db, english):
    alert = _emit(db, [{"ticker": "ASTS", "status": "disponible", "price_change_pct": 2.5}])
    assert alert.message.startswith("1 of 1 position moved: ASTS +2.50%.")


def test_english_singular_without_close(db, english):
    alert = _emit(db, [{"ticker": "ASTS", "status": "sin datos"}])
    assert alert.message.startswith("1 position tracked, no closing data for Oct 9, 2026")
