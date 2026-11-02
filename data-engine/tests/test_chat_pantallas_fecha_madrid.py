"""Chat: «última ejecución» de pantallas y «saltó por última vez» de alertas, en día de Madrid.

last_run_at se guarda en UTC. Una pantalla ejecutada a las 00:30 de Madrid
(23:30 UTC del día anterior) salía «última ejecución el 29 oct» cuando para el
usuario era el 30; igual el «saltó por última vez» de las alertas (dos
respuestas). Ahora la fecha se pasa a Europe/Madrid como local_today().
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import AlertRule, Base, Company, SavedScreen
from app.services.chat_service import ChatService

# 30 oct 2026 00:30 en Madrid (CET, UTC+1 tras el cambio de hora del 25 oct).
_AFTER_MIDNIGHT_MADRID = datetime(2026, 10, 29, 23, 30, tzinfo=UTC)


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las pantallas no deben pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.add(SavedScreen(tenant_id=1, name="Calidad", active=True, last_run_at=_AFTER_MIDNIGHT_MADRID,
                       criteria=[{"left": "pe", "operator": "<", "right": "20"}]))
    db.commit()
    db.info["tenant_id"] = 2
    db.add(SavedScreen(tenant_id=2, name="De otro", active=True, last_run_at=_AFTER_MIDNIGHT_MADRID,
                       criteria=[]))
    db.commit()
    db.info["tenant_id"] = 1
    return db


def test_last_run_date_is_madrid_day():
    db = _db()
    resp = asyncio.run(ChatService(provider=_NoLLM()).answer(db, "mis pantallas del screener", "global", None))
    assert resp.llm_trace.get("path") == "account_saved_screens"
    assert "última ejecución el 30 oct 2026." in resp.answer
    assert "29 oct" not in resp.answer
    assert "De otro" not in resp.answer


def _alerts_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("MSFT", "AAPL"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    for tenant, ticker in ((1, "MSFT"), (2, "AAPL")):
        db.info["tenant_id"] = tenant
        db.add(AlertRule(tenant_id=tenant, company_id=ids[ticker], name=f"{ticker}: price_below < 300",
                         rule_type="price_below", condition={"operator": "<", "value": "300"}, active=True,
                         last_triggered_at=_AFTER_MIDNIGHT_MADRID))
        db.commit()
    db.info["tenant_id"] = 1
    return db


@pytest.mark.parametrize(("question", "path"), [("¿Qué alertas tengo configuradas?", "account_alert_rules"),
                                                ("¿Qué alertas tengo?", "alerts")])
def test_alert_last_triggered_is_madrid_day(question, path):
    resp = asyncio.run(ChatService(provider=_NoLLM()).answer(_alerts_db(), question, "global", None))
    assert resp.llm_trace.get("path") == path
    assert "- MSFT: precio por debajo de 300 USD (saltó por última vez el 30 oct 2026)" in resp.answer
    assert "AAPL" not in resp.answer
