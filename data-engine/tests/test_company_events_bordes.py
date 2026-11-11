"""company_events_service: fetchers reales con clientes doblados (degradacion
honesta), parseos de fecha, mezcla calendario/EPS, accession invalida, limite
de filings y filas de timeline sin fuente.

Red siempre doblada (objetos finnhub/sec falsos en la instancia); base SQLite
real en memoria para stored_timeline_events, siguiendo el patron de
test_company_timeline_events.py.

No se prueba aqui: el flujo feliz ya cubierto en test_company_events_service.py
y test_company_timeline_events.py, ni la capa de rutas (test_thin_routes_batch5).
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    DividendRecord,
    EarningsDate,
    NewsEvent,
)
from app.services.company_events_service import (
    CompanyEventsService,
    _timeline_day,
    _timeline_float,
    stored_timeline_events,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = None
        yield session
    engine.dispose()


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik="0000320193",
        company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


class _FakeFinnhub:
    """Doble minimo: configured() y un _get async con payload o excepcion."""

    def __init__(self, configured, payload=None, exc=None):
        self._configured = configured
        self._payload = payload
        self._exc = exc
        self.calls = []

    def configured(self):
        return self._configured

    async def _get(self, path, params):
        self.calls.append((path, params))
        if self._exc is not None:
            raise self._exc
        return self._payload


class _FakeSEC:
    """Doble minimo: submissions() y cik_for_ticker() async."""

    def __init__(self, submissions_payload=None, submissions_exc=None,
                 cik="0000320193", cik_exc=None):
        self._submissions_payload = submissions_payload
        self._submissions_exc = submissions_exc
        self._cik = cik
        self._cik_exc = cik_exc

    async def submissions(self, cik):
        if self._submissions_exc is not None:
            raise self._submissions_exc
        return self._submissions_payload

    async def cik_for_ticker(self, ticker, entity_name=None):
        if self._cik_exc is not None:
            raise self._cik_exc
        return self._cik


# -- Fetchers reales (degradacion honesta) ------------------------------------


def test_fetch_calendar_chunk_no_configurado(db, monkeypatch):
    service = CompanyEventsService(db)
    fake = _FakeFinnhub(configured=False)
    monkeypatch.setattr(service, "_finnhub", fake)
    assert _run(service._fetch_calendar_chunk("2026-01-01", "2026-02-01")) is None
    assert fake.calls == []


def test_fetch_calendar_chunk_error_y_tipos(db, monkeypatch):
    service = CompanyEventsService(db)
    monkeypatch.setattr(service, "_finnhub", _FakeFinnhub(True, exc=RuntimeError("caido")))
    assert _run(service._fetch_calendar_chunk("2026-01-01", "2026-02-01")) is None
    payload = {"earningsCalendar": []}
    monkeypatch.setattr(service, "_finnhub", _FakeFinnhub(True, payload=payload))
    assert _run(service._fetch_calendar_chunk("2026-01-01", "2026-02-01")) is payload
    monkeypatch.setattr(service, "_finnhub", _FakeFinnhub(True, payload=["no", "dict"]))
    assert _run(service._fetch_calendar_chunk("2026-01-01", "2026-02-01")) is None


def test_fetch_eps_history_degradaciones(db, monkeypatch):
    service = CompanyEventsService(db)
    monkeypatch.setattr(service, "_finnhub", _FakeFinnhub(False))
    assert _run(service._fetch_eps_history("AAPL")) is None
    monkeypatch.setattr(service, "_finnhub", _FakeFinnhub(True, exc=RuntimeError("caido")))
    assert _run(service._fetch_eps_history("AAPL")) is None
    rows = [{"period": "2026-06-30"}]
    monkeypatch.setattr(service, "_finnhub", _FakeFinnhub(True, payload=rows))
    assert _run(service._fetch_eps_history("AAPL")) is rows
    monkeypatch.setattr(service, "_finnhub", _FakeFinnhub(True, payload={"no": "lista"}))
    assert _run(service._fetch_eps_history("AAPL")) is None


def test_fetch_submissions_degradaciones(db, monkeypatch):
    service = CompanyEventsService(db)
    monkeypatch.setattr(service, "_sec", _FakeSEC(submissions_exc=RuntimeError("caido")))
    assert _run(service._fetch_submissions("0000320193")) is None
    payload = {"filings": {"recent": {}}}
    monkeypatch.setattr(service, "_sec", _FakeSEC(submissions_payload=payload))
    assert _run(service._fetch_submissions("0000320193")) is payload
    monkeypatch.setattr(service, "_sec", _FakeSEC(submissions_payload=["no", "dict"]))
    assert _run(service._fetch_submissions("0000320193")) is None


def test_fetch_cik_degradacion(db, monkeypatch):
    service = CompanyEventsService(db)
    monkeypatch.setattr(service, "_sec", _FakeSEC(cik_exc=RuntimeError("caido")))
    assert _run(service._fetch_cik("AAPL")) is None
    monkeypatch.setattr(service, "_sec", _FakeSEC(cik="0000320193"))
    assert _run(service._fetch_cik("AAPL")) == "0000320193"


# -- Parseos y mezcla ----------------------------------------------------------


def test_parse_day_bordes(db):
    service = CompanyEventsService(db)
    assert service._parse_day(None) is None
    assert service._parse_day("") is None
    assert service._parse_day("basura") is None
    assert service._parse_day("2026-07-30") == date(2026, 7, 30)
    assert service._parse_day("2026-07-30T23:59:59") == date(2026, 7, 30)


def test_history_eps_sin_periodo_omitido(db):
    service = CompanyEventsService(db)
    out = service._history([], [
        {"period": "", "estimate": 9.9},
        {"period": "2026-06-30", "quarter": 2, "year": 2026,
         "estimate": 1.0, "actual": 1.1, "surprisePercent": 2.0},
    ], date(2026, 9, 1))
    assert len(out) == 1
    assert out[0]["period"] == "2026-06-30"
    assert out[0]["eps_estimate"] == 1.0
    assert out[0]["eps_actual"] == 1.1
    assert out[0]["source"] == "Finnhub /stock/earnings"


def test_history_no_pisa_estimaciones_del_calendario(db):
    service = CompanyEventsService(db)
    calendar = [{
        "date": "2026-06-30", "quarter": 2, "year": 2026,
        "epsEstimate": 2.0, "epsActual": 1.9,
        "revenueEstimate": 100.0, "revenueActual": 101.0,
    }]
    eps = [{"period": "2026-06-30", "estimate": 9.9, "actual": 8.8,
            "surprisePercent": 5.0}]
    out = service._history(calendar, eps, date(2026, 9, 1))
    assert len(out) == 1
    row = out[0]
    assert row["eps_estimate"] == 2.0
    assert row["eps_actual"] == 1.9
    assert row["eps_surprise_percent"] == 5.0


def test_map_submissions_accession_invalida_omitida(db):
    service = CompanyEventsService(db)
    payload = {"filings": {"recent": {
        "accessionNumber": ["abc-def"],
        "form": ["10-Q"],
        "primaryDocument": ["doc.htm"],
        "filingDate": ["2026-08-01"],
        "reportDate": ["2026-06-30"],
    }}}
    assert service._map_submissions("320193", payload, "AAPL", 10) == []


def test_map_submissions_rompe_al_limite(db):
    service = CompanyEventsService(db)
    payload = {"filings": {"recent": {
        "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
        "form": ["10-Q", "8-K"],
        "primaryDocument": ["q.htm", "k.htm"],
        "filingDate": ["2026-08-01", "2026-09-01"],
        "reportDate": ["2026-06-30", "2026-09-01"],
    }}}
    items = service._map_submissions("320193", payload, "AAPL", 1)
    assert len(items) == 1
    assert items[0]["form"] == "10-Q"
    assert items[0]["accession"] == "0000320193-26-000001"


def test_timeline_float_y_day_bordes():
    assert _timeline_float("abc") is None
    assert _timeline_float(None) is None
    assert _timeline_float("2.5") == 2.5
    assert _timeline_float(float("nan")) is None
    assert _timeline_day(None) is None
    assert _timeline_day("") is None
    assert _timeline_day("basura") is None
    assert _timeline_day("2026-08-10") == date(2026, 8, 10)


# -- Timeline: filas sin fuente -------------------------------------------------


def test_stored_timeline_omite_filas_sin_fuente(db):
    company = _company(db)
    # Las columnas source son NOT NULL con default Python ("fmp"/"manual"):
    # el "sin fuente" real que ejerce el guard es la cadena vacia.
    db.add(EarningsDate(ticker="AAPL", event_date=date(2026, 7, 30),
                        source="", source_label=""))
    db.add(DividendRecord(company_id=company.id, ex_date=date(2026, 8, 10),
                          amount=Decimal("0.25"), currency="USD", source=""))
    db.add(NewsEvent(company_id=company.id,
                     date=datetime(2026, 9, 1, 14, tzinfo=UTC),
                     title="8-K sin fuente", source="", url=None,
                     event_type="new_filing"))
    db.commit()
    out = stored_timeline_events(db, company, date(2026, 1, 1), date(2026, 12, 31))
    assert out == []
