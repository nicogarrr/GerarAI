"""Chat: «what alerts do I have?» y la lista de reglas ya cuentan los avisos abiertos.

Antes «what alerts do I have?» contestaba solo con las reglas («You have no
active alerts…») aunque hubiera avisos abiertos (alertas que ya saltaron); en
castellano «¿qué alertas tengo?» sí los enseñaba. Ahora la pregunta en inglés
va a la misma respuesta que en castellano (avisos abiertos y reglas), y la lista
de reglas («¿qué alertas tengo configuradas?», «list my alerts») añade cuántos
avisos abiertos hay. Solo lectura y solo del tenant.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import AlertRule, Base, Company, ResearchAlert
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("los avisos no deben pasar por el LLM")


def _db(rules=True):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("KO", "AAPL"):
        company = Company(
            ticker=ticker,
            name=ticker + " Inc",
            exchange="NYSE",
            company_type="consumer",
            valuation_model="unassigned",
            currency="USD",
        )
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    db.info["tenant_id"] = 1
    db.add(
        ResearchAlert(
            tenant_id=1,
            company_id=ids["KO"],
            status="open",
            title="KO cae un 5 %",
            message="m",
            severity="high",
            alert_type="price",
            fingerprint="ko-1",
        )
    )
    db.add(
        ResearchAlert(
            tenant_id=1,
            company_id=ids["KO"],
            status="open",
            title="KO pospuesto",
            message="m",
            severity="low",
            alert_type="price",
            fingerprint="ko-2",
            snoozed_until=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )
    db.add(
        ResearchAlert(
            tenant_id=1,
            company_id=ids["KO"],
            status="resolved",
            title="KO viejo",
            message="m",
            severity="low",
            alert_type="price",
            fingerprint="ko-3",
        )
    )
    if rules:
        db.add(
            AlertRule(
                tenant_id=1,
                company_id=ids["KO"],
                name="KO < 50",
                rule_type="price_below",
                condition={"operator": "<", "value": "50"},
                active=True,
            )
        )
    db.commit()
    db.info["tenant_id"] = 2
    db.add(
        ResearchAlert(
            tenant_id=2,
            company_id=ids["AAPL"],
            status="open",
            title="AAPL sube",
            message="m",
            severity="low",
            alert_type="price",
            fingerprint="aapl-1",
        )
    )
    db.add(
        ResearchAlert(
            tenant_id=2,
            company_id=ids["AAPL"],
            status="open",
            title="AAPL baja",
            message="m",
            severity="low",
            alert_type="price",
            fingerprint="aapl-2",
        )
    )
    db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question, english=False):
    if not english:
        return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))
    db.info["language"] = "en"
    try:
        return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))
    finally:
        get_settings.cache_clear()


@pytest.fixture
def _en(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("_en")
def test_what_alerts_do_i_have_shows_open_alerts():
    resp = _ask(_db(rules=False), "What alerts do I have?", english=True)
    assert resp.llm_trace["provider_calls"] == 0
    assert "You have no active alerts" not in resp.answer
    assert resp.answer.startswith("Open alerts: 1 (most recent first).")
    assert "- KO: KO cae un 5 % (severity high," in resp.answer


@pytest.mark.usefixtures("_en")
def test_set_up_still_lists_rules_and_counts_open_alerts():
    resp = _ask(_db(), "What alerts do I have set up?", english=True)
    assert resp.llm_trace["path"] == "account_alert_rules"
    assert resp.answer.splitlines() == [
        "You have 1 active alert:",
        "- KO: price below 50 USD",
        "You also have 1 open alert (one that already triggered); see it in Alerts.",
        "To create, pause or delete alerts, go to Alerts.",
    ]


def test_rules_list_without_rules_mentions_open_alerts():
    resp = _ask(_db(rules=False), "¿Qué alertas tengo configuradas?")
    assert resp.llm_trace["path"] == "account_alert_rules"
    assert resp.answer.splitlines() == [
        "No tienes alertas activas. Puedes crearlas en Alertas.",
        "Eso sí, tienes 1 aviso abierto (una alerta que ya saltó); lo ves en Alertas.",
    ]


def test_rules_list_plural_open_alerts_other_user():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "lista de mis alertas")
    assert resp.answer.splitlines() == [
        "No tienes alertas activas. Puedes crearlas en Alertas.",
        "Eso sí, tienes 2 avisos abiertos (alertas que ya saltaron); los ves en Alertas.",
    ]
    assert "KO" not in resp.answer


def test_no_open_alerts_no_extra_line():
    db = _db()
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Qué alertas tengo configuradas?")
    assert resp.answer == "No tienes alertas activas. Puedes crearlas en Alertas."
