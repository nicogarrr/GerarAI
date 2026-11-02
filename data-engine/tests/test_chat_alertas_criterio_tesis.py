"""Chat «¿qué alertas tengo configuradas?»: los criterios de invalidación de tesis se leen.

Las reglas que crea la tesis (``rule_type="thesis_invalidation"``) caían en el
texto genérico: «MSFT: thesis_invalidation < 0,08», con el código interno,
sin la métrica y con el umbral redondeado (0,075 → 0,08). Ahora salen como en
el resto de la app: «invalidación de tesis: roic < 0,075».
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import AlertRule, Base, Company
from app.services.chat_service import ChatService
from app.services.thesis_invalidation_rules import MARGIN_OF_SAFETY_PCT


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las reglas no deben pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    company = Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", company_type="platform",
                      valuation_model="unassigned", currency="USD")
    db.add(company)
    db.flush()
    for metric, op, value in (("roic", "<", 0.075), (MARGIN_OF_SAFETY_PCT, "<", 10)):
        db.add(AlertRule(tenant_id=1, company_id=company.id, name=f"MSFT: {metric} {op} {value}",
                         rule_type="thesis_invalidation", condition={"operator": op, "value": value},
                         target={"kind": "thesis_invalidation", "metric": metric}, active=True))
    db.commit()
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_thesis_rules_are_readable():
    resp = _ask(_db(), "¿Qué alertas tengo configuradas?")
    assert resp.llm_trace.get("path") == "account_alert_rules"
    assert "- MSFT: invalidación de tesis: roic < 0,075" in resp.answer
    assert "- MSFT: invalidación de tesis: margen de seguridad < 10,00 %" in resp.answer
    assert "thesis_invalidation" not in resp.answer
    assert "0,08" not in resp.answer


@pytest.fixture
def english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_thesis_rules_in_english(english):
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "What alerts do I have set up?")
    assert "- MSFT: thesis invalidation: roic < 0.075" in resp.answer
    assert "- MSFT: thesis invalidation: margin of safety < 10.00%" in resp.answer
    assert "thesis_invalidation" not in resp.answer
