"""Chat: preguntas de recuento que caían al modelo general.

- «how many alerts do I have?» → avisos abiertos y reglas (como «¿cuántas alertas tengo?»).
- «how many theses do I have?» → tus tesis (como «¿cuántas tesis tengo?»).
- «¿cuántas pantallas tengo guardadas?» → tus pantallas guardadas.
- «¿cuántas empresas sigo?» → tu watchlist (como «how many companies do I follow?»).
Antes contestaban «No puedo responderte con fuentes…». Solo lectura.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, ResearchAlert, WatchItem
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    company = Company(
        ticker="KO",
        name="KO Inc",
        exchange="NYSE",
        company_type="consumer",
        valuation_model="unassigned",
        currency="USD",
    )
    db.add(company)
    db.flush()
    db.info["tenant_id"] = 1
    db.add(WatchItem(tenant_id=1, symbol="MSFT"))
    db.add(
        ResearchAlert(
            tenant_id=1,
            company_id=company.id,
            status="open",
            title="KO cae un 5 %",
            message="m",
            severity="high",
            alert_type="price",
            fingerprint="ko-1",
        )
    )
    db.commit()
    db.info["tenant_id"] = 2
    db.add(WatchItem(tenant_id=2, symbol="NVDA"))
    db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.fixture
def _en(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("_en")
def test_how_many_alerts():
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "How many alerts do I have?")
    assert resp.llm_trace["path"] == "alerts"
    assert resp.answer.startswith("Open alerts: 1 (most recent first).")


@pytest.mark.usefixtures("_en")
def test_how_many_theses():
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "How many theses do I have?")
    assert resp.llm_trace["path"] == "portfolio_theses"
    assert "I can't answer" not in resp.answer


def test_cuantas_pantallas_tengo_guardadas():
    resp = _ask(_db(), "¿Cuántas pantallas tengo guardadas?")
    assert resp.llm_trace["path"] == "account_saved_screens"
    assert resp.answer.startswith("No tienes pantallas guardadas en el screener.")


def test_cuantas_empresas_sigo():
    resp = _ask(_db(), "¿Cuántas empresas sigo?")
    assert "No puedo responderte con fuentes" not in resp.answer
    assert "MSFT" in resp.answer
    assert "NVDA" not in resp.answer  # el usuario B no se cuela
