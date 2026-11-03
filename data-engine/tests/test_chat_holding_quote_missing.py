"""El nuevo contexto de empresa no presenta un precio de operación como mercado."""
from sqlalchemy import select

from app.models import Company
from app.services.chat_service import ChatService
from tests.test_user_context_quote_missing import db  # noqa: F401 - fixture con posición A3


def test_holding_context_marks_trade_fallback_as_unquoted(db):
    company = db.scalar(select(Company).where(Company.ticker == "ZQX"))
    _sources, lines, _citations = ChatService()._holding_context(db, company)
    text = "\n".join(lines)
    assert "20 acciones" in text
    assert "sin cotización real" in text
    assert "valor 280" not in text
    assert "precio 14" not in text
    assert "% de tu cartera" not in text


def test_holding_context_does_not_compute_weight_with_unquoted_denominator(db):
    company = db.scalar(select(Company).where(Company.ticker == "UBER"))
    _sources, lines, _citations = ChatService()._holding_context(db, company)
    text = "\n".join(lines)
    assert "valor 1.200,00 EUR" in text
    assert "% de tu cartera" not in text


def test_real_quote_restores_value_and_weight(db):
    from datetime import date
    from decimal import Decimal

    from app.models import MarketPrice

    company = db.scalar(select(Company).where(Company.ticker == "ZQX"))
    db.add(MarketPrice(company_id=company.id, date=date(2026, 10, 1), close=Decimal("14")))
    db.flush()
    _sources, lines, _citations = ChatService()._holding_context(db, company)
    text = "\n".join(lines)
    assert "valor 280,00 EUR" in text
    assert "2,7 % de tu cartera" in text
    assert "sin cotización real" not in text


def test_unquoted_warning_in_english(db, monkeypatch):
    monkeypatch.setattr("app.services.chat_service._english", lambda: True)
    company = db.scalar(select(Company).where(Company.ticker == "ZQX"))
    _sources, lines, _citations = ChatService()._holding_context(db, company)
    text = "\n".join(lines)
    assert "no real quote" in text
    assert "value 280" not in text
    assert "% of your portfolio" not in text
