"""GET filings con la SEC sin respuesta: solo la primera carga espera el presupuesto.

Antes cada carga de /companies/{ticker}/filings volvia a esperar los 4 s del
presupuesto para acabar sirviendo lo mismo (la base, ``unavailable``). Ahora
una memoria corta hace que las siguientes respondan al momento con la misma
salida; un fallo rapido (404/403, ticker sin CIK) no la activa.
"""

import asyncio
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document
from app.services import company_events_service
from app.services.company_events_service import CompanyEventsService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker, cik):
    company = Company(
        ticker=ticker,
        name=f"{ticker} Inc.",
        exchange="NASDAQ",
        currency="USD",
        sector="Tech",
        industry="Tech",
        cik=cik,
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(
        Document(
            company_id=company.id,
            title=f"10-K 2025 - {ticker}",
            source_type="SEC",
            source_url=None,
            storage_uri=None,
            published_at=None,
            checksum=f"k-{ticker}",
            metadata_={},
            tenant_id="tenant-test",
        )
    )
    db.commit()
    return company


class _Hang:
    def __init__(self):
        self.calls = 0

    async def __call__(self, *_args):
        self.calls += 1
        await asyncio.sleep(3)
        return {"filings": {"recent": {}}}


def _timed(coro):
    start = time.monotonic()
    out = asyncio.run(coro)
    return out, time.monotonic() - start


def _sin_reloj(out):
    return {k: v for k, v in out.items() if k != "as_of"}


def test_sec_sin_respuesta_solo_la_primera_carga_espera(db, monkeypatch):
    monkeypatch.setattr(company_events_service, "FILINGS_SEC_BUDGET_SECONDS", 0.4)
    aapl = _company(db, "AAPL", "0000320193")
    msft = _company(db, "MSFT", "0000789019")
    hang = _Hang()

    primera, t1 = _timed(CompanyEventsService(db, submissions_fetcher=hang).get_filings(aapl))
    assert t1 >= 0.35
    segunda, t2 = _timed(CompanyEventsService(db, submissions_fetcher=hang).get_filings(aapl))
    assert t2 < 0.2
    # Misma respuesta que la carga que si espero.
    assert _sin_reloj(segunda) == _sin_reloj(primera)
    assert segunda["sec_status"] == "unavailable"
    assert "no respondió a tiempo" in segunda["note"]
    assert segunda["documents"]

    # Otro emisor tampoco espera mientras dura la memoria.
    otra, t3 = _timed(CompanyEventsService(db, submissions_fetcher=hang).get_filings(msft))
    assert t3 < 0.2
    assert otra["sec_status"] == "unavailable"


def test_la_memoria_caduca_y_se_vuelve_a_preguntar(db, monkeypatch):
    monkeypatch.setattr(company_events_service, "FILINGS_SEC_BUDGET_SECONDS", 0.3)
    aapl = _company(db, "AAPL", "0000320193")
    _timed(CompanyEventsService(db, submissions_fetcher=_Hang()).get_filings(aapl))
    company_events_service._FAILED_UNTIL[company_events_service._SEC_DOWN_KEY] = time.monotonic() - 1

    async def ok(_cik):
        return {"filings": {"recent": {}}}

    out, _ = _timed(CompanyEventsService(db, submissions_fetcher=ok).get_filings(aapl))
    assert out["sec_status"] == "ok"
    assert (
        company_events_service._FAILED_UNTIL.get(company_events_service._SEC_DOWN_KEY, 0) < time.monotonic()
    )


def test_fallo_rapido_no_activa_la_memoria(db, monkeypatch):
    monkeypatch.setattr(company_events_service, "FILINGS_SEC_BUDGET_SECONDS", 0.3)
    aapl = _company(db, "AAPL", "0000320193")
    sin_cik = _company(db, "SAN", None)

    async def none(*_args):
        return None

    out, _ = _timed(CompanyEventsService(db, submissions_fetcher=none).get_filings(aapl))
    assert out["sec_status"] == "unavailable"
    _timed(CompanyEventsService(db, cik_fetcher=none).get_filings(sin_cik))
    assert company_events_service._SEC_DOWN_KEY not in company_events_service._FAILED_UNTIL


def test_cik_lento_tambien_activa_la_memoria(db, monkeypatch):
    monkeypatch.setattr(company_events_service, "FILINGS_SEC_BUDGET_SECONDS", 0.3)
    sin_cik = _company(db, "SAN", None)
    hang = _Hang()
    _timed(CompanyEventsService(db, cik_fetcher=hang, submissions_fetcher=hang).get_filings(sin_cik))
    out, t = _timed(CompanyEventsService(db, cik_fetcher=hang, submissions_fetcher=hang).get_filings(sin_cik))
    assert t < 0.2
    assert out["sec_status"] == "unavailable"
    assert "no respondió a tiempo" in out["note"]


@pytest.mark.parametrize("ttl", [company_events_service.FILINGS_SEC_DOWN_TTL_SECONDS])
def test_memoria_corta(ttl):
    assert 30 <= ttl <= 300
