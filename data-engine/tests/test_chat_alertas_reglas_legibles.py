"""Chat: «¿qué alertas tengo?» / «mis alertas» enseña cada regla en lenguaje normal.

Antes el bloque de avisos decía «Reglas de aviso activas: 1 (price_below 1)»: el
tipo interno en inglés y un recuento, sin empresa ni umbral, y la última vez que
saltó salía con el nombre interno («MSFT: price_below < 300»). En inglés, «my
alerts» no llegaba a esta respuesta (iba al modelo general). Solo lectura y
solo del tenant.
"""

import asyncio
from datetime import UTC, datetime, timedelta

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


def _db(extra_rules: int = 0):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("MSFT", "KO", "AAPL"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    rules = {1: [("MSFT", "price_below", "<", "300", datetime(2026, 10, 20, 15, 0, tzinfo=UTC)),
                 ("KO", "price_change", "<=", "-5", None)],
             2: [("AAPL", "price_above", ">", "250", None)]}
    rules[1] += [("KO", "price_above", ">", str(100 + i), None) for i in range(extra_rules)]
    for tenant, rows in rules.items():
        db.info["tenant_id"] = tenant
        for ticker, kind, op, value, fired in rows:
            db.add(AlertRule(tenant_id=tenant, company_id=ids[ticker], name=f"{ticker}: {kind} {op} {value}",
                             rule_type=kind, condition={"operator": op, "value": value}, active=True,
                             last_triggered_at=fired))
        db.add(ResearchAlert(tenant_id=tenant, company_id=ids["MSFT" if tenant == 1 else "AAPL"],
                             alert_type="price", severity="high", status="open",
                             title="MSFT cae un 6 %" if tenant == 1 else "AAPL sube un 9 %",
                             message="x", fingerprint=f"f{tenant}",
                             last_triggered_at=datetime.now(UTC) - timedelta(hours=2)))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué alertas tengo?", "mis alertas", "¿Tengo avisos?"])
def test_rules_are_readable(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "alerts"
    assert resp.llm_trace["provider_calls"] == 0
    assert "MSFT cae un 6 %" in resp.answer
    assert "Reglas de aviso activas: 2." in resp.answer
    assert "- MSFT: precio por debajo de 300 USD (saltó por última vez el 20 oct 2026)" in resp.answer
    assert "- KO: variación del día de -5 % o menos" in resp.answer
    assert "price_below" not in resp.answer and "price_change" not in resp.answer


def test_many_rules_are_capped():
    resp = _ask(_db(extra_rules=10), "¿Qué alertas tengo?")
    assert "Reglas de aviso activas: 12." in resp.answer
    # Primero la que ya saltó; luego por orden de creación, hasta 8.
    assert "- KO: precio por encima de 105 USD" in resp.answer
    assert "106 USD" not in resp.answer
    assert "Y 4 más en Alertas." in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué alertas tengo?")
    assert "AAPL sube un 9 %" in resp.answer
    assert "- AAPL: precio por encima de 250 USD" in resp.answer
    assert "MSFT" not in resp.answer and "KO" not in resp.answer


@pytest.fixture()
def english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("question", ["my alerts", "Show my alerts", "which alerts are set?", "Do I have any alerts?"])
def test_english_alerts_without_llm(english, question):
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "alerts"
    assert resp.llm_trace["provider_calls"] == 0
    assert "Open alerts: 1" in resp.answer
    assert "(severity high," in resp.answer
    assert "Active alert rules: 2." in resp.answer
    assert "- MSFT: price below 300 USD (last triggered Oct 20, 2026)" in resp.answer
    assert "Avisos" not in resp.answer and "gravedad" not in resp.answer


@pytest.mark.parametrize("question", ["Alert me when MSFT drops below 300", "create an alert for KO",
                                      "delete my KO alert"])
def test_english_alert_actions_are_not_listings(english, question):
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, question)
    assert (resp.llm_trace or {}).get("path") != "alerts"
