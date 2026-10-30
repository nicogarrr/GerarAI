"""Contrato de `latest_snapshot` (GET /api/market/regime): estado y cobertura coherentes."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, MarketRegimeSnapshot
from app.services.market_snapshot_service import latest_snapshot


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        yield db
    engine.dispose()


def _snapshot(days_old: int, coverage: str, input_hash: str) -> MarketRegimeSnapshot:
    today = datetime.now(UTC).date()
    return MarketRegimeSnapshot(
        snapshot_date=today - timedelta(days=days_old),
        model_version="macro-context-hmm-v2",
        input_hash=input_hash,
        metrics={"treasury_10y_us": {"value": 4.1}},
        probabilities={"risk_on": 0.6},
        coverage=coverage,
        generated_at=datetime.now(UTC),
    )


def test_empty_table_reports_unavailable(db):
    result = latest_snapshot(db)
    assert result["status"] == "sin datos"
    assert result["coverage"] == "unavailable"
    assert result["metrics"] == {} and result["probabilities"] == {}
    assert "date" not in result


def test_fresh_ok_snapshot_is_disponible(db):
    db.add(_snapshot(0, "ok", "a"))
    db.commit()
    result = latest_snapshot(db)
    assert result["status"] == "disponible"
    assert result["coverage"] == "ok"
    assert result["metrics"]["treasury_10y_us"]["value"] == 4.1


def test_age_four_days_still_disponible(db):
    db.add(_snapshot(4, "ok", "b"))
    db.commit()
    assert latest_snapshot(db)["status"] == "disponible"
    assert latest_snapshot(db)["coverage"] == "ok"


def test_age_five_days_is_obsoleto_stale(db):
    db.add(_snapshot(5, "ok", "c"))
    db.commit()
    result = latest_snapshot(db)
    assert result["status"] == "obsoleto"
    assert result["coverage"] == "stale"


def test_unavailable_stays_unavailable_when_fresh(db):
    db.add(_snapshot(0, "unavailable", "d"))
    db.commit()
    result = latest_snapshot(db)
    assert result["status"] == "sin datos"
    assert result["coverage"] == "unavailable"


def test_unavailable_stays_unavailable_when_old(db):
    # Antes devolvia coverage="stale" junto a status="sin datos": un par
    # contradictorio («sin datos» pero «datos envejecidos» a la vez).
    db.add(_snapshot(10, "unavailable", "e"))
    db.commit()
    result = latest_snapshot(db)
    assert result["status"] == "sin datos"
    assert result["coverage"] == "unavailable"


def test_latest_wins_by_date_then_id(db):
    db.add(_snapshot(1, "ok", "f"))
    db.add(_snapshot(2, "unavailable", "g"))
    db.commit()
    assert latest_snapshot(db)["coverage"] == "ok"


def test_portfolio_beta_marker_never_leaks(db):
    db.add(_snapshot(0, "ok", "h"))
    db.commit()
    beta = latest_snapshot(db)["portfolio_beta"]
    assert beta["status"] == "no_disponible"
