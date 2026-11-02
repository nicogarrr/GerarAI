"""Chat «¿qué he vendido este año?»: con más de 20 ventas dice cuántas faltan.

La lista se corta en 20 ventas para no hacer un muro de texto, pero el corte no
se decía: con 25 ventas salían 20 líneas y el «Total realizado» de las 25, sin
ningún aviso de que faltaban 5. Ahora acaba con «… y 5 ventas más (en Impuestos)».
De paso, una venta de 1 acción decía «1 acciones» («1 shares» en inglés).
"""

import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las ventas no deben pasar por el LLM")


def _report(n_sales: int) -> dict:
    sales = [{"quantity": 1, "date": f"2026-03-{day:02d}", "proceeds_base": 100.0, "gain_base": 10.0}
             for day in range(1, n_sales + 1)]
    return {"realized": [{"ticker": "KO", "sale_count": n_sales, "sales": sales, "gain_base": 10.0 * n_sales}],
            "summary": {}}


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(monkeypatch, n_sales, question="¿Qué he vendido este año?"):
    monkeypatch.setattr(brain_account_tools, "_tax_data", lambda db, year: _report(n_sales))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    return db, asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_more_than_20_sales_says_how_many_are_missing(monkeypatch):
    _, resp = _ask(monkeypatch, 25)
    assert resp.llm_trace["path"] == "account_sales"
    assert resp.answer.count("\n- KO: 1 acción el") == 20
    assert "… y 5 ventas más (en Impuestos)." in resp.answer
    assert "Total realizado: +250,00 €." in resp.answer


def test_20_sales_or_fewer_unchanged(monkeypatch):
    _, resp = _ask(monkeypatch, 20)
    assert resp.answer.count("\n- KO: 1 acción el") == 20
    assert "más (en Impuestos)" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(brain_account_tools, "_tax_data", lambda db, year: _report(21))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.info["language"] = "en"
    resp = asyncio.run(ChatService(provider=_NoLLM()).answer(db, "What did I sell this year?", "global", None))
    assert "… and 1 more sale (in Taxes)." in resp.answer
    assert "- KO: 1 share on Mar 1, 2026" in resp.answer
