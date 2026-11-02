"""Chat «¿cuánto IRPF pagaría si lo vendo todo?»: sin mezclar posiciones sin cotización.

La venta hipotética de toda la cartera sumaba también las posiciones que el
ledger valora al precio de su última operación porque no tienen cotización
(auditoría A3): su «valor» es el de compra, la ganancia sale 0 y entra en el
total y en el número de posiciones como si estuviera medida. Cartera, impuestos,
el ranking (#4238) y el latente (#4243) ya las dejan fuera; ahora aquí también,
nombradas aparte.
"""

import asyncio
from datetime import date

import pytest

from app.core.config import get_settings
from app.services import brain_account_tools
from app.services.chat_service import ChatService
from tests.test_chat_latente_sin_cotizacion import _db


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el IRPF de vender todo no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    monkeypatch.setattr(brain_account_tools, "_tax_data", lambda db, year: {"summary": {}, "realized": []})
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_sell_all_leaves_out_unquoted_positions():
    resp = _ask(_db(), "¿Cuánto IRPF pagaría si lo vendo todo?")
    assert resp.llm_trace["path"] == "account_sell_all_tax"
    text = resp.answer
    assert text.startswith("Si vendieras hoy tu única posición medida (datos a 30 oct 2026):")
    assert "valor 1.500,00 €, coste 1.000,00 € (FIFO), ganancia neta de 500,00 €." in text
    assert "- NEWCO:" not in text
    assert "Fuera del cálculo (sin cotización real): GHOST, NEWCO." in text


def test_sell_all_leaves_out_unquoted_positions_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "How much tax would I pay if I sell everything?")
    assert resp.llm_trace["path"] == "account_sell_all_tax"
    text = resp.answer
    assert text.startswith("If you sold your only measured position today")
    assert "value 1,500.00 €, cost 1,000.00 € (FIFO), net gain 500.00 €." in text
    assert "- NEWCO:" not in text
    assert "Left out (no real quote): GHOST, NEWCO." in text


def test_sell_all_unchanged_when_everything_is_quoted():
    text = _ask(_db(with_unquoted=False), "¿Cuánto IRPF pagaría si lo vendo todo?").answer
    assert "sin cotización real" not in text
    assert "valor 1.500,00 €, coste 1.000,00 € (FIFO), ganancia neta de 500,00 €." in text
