"""Regla de noticias: una noticia válida no se pierde detrás de otra ya avisada o sin titular.

La regla miraba solo la noticia MÁS RECIENTE desde su cursor. Si esa última ya
la había avisado otra vía (duplicada) o venía sin titular, no saltaba nada y el
cursor avanzaba igual: la noticia anterior, nueva y con titular, se perdía para
siempre. Vale para cualquier empresa y tenant: se avisa de la más reciente que
sí se puede citar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, NewsEvent, ResearchAlert, Tenant
from app.services.alert_rule_service import AlertRuleService
from app.services.review_alert_service import ReviewAlertService


@pytest.fixture
def db():
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t-news", name="t"))
        session.commit()
        session.info["tenant_id"] = 1
        session.info["user_id"] = "u-1"
        yield session
    get_settings.cache_clear()


def _company(db, ticker="DEMO"):
    c = Company(ticker=ticker, name=f"{ticker} Corp", exchange="NASDAQ", currency="USD", sector="x",
                industry="x", company_type="x", valuation_model="x", special_sources=[],
                special_risks=[], factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _rule(db, c):
    s = AlertRuleService()
    r = s.create(db, c, rule_type="news", operator=">", value=0, cooldown_seconds=0)
    r.last_evaluated_at = datetime.now(UTC) - timedelta(minutes=10)
    db.commit()
    return s, r


def _news(db, c, title, slug, minutes_ago):
    event = NewsEvent(company_id=c.id, title=title, url=f"https://example.invalid/{slug}", source="s",
                      summary="", created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago))
    db.add(event)
    db.commit()
    return event


def _rule_alerts(db):
    return list(db.scalars(select(ResearchAlert).where(ResearchAlert.alert_type == "news")))


def test_older_fresh_news_alerts_when_the_latest_was_already_alerted(db):
    c = _company(db)
    s, r = _rule(db, c)
    _news(db, c, "Contrato nuevo con la agencia espacial", "contrato", minutes_ago=3)
    covered = _news(db, c, "Resultados del tercer trimestre", "resultados", minutes_ago=1)
    ReviewAlertService().emit_alert(
        db, company_id=c.id, alert_type="news_material_update", severity="high",
        title="Revisión necesaria", message="x", fingerprint_parts=["review", str(covered.id)],
        metadata={"news_event_id": covered.id},
    )
    db.commit()
    with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
        result = s.evaluate(db, r)
        again = s.evaluate(db, r)
    assert result["status"] == "triggered"
    alerts = _rule_alerts(db)
    assert len(alerts) == 1 and "Contrato nuevo con la agencia espacial" in alerts[0].message
    # Consumida: la siguiente pasada no repite el aviso.
    assert again["status"] == "evaluated"
    assert len(_rule_alerts(db)) == 1


def test_older_titled_news_alerts_when_the_latest_has_no_title(db):
    c = _company(db, "OTHER")
    s, r = _rule(db, c)
    _news(db, c, "Ampliación de capital aprobada", "ampliacion", minutes_ago=3)
    _news(db, c, "   ", "sin-titulo", minutes_ago=1)
    with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
        result = s.evaluate(db, r)
    assert result["status"] == "triggered"
    alerts = _rule_alerts(db)
    assert len(alerts) == 1 and "Ampliación de capital aprobada" in alerts[0].message


def test_only_covered_or_untitled_news_still_does_not_alert(db):
    c = _company(db, "THIRD")
    s, r = _rule(db, c)
    covered = _news(db, c, "Dividendo extraordinario", "dividendo", minutes_ago=2)
    _news(db, c, "", "vacia", minutes_ago=1)
    ReviewAlertService().emit_alert(
        db, company_id=c.id, alert_type="news_material_update", severity="high",
        title="Revisión necesaria", message="x", fingerprint_parts=["review", str(covered.id)],
        metadata={"news_event_id": covered.id},
    )
    db.commit()
    with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
        result = s.evaluate(db, r)
    assert result["status"] == "evaluated"
    assert not _rule_alerts(db)
