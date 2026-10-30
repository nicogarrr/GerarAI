"""Cerebro lee el nivel DCA (con «sin nivel» si el motor no está) y el motor de valoración."""
import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Date, DateTime, Integer, Numeric, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

import app.models as models
from app.models.entities import Base, Company
from app.services.brain_data_tools import answer_data_question
from app.services.chat_service import ChatService
from app.services.dca_level_reader import dca_engine_available, read_dca_levels


class _FakeBase(DeclarativeBase):
    pass


class FakeDcaSignalState(_FakeBase):
    """Mismas columnas que lee el lector; la tabla real llega con la PR del motor."""

    __tablename__ = "dca_signal_states"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(20))
    level: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(7))
    signal_date: Mapped[date] = mapped_column(Date)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    params_version: Mapped[str] = mapped_column(String(40))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


@pytest.fixture
def without_engine(monkeypatch):
    monkeypatch.delattr(models, "DcaSignalState", raising=False)


@pytest.fixture
def with_engine(monkeypatch):
    # #2310 ya trae el modelo real: el lector usa models.DcaSignalState tal cual.
    assert getattr(models, "DcaSignalState", None) is not None


def _company(db, ticker, currency="USD"):
    comp = Company(ticker=ticker, name=f"{ticker} Corp", exchange="NYSE", currency=currency,
                   company_type="operating", valuation_model="dcf")
    db.add(comp)
    db.flush()
    return comp


def _state(db, symbol, level, *, tenant=1, status="forming", close="100"):
    from app.models.entities import DcaSignalState

    if tenant != db.info.get("tenant_id"):
        _other_tenant_dca_row(db, tenant=tenant, symbol=symbol, level=level, status=status)
        return
    db.add(DcaSignalState(tenant_id=tenant, symbol=symbol, level=level, status=status, period="2026-10",
                          signal_date=date(2026, 10, 26), close=Decimal(close), currency="USD",
                          metrics={}, level_prices={}, sources=[], data_source="test",
                          params_version="nico-v1", evaluated_at=datetime(2026, 10, 27, tzinfo=UTC)))


def test_without_dca_engine_the_answer_is_sin_nivel(db, without_engine):
    _company(db, "POOL")
    db.commit()
    assert dca_engine_available() is False
    assert read_dca_levels(db, 1) is None
    resp = asyncio.run(ChatService().answer(db, "¿Qué nivel DCA tiene POOL?", "portfolio", None))
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.llm_trace["path"] == "dca_level"
    assert resp.answer.startswith("Sin nivel DCA")
    assert "4X" not in resp.answer


def test_named_ticker_level_with_forming_month(db, with_engine):
    _company(db, "POOL")
    _state(db, "POOL", 4, close="301.5")
    _state(db, "POOL", 1, tenant=2)
    db.commit()
    resp = answer_data_question(db, "nivel dca de POOL")
    assert resp is not None
    assert "**POOL: 4X DCA**" in resp.answer or "**POOL: 4X DCA** (" in resp.answer
    assert "301,50 USD" in resp.answer
    assert "mes en formación" in resp.answer
    assert "no una orden de compra" in resp.answer


def test_all_levels_grouped_buy_first_then_trims(db, with_engine):
    for symbol, level in (("POOL", 4), ("UBER", 3), ("KKR", 3), ("AAPL", 1), ("ABCL", -1)):
        _state(db, symbol, level, status="confirmed")
    _state(db, "SECRET", 4, tenant=2)
    db.commit()
    resp = answer_data_question(db, "¿Cómo están mis niveles de compra?")
    assert resp is not None
    text = resp.answer
    assert text.index("4X DCA: POOL") < text.index("3X DCA: KKR, UBER") < text.index("1X DCA: AAPL")
    assert text.index("1X DCA") < text.index("RECORTE LIGERO: ABCL")
    assert "SECRET" not in text
    assert "en formación" not in text


def test_named_ticker_without_state_says_not_evaluated(db, with_engine):
    _company(db, "HIMS")
    db.commit()
    resp = answer_data_question(db, "¿En qué zona de compra está HIMS?")
    assert resp is not None
    assert "HIMS: sin nivel DCA guardado todavía" in resp.answer


def test_engine_valuation_answer_uses_the_engine_output(db, monkeypatch):
    comp = _company(db, "UBER")
    db.commit()
    from app.services import valuation_service

    def fake_value(self, _db, company, **_kw):
        assert company.id == comp.id
        return {"model_type": "dcf", "publishable": False, "bear_value": 60.0, "base_value": 90.0,
                "bull_value": 130.0, "expected_value": 92.5, "current_price": 75.0,
                "margin_of_safety": 0.189, "publication_blockers": ["WACC sin fuente datada"],
                "trace": {"price_as_of": "2026-10-24"}}

    monkeypatch.setattr(valuation_service.ValuationService, "value_company", fake_value)
    resp = asyncio.run(ChatService().answer(db, "¿Cuál es el valor justo de UBER?", "portfolio", None))
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.llm_trace["path"] == "engine_valuation"
    assert "orientativo" in resp.answer
    assert "bajista 60,00 USD, base 90,00 USD, alcista 130,00 USD, esperado 92,50 USD" in resp.answer
    assert "Precio usado 75,00 USD (cierre del 2026-10-24)" in resp.answer
    assert "Margen de seguridad del motor: 18,9 %" in resp.answer
    assert "WACC sin fuente datada" in resp.answer
    assert resp.sources[0]["url"] == "/research/UBER?view=valuation"


