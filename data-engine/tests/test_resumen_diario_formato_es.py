"""Resumen diario en castellano: cifras en formato español y texto con tildes.

El aviso decía «ASTS +2.50%», «con variacion», «No habia» y «y 4 mas», y con
una sola posición omitida «1 omitidas». En inglés no cambia.
"""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

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


def test_variation_uses_spanish_decimal_comma_and_spaced_percent(db):
    alert = _emit(db, [
        {"ticker": "ASTS", "status": "disponible", "price_change_pct": 2.5},
        {"ticker": "NBIS", "status": "disponible", "price_change_pct": -1234.5},
    ])
    assert "NBIS −1.234,50 %" in alert.message or "NBIS -1.234,50 %" in alert.message
    assert "ASTS +2,50 %" in alert.message
    assert "2.50%" not in alert.message
    assert "2 de 2 posiciones con variación:" in alert.message


def test_no_positions_and_more_without_data_carry_accents(db):
    alert = _emit(db, [])
    assert alert.message.startswith("No había posiciones abiertas que resumir.")


def test_one_left_out_is_singular(db):
    items = [{"ticker": f"T{i:02d}", "status": "disponible", "price_change_pct": float(i + 1)}
             for i in range(17)]
    items += [{"ticker": f"S{i:02d}", "status": "sin datos"} for i in range(17)]
    alert = _emit(db, items)
    assert "Mostradas 16 de 17 posiciones con variación; 1 omitida." in alert.message
    assert "y 1 más." in alert.message


def test_english_keeps_english_format(db, monkeypatch):
    import app.services.daily_digest_alerts as mod

    monkeypatch.setattr(mod, "generation_language", lambda _db: "en")
    alert = _emit(db, [{"ticker": "ASTS", "status": "disponible", "price_change_pct": 2.5}])
    assert "ASTS +2.50%" in alert.message
