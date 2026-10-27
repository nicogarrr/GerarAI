"""«PER de CB y UNH» en el Cerebro (prueba real realqa-14).

La herramienta de datos de empresa solo respondía precio/PER con exactamente
un ticker (o con «compara»). Con dos tickers devolvía None y la pregunta
acababa en el generador general sin fuentes: «No puedo responderte con
fuentes ahora mismo», aunque el PER de ambas estaba guardado.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact, MarketPrice, Tenant
from app.services.brain_data_tools import answer_data_question
from app.services.chat_service import ChatService

TODAY = date.today()


class _NoLLM:
    name = "no-llm"

    async def complete(self, *args, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("el PER guardado no pasa por el LLM")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        session.add(Tenant(id=1, external_id="one"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _company(db, ticker, name):
    company = Company(
        ticker=ticker, name=name, exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="standard",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _priced(db, company, close, eps, *, year=2025):
    db.add(MarketPrice(company_id=company.id, date=TODAY - timedelta(days=1), open=close,
                       high=close, low=close, close=Decimal(str(close)), source="yahoo"))
    db.add(FinancialFact(
        company_id=company.id, metric="eps_diluted", value=Decimal(str(eps)), unit="USD/shares",
        period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
        source_type="SEC", is_reported=True, tenant_id=1,
    ))
    db.commit()


def _watchlist(db):
    cb = _company(db, "CB", "Chubb Limited")
    unh = _company(db, "UNH", "UnitedHealth Group")
    _priced(db, cb, 280, 22.4)
    _priced(db, unh, 330, 16.5)
    return cb, unh


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None))


def test_per_de_cb_y_unh_responde_con_fuentes(db):
    _watchlist(db)
    resp = _ask(db, "PER de CB y UNH")
    assert resp.llm_trace["path"] == "company_quotes"
    assert resp.llm_trace["provider_calls"] == 0
    assert "No puedo responderte" not in resp.answer
    assert "PER sobre BPA anual: 12,50 veces" in resp.answer
    assert "PER sobre BPA anual: 20,00 veces" in resp.answer
    # En el orden en que el usuario los nombra.
    assert resp.answer.index("CB · Chubb") < resp.answer.index("UNH · UnitedHealth")
    types = [s["type"] for s in resp.sources]
    assert types.count("market_price") == 2
    assert types.count("financial_fact") == 2


def test_orden_de_la_pregunta_se_respeta(db):
    _watchlist(db)
    resp = _ask(db, "¿Qué PER tienen UNH y CB?")
    assert resp.answer.index("UNH · UnitedHealth") < resp.answer.index("CB · Chubb")


def test_un_ticker_sin_datos_lo_dice_y_no_inventa(db):
    cb = _company(db, "CB", "Chubb Limited")
    _company(db, "UNH", "UnitedHealth Group")
    _priced(db, cb, 280, 22.4)
    resp = _ask(db, "PER de CB y UNH")
    assert "PER sobre BPA anual: 12,50 veces" in resp.answer
    assert "PER: sin dato calculable guardado" in resp.answer
    assert "Precio: sin cotización válida almacenada." in resp.answer


def test_un_solo_ticker_sigue_por_la_ficha(db):
    _watchlist(db)
    resp = answer_data_question(db, "¿cuál es el PER de UNH?")
    assert resp is not None
    assert resp.llm_trace["path"] == "company_quote"
    assert "20,00 veces" in resp.answer


def test_cinco_tickers_no_vuelcan_todo(db):
    for ticker in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        _company(db, ticker, ticker)
    assert answer_data_question(db, "PER de AAA, BBB, CCC, DDD y EEE") is None


def test_orden_de_compra_con_dos_tickers_no_se_toca(db):
    _watchlist(db)
    assert answer_data_question(db, "vende CB y compra UNH a precio de mercado") is None