def test_engine_valuation_answer_adr_shows_per_adr_scenarios(db, monkeypatch):
    """BABA 8:1: motor por ordinaria (base 25, esperado 25), precio por ADR 160.

    Por ADR: base 25 x 8 = 200; margen (200 − 160) / 200 = +20 %. Antes la
    respuesta ponía «base 25,00 USD» junto a «Precio usado 160,00 USD».
    """
    comp = _company(db, "BABA")
    db.commit()
    from app.services import valuation_service

    def fake_value(self, _db, company, **_kw):
        assert company.id == comp.id
        return {"model_type": "dcf", "publishable": True, "bear_value": 15.0, "base_value": 25.0,
                "bull_value": 35.0, "expected_value": 25.0, "current_price": 160.0,
                "margin_of_safety": 0.2, "adr_ratio": 8.0,
                "listed_share_values": {"bear": 120.0, "base": 200.0, "bull": 280.0, "expected": 200.0},
                "trace": {"price_as_of": "2026-10-24"}}

    monkeypatch.setattr(valuation_service.ValuationService, "value_company", fake_value)
    resp = asyncio.run(ChatService().answer(db, "¿Cuál es el valor justo de BABA?", "portfolio", None))
    assert resp.llm_trace["path"] == "engine_valuation"
    assert ("Escenarios por ADR (1 ADR = 8 acciones ordinarias): bajista 120,00 USD, base 200,00 USD, "
            "alcista 280,00 USD, esperado 200,00 USD") in resp.answer
    assert "base 25,00 USD" not in resp.answer
    assert "Precio usado 160,00 USD" in resp.answer


def test_thesis_margin_question_keeps_the_thesis_route(db, monkeypatch):
    _company(db, "UBER")
    db.commit()
    from app.services import valuation_service

    def boom(*_a, **_k):
        raise AssertionError("el motor no debe usarse para una pregunta de tesis")

    monkeypatch.setattr(valuation_service.ValuationService, "value_company", boom)
    resp = answer_data_question(db, "¿Cuál es el margen de seguridad de la tesis de UBER? ¿Está infravalorada?")
    assert resp is not None
    assert resp.llm_trace["path"] == "thesis_valuation"


def test_engine_failure_is_said_not_invented(db, monkeypatch):
    _company(db, "AAPL")
    db.commit()
    from app.services import valuation_service

    def boom(*_a, **_k):
        raise RuntimeError("sin hechos")

    monkeypatch.setattr(valuation_service.ValuationService, "value_company", boom)
    resp = answer_data_question(db, "¿AAPL está infravalorada según el DCF?")
    assert resp is not None
    assert "no ha podido valorar AAPL" in resp.answer


def _other_tenant_dca_row(db, *, tenant, symbol, level, company_id=None, status="closed"):
    """Fila de OTRO tenant: el ORM bloquea escrituras cruzadas, se inserta en SQL."""
    from sqlalchemy import text as _text

    db.execute(_text(
        "INSERT INTO dca_signal_states (tenant_id, symbol, company_id, level, status, period, signal_date,"
        " close, metrics, level_prices, sources, params_version, evaluated_at, data_source, created_at,"
        " updated_at) VALUES (:t, :s, :c, :l, :st, '2026-09', '2026-09-30', 100, '{}', '{}', '[]',"
        " 'nico-v1', '2026-09-30', 'test', '2026-09-30', '2026-09-30')"
    ), {"t": tenant, "s": symbol, "c": company_id, "l": level, "st": status})


def test_stale_dca_level_is_said_not_given_as_today(db, with_engine):
    """Un nivel con el último cierre más viejo que dca_max_data_age_days (14) se avisa."""
    from app.services.brain_context_tools import dca_answer

    comp = _company(db, "POOL")
    _state(db, "POOL", 4, status="confirmed")  # último cierre 2026-10-26
    _state(db, "UBER", 2, status="confirmed")
    db.commit()
    fresh = dca_answer(db, 1, comp, today=date(2026, 10, 30)).answer
    assert "desactualizado" not in fresh.lower()
    stale = dca_answer(db, 1, comp, today=date(2026, 12, 1)).answer
    assert "**POOL: 4X DCA**" in stale
    assert "Ojo: desactualizado, el último cierre es de hace 36 días" in stale
    summary = dca_answer(db, 1, None, today=date(2026, 12, 1)).answer
    assert "Desactualizados (último cierre de hace más de 14 días" in summary
    assert "POOL, UBER." in summary
