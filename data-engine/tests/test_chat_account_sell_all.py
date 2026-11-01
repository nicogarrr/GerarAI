"""Chat: «¿cuánto IRPF pagaría si vendo todo?».

Antes no tenía respuesta (ruta general). Ahora suma la venta hipotética de
todas tus posiciones abiertas con el mismo FIFO y la misma escala del ahorro
que «¿cuánto IRPF pagaría si vendo UBER?», posición por posición, y añade lo ya
realizado en el año. Solo lectura: no ejecuta ninguna venta.
"""

import asyncio
from datetime import date

import pytest

from app.core.config import get_settings
from app.services import brain_account_tools
from app.services.chat_service import ChatService
from tests.test_chat_account_year import _db


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el IRPF de vender todo no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", [
    "¿Cuánto IRPF pagaría si vendo todo?",
    "si lo vendo todo, ¿cuánto pago a Hacienda?",
    "¿Cuántos impuestos pagaría si vendiera toda mi cartera?",
])
def test_sell_all_tax(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_sell_all_tax"
    text = resp.answer
    assert text.startswith("Si vendieras hoy tus 2 posiciones (datos a 30 oct 2026):")
    assert "valor 4.200,00 €, coste 2.430,68 € (FIFO), ganancia neta de 1.769,33 €." in text
    assert "- UBER: +1.049,33 €\n- MSFT: +720,00 €" in text
    assert "IRPF estimado: 336,17 € (un 19,0 % de la ganancia), escala del ahorro de 2025 (la última verificada" in text
    assert "En 2026 ya llevas +180,00 € realizado: sumándolo, la base sería +1.949,33 € y el IRPF 370,37 €." in text
    assert "No ejecuto ventas" in text
    assert "AAPL" not in text


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo todo?")
    assert resp.answer == "No tienes posiciones abiertas guardadas: no hay nada que vender."
    assert "UBER" not in resp.answer and "MSFT" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "How much tax would I pay if I sold everything?")
    assert resp.llm_trace["path"] == "account_sell_all_tax"
    assert resp.answer.startswith("If you sold all 2 positions today (data as of Oct 30, 2026):")


@pytest.mark.parametrize("question", [
    "¿Cuánto IRPF pagaría si vendo UBER?",
    "¿Cuánto IRPF pagaría si vendo todas mis UBER?",
])
def test_single_ticker_sale_unchanged(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
