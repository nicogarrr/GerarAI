"""Chat: «my watchlist» en inglés sin modelo sale en inglés.

Antes, en inglés, si el modelo fallaba (o no había modelo) la respuesta
determinista de la watchlist salía en castellano: «Tus datos de watchlist en
GerarAI: - 2 valores. Margen de seguridad… aún sin ficha…». El contexto que
recibe el modelo no cambia. Solo lectura y solo del tenant.
"""

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import reset_language_scope, set_language_scope
from app.models.entities import Base, Company, WatchItem
from app.services.chat_service import ChatService
from app.services.personal_answer import answer_personal_question, detect_personal_intent
from app.services.user_context import build_user_context


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Company(ticker="KO", name="Coca-Cola", exchange="NYSE", company_type="consumer",
                   valuation_model="unassigned", currency="USD"))
    db.commit()
    for tenant, symbols in ((1, ("NVDA", "KO")), (2, ("TSLA",))):
        db.info["tenant_id"] = tenant
        for symbol in symbols:
            db.add(WatchItem(tenant_id=tenant, symbol=symbol, company=symbol + " Corp"))
        db.commit()
    db.info["tenant_id"] = 1
    return db


@pytest.fixture()
def english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _english_db():
    db = _db()
    db.info["language"] = "en"
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_english_watchlist_fallback_in_english(english):
    resp = _ask(_english_db(), "my watchlist")
    assert resp.llm_trace["path"] == "personal_context"
    assert resp.llm_trace["intent"] == "watchlist"
    lines = resp.answer.splitlines()
    assert lines[0] == "Your watchlist in GerarAI:"
    assert lines[1] == ("- 2 stocks. Margin of safety = (fair value − price) / fair value; "
                        "positive = trading below fair value.")
    assert lines[2].startswith("- NVDA: no GerarAI page yet (no price or fair value); ")
    assert lines[3].startswith("- KO (Coca-Cola), no saved price, "
                               "no fair value (neither a published thesis nor the engine), ")
    for spanish in ("Tus datos", "valores", "sin ficha", "sin precio", "valor justo", "nivel DCA"):
        assert spanish not in resp.answer


@pytest.mark.parametrize("age_days", [0, 15])
def test_english_dca_level_in_english(english, monkeypatch, age_days):
    # Language assertions must not age with the wall clock. Exercise the stale
    # notice explicitly as well, without changing or suppressing production copy.
    monkeypatch.setattr("app.services.user_context.local_today", lambda: date(2026, 10, 30) + timedelta(days=age_days))
    monkeypatch.setattr(get_settings(), "dca_max_data_age_days", 7)
    db = _english_db()
    reading = SimpleNamespace(level=-1, label="RECORTE LIGERO", status="forming", signal_date=date(2026, 10, 30))
    intent = detect_personal_intent("my watchlist")
    assert intent is not None
    token = set_language_scope("en")
    try:
        resp = asyncio.run(answer_personal_question(
            db, "my watchlist", intent, None, dca_reader=lambda _db, _tenant, _symbols: {"KO": reading},
        ))
    finally:
        reset_language_scope(token)
    assert resp is not None
    stale = f" [stale: last close {age_days} days ago]" if age_days > 7 else ""
    assert ("- KO (Coca-Cola), no saved price, no fair value (neither a published thesis nor the engine), "
            f"DCA level LIGHT TRIM (forming) (Oct 30, 2026){stale}.") in resp.answer
    if age_days == 0:
        assert "[stale:" not in resp.answer
    assert "- NVDA: no GerarAI page yet (no price or fair value); no DCA level evaluated." in resp.answer


def test_model_context_stays_spanish(english):
    db = _english_db()
    ctx = build_user_context(db, sections=("watchlist",), dca_reader=lambda *_a: {})
    assert ctx is not None
    rendered = ctx.render()
    assert "2 valores" in rendered and "aún sin ficha" in rendered
    assert "stocks" not in rendered and "no GerarAI page" not in rendered


def test_user_b_never_sees_user_a(english):
    db = _english_db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "my watchlist")
    assert "TSLA" in resp.answer
    assert "NVDA" not in resp.answer and "KO" not in resp.answer
    assert "- 1 stock. Margin" in resp.answer


def test_spanish_unchanged():
    resp = _ask(_db(), "mi watchlist")
    assert resp.answer.splitlines()[0] == "Tus datos de watchlist en GerarAI:"
    assert "- 2 valores. Margen de seguridad" in resp.answer
