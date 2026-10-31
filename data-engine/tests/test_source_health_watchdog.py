"""Pruebas del watchdog de fuentes degradadas (alerta in-app al operador, coste 0).

Fulfills: VAL-DATA-004
Expected Behavior:
- Una fuente que entra en degraded/failing genera una ResearchAlert in-app con
  lo medido por el circuit breaker; nunca se inventa causa ni estado
- Idempotente por fuente, estado y día; sin transición no hay alerta; una
  fuente "unknown" (nunca sondeada) no alerta
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services import source_health_watchdog as wd


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="owner"))
        session.commit()
        session.info.update(tenant_id=1, user_id="owner")
        yield session
    engine.dispose()


def _fuente(
    status: str, *, name: str = "Yahoo Finance", failures: int = 3, fallback: str | None = "alpha_vantage"
) -> dict:
    """as_dict() de una fuente (la clave del registry la pone _collect_sources)."""
    circuit = {"healthy": "closed", "degraded": "half_open", "failing": "open", "unknown": "closed"}[status]
    return {
        "name": name,
        "status": status,
        "circuit_state": circuit,
        "consecutive_failures": failures,
        "last_checked_at": "2026-10-31T00:30:00+00:00",
        "fallback_source": fallback,
        "is_primary": True,
        "response_time_ms": 12.0,
    }


NOW = datetime(2026, 10, 31, 0, 31, tzinfo=UTC)


def test_transicion_a_failing_emite_alerta_in_app(db):
    last: dict[str, str] = {"yahoo_finance": "healthy"}

    class _Status:
        def as_dict(self):
            return _fuente("failing")

    class _Registry:
        sources = {"yahoo_finance": _Status()}

    out = wd.emit_source_health_alerts(db, registry=_Registry(), now=NOW, last_states=last)
    assert out["created"] == 1
    alert = db.scalar(select(ResearchAlert))
    assert alert.alert_type == "source_health"
    assert alert.severity == "high"
    assert alert.channels == ["in_app"]
    assert "Yahoo Finance" in alert.title
    assert "alpha_vantage" in alert.message
    assert alert.metadata_["source_key"] == "yahoo_finance"


def test_sin_transicion_no_alerta(db):
    last = {"yahoo_finance": "failing"}  # ya estaba caída: no es una transición

    class _Status:
        def as_dict(self):
            return _fuente("failing")

    class _Registry:
        sources = {"yahoo_finance": _Status()}

    out = wd.emit_source_health_alerts(db, registry=_Registry(), now=NOW, last_states=last)
    assert out["created"] == 0
    assert db.scalar(select(ResearchAlert)) is None


def test_unknown_nunca_alerta(db):
    last: dict[str, str] = {}

    class _Status:
        def as_dict(self):
            return _fuente("unknown", failures=0, fallback=None)

    class _Registry:
        sources = {"ecb": _Status()}

    out = wd.emit_source_health_alerts(db, registry=_Registry(), now=NOW, last_states=last)
    assert out["created"] == 0


def test_idempotente_mismo_dia_y_realerta_al_dia_siguiente(db):
    class _Status:
        def as_dict(self):
            return _fuente("degraded", failures=1)

    class _Registry:
        sources = {"ecb": _Status()}

    last: dict[str, str] = {"ecb": "healthy"}
    first = wd.emit_source_health_alerts(db, registry=_Registry(), now=NOW, last_states=last)
    assert first["created"] == 1
    # Recae el mismo día: la transición vuelve a detectarse (se recuperó y cayó),
    # pero el fingerprint la deduplica.
    last["ecb"] = "healthy"
    same_day = wd.emit_source_health_alerts(db, registry=_Registry(), now=NOW, last_states=last)
    assert same_day["created"] == 0
    assert same_day["existing"] == 1
    # Al día siguiente sí hay nueva alerta.
    last["ecb"] = "healthy"
    nxt = datetime(2026, 11, 1, 0, 5, tzinfo=UTC)
    second_day = wd.emit_source_health_alerts(db, registry=_Registry(), now=nxt, last_states=last)
    assert second_day["created"] == 1
    assert len(db.scalars(select(ResearchAlert)).all()) == 2


def test_degraded_es_severity_media(db):
    class _Status:
        def as_dict(self):
            return _fuente("degraded", failures=1)

    class _Registry:
        sources = {"alpha_vantage": _Status()}

    wd.emit_source_health_alerts(db, registry=_Registry(), now=NOW, last_states={})
    alert = db.scalar(select(ResearchAlert))
    assert alert.severity == "medium"
    assert "degradada" in alert.title
