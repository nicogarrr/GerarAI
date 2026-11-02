"""Chat: «which companies am I losing money on?» lista las posiciones en pérdidas.

En castellano «¿qué empresas tengo en pérdidas?» ya iba a la lista (#4321), pero en
inglés «which companies am I losing money on?» / «which stocks am I making money
on?» caían al modelo general: «companies» no contaba como posiciones y «am I» no
contaba como tuyas. Solo lectura y solo del tenant.
"""

import pytest

from app.core.config import get_settings
from tests.test_chat_posiciones_perdidas import _ask, _db


def _ask_en(monkeypatch, question, tenant=1):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    db.info["tenant_id"] = tenant
    try:
        return _ask(db, question)
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", ["Which companies am I losing money on?", "which stocks am I losing on?",
                                      "What companies do I have at a loss?"])
def test_losers(monkeypatch, question):
    resp = _ask_en(monkeypatch, question)
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines()[:3] == [
        "You have 2 positions at a loss on their purchase cost (data as of Oct 30, 2026), worst first:",
        "1. KO -15.4% (-100.00 €)",
        "2. ITX -10.0% (-20.00 €)",
    ]


def test_winners(monkeypatch):
    resp = _ask_en(monkeypatch, "Which companies am I making money on?")
    assert resp.llm_trace["path"] == "account_return_ranking"
    assert resp.answer.splitlines()[1] == "1. TSLA +50.0% (+500.00 €)"


def test_user_b_never_sees_user_a(monkeypatch):
    resp = _ask_en(monkeypatch, "which companies am I losing money on?", tenant=2)
    assert "1. NVDA -99.0% (-990.00 €)" in resp.answer
    assert "KO" not in resp.answer


@pytest.mark.parametrize("question", ["Which companies are losing money in Europe?", "what if KO is at a loss?"])
def test_general_questions_unchanged(monkeypatch, question):
    resp = _ask_en(monkeypatch, question)
    assert (resp.llm_trace or {}).get("path") != "account_return_ranking"
