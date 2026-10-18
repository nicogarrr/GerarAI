"""FinnhubProfileBackfill contract tests (PR-D resto).

The backfill must stay inside the free-tier rate budget (bounded companies
per run), write only what the API returns (a quote-dated market cap, never
an ingest-dated one), leave good Company fields untouched, and resume from
the per-company finnhub_profile Document instead of re-burning budget.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, FinancialFact
from app.services.finnhub_profile_backfill import FinnhubProfileBackfill


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


class _Client:
    """Stub httpx.Client: payload por (fragmento de URL, ticker)."""

    def __init__(self, quotes=None, profiles=None):
        self.quotes = quotes or {}
        self.profiles = profiles or {}
        self.calls = []

    def get(self, url, params=None):
        ticker = (params or {}).get("symbol", "")
        self.calls.append(url)
        if "/quote" in url:
            data = self.quotes.get(ticker)
        else:
            data = self.profiles.get(ticker)
        return _Resp(data or {})

    def close(self):
        pass


class _Settings:
    finnhub_api_key = "test-key"


class _NoKey:
    finnhub_api_key = None


def _company(db: Session, ticker: str, **overrides) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="UNKNOWN", currency="USD",
        sector="", industry="", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    for key, value in overrides.items():
        setattr(company, key, value)
    db.add(company)
    db.commit()
    return company


def test_backfill_fills_profile_and_quote_dated_market_cap(db):
    company = _company(db, "XYZ", exchange="NASDAQ")
    client = _Client(
        quotes={"XYZ": {"c": 25.5, "t": int(datetime(2026, 10, 16, 20, 0, tzinfo=UTC).timestamp())}},
        profiles={"XYZ": {
            "name": "Xylem Robotics Inc", "exchange": "NASDAQ NMS - GLOBAL MARKET",
            "currency": "USD", "country": "US", "finnhubIndustry": "Technology",
            "marketCapitalization": 1234.0,
        }},
    )
    service = FinnhubProfileBackfill(settings=_Settings(), client=client)
    result = service.backfill(db, sleep_between_calls=0, today=date(2026, 10, 17))

    assert result["status"] == "ok"
    assert result["procesadas"] == 1
    assert result["market_cap"] == 1
    assert company.name == "Xylem Robotics Inc"
    # exchange conocido no se pisa con el valor del perfil (regla anti-ADR).
    assert company.exchange == "NASDAQ"
    assert company.domicile_country == "US"
    cap = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
        )
    )
    assert cap is not None
    assert cap.value == Decimal("1234000000")
    assert cap.period == "2026-10-16"  # sesion de la quote, no el dia de ingesta
    assert cap.source_type == "Finnhub"
    assert cap.is_reported is True
    doc = db.scalar(select(Document).where(Document.company_id == company.id))
    assert doc.source_type == "finnhub_profile"
    assert doc.metadata_["quote_date"] == "2026-10-16"
    assert doc.metadata_["market_cap_written"] is True


def test_backfill_never_overwrites_good_fields(db):
    company = _company(db, "ABC", name="Real Name", exchange="NASDAQ", domicile_country="GB")
    client = _Client(
        quotes={"ABC": {"c": 10.0, "t": int(datetime(2026, 10, 16, 20, 0, tzinfo=UTC).timestamp())}},
        profiles={"ABC": {"name": "Otro Nombre", "exchange": "LSE", "country": "US"}},
    )
    service = FinnhubProfileBackfill(settings=_Settings(), client=client)
    service.backfill(db, sleep_between_calls=0, today=date(2026, 10, 17))
    assert company.name == "Real Name"
    assert company.exchange == "NASDAQ"
    assert company.domicile_country == "GB"


def test_placeholder_exchange_promotes_only_name_adr_stays_candidate(db):
    """Objecion de revision: SAN con exchange placeholder -> Finnhub resuelve
    el ADR (NYSE/USD/US); promover identidad o market_cap escribiria OTRO
    instrumento. Solo el nombre se promueve; el resto queda declarado como
    candidato en metadata del Document."""
    company = _company(db, "SAN")  # exchange UNKNOWN por defecto
    client = _Client(
        quotes={"SAN": {"c": 4.9, "t": int(datetime(2026, 10, 16, 20, 0, tzinfo=UTC).timestamp())}},
        profiles={"SAN": {
            "name": "Banco Santander SA", "exchange": "NYSE",
            "currency": "USD", "country": "US",
            "marketCapitalization": 80000.0,
        }},
    )
    service = FinnhubProfileBackfill(settings=_Settings(), client=client)
    result = service.backfill(db, sleep_between_calls=0, today=date(2026, 10, 17))

    assert company.name == "Banco Santander SA"
    assert company.exchange == "UNKNOWN"  # nunca el NYSE del ADR
    assert company.currency == "USD"  # ya era USD; no promovido desde perfil
    assert company.domicile_country in (None, "")
    assert result["market_cap"] == 0
    assert db.scalar(
        select(FinancialFact).where(FinancialFact.company_id == company.id)
    ) is None
    doc = db.scalar(select(Document).where(Document.company_id == company.id))
    candidates = doc.metadata_["adr_candidates"]
    assert candidates["exchange"] == "NYSE"
    assert candidates["country"] == "US"
    assert candidates["market_cap_usd_millions"] == "80000.0"
    assert doc.metadata_["market_cap_written"] is False


def test_backfill_skips_companies_checked_recently(db):
    company = _company(db, "OLD")
    db.add(Document(company_id=company.id, title="Finnhub profile backfill 2026-10-10",
                    source_type="finnhub_profile", metadata_={"date": "2026-10-10"}))
    db.commit()
    client = _Client(profiles={"OLD": {"name": "No deberia consultarse"}})
    service = FinnhubProfileBackfill(settings=_Settings(), client=client)
    result = service.backfill(db, sleep_between_calls=0, today=date(2026, 10, 17))
    assert result["procesadas"] == 0
    assert client.calls == []


def test_backfill_budget_limits_companies_per_run(db):
    for i in range(5):
        _company(db, f"T{i}")
    client = _Client(profiles={f"T{i}": {"name": f"Nombre {i}"} for i in range(5)})
    service = FinnhubProfileBackfill(settings=_Settings(), client=client)
    result = service.backfill(db, max_companies=2, sleep_between_calls=0, today=date(2026, 10, 17))
    assert result["procesadas"] == 2
    assert result["pendientes_tras_run"] == 3
    assert client.calls == [u for t in ("T0", "T1") for u in
                          ("https://finnhub.io/api/v1/quote", "https://finnhub.io/api/v1/stock/profile2")]


def test_backfill_records_empty_answers_and_does_not_invent(db):
    company = _company(db, "NOP")
    client = _Client(quotes={"NOP": {}}, profiles={"NOP": {}})
    service = FinnhubProfileBackfill(settings=_Settings(), client=client)
    result = service.backfill(db, sleep_between_calls=0, today=date(2026, 10, 17))
    assert result["sin_datos"] == 1
    assert db.scalar(select(FinancialFact).where(FinancialFact.company_id == company.id)) is None
    doc = db.scalar(select(Document).where(Document.company_id == company.id))
    assert doc.metadata_["empty"] is True


def test_backfill_without_quote_date_writes_no_market_cap(db):
    company = _company(db, "NOD")
    client = _Client(
        quotes={"NOD": {}},
        profiles={"NOD": {"name": "Sin Fecha SA", "marketCapitalization": 500.0}},
    )
    service = FinnhubProfileBackfill(settings=_Settings(), client=client)
    result = service.backfill(db, sleep_between_calls=0, today=date(2026, 10, 17))
    assert result["market_cap"] == 0
    assert db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
        )
    ) is None


def test_backfill_without_api_key_writes_nothing(db):
    _company(db, "KEY")
    service = FinnhubProfileBackfill(settings=_NoKey(), client=_Client())
    result = service.backfill(db, sleep_between_calls=0, today=date(2026, 10, 17))
    assert result["status"] == "sin_clave"
    assert db.scalar(select(Document)) is None
