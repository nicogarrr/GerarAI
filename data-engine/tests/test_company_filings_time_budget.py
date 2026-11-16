"""GET filings con la SEC caida no puede colgar la peticion ~15 s.

Los reintentos con backoff y el fallback EFTS corren dentro del GET; ahora hay
un presupuesto total y, al agotarse, se sirve la base con estado honesto.
"""

import asyncio

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


def _company(db, cik):
    company = Company(
        ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik=cik, company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(Document(
        company_id=company.id, title="10-K 2025 - AAPL",
        source_type="SEC", source_url=None, storage_uri=None,
        published_at=None, checksum="k", metadata_={}, tenant_id="tenant-test",
    ))
    db.commit()
    return company


async def _hang(*_args):
    # SEC caida: reintentos + EFTS. 3 s basta para distinguir del tope.
    await asyncio.sleep(3)
    return {"filings": {"recent": {}}}


class _BudgetLoop(asyncio.SelectorEventLoop):
    """Advance idle timer deadlines without measuring runner CPU contention."""

    def __init__(self):
        self.clock = 0.0
        super().__init__()

    def time(self):
        return self.clock

    def _run_once(self):
        if not self._ready and self._scheduled:
            self.clock = max(self.clock, self._scheduled[0]._when)
        super()._run_once()


def _timed(coro):
    with asyncio.Runner(loop_factory=_BudgetLoop) as runner:
        loop = runner.get_loop()
        start = loop.time()
        out = runner.run(coro)
        return out, loop.time() - start


def test_submissions_lentas_respetan_el_presupuesto(db, monkeypatch):
    monkeypatch.setattr(company_events_service, "FILINGS_SEC_BUDGET_SECONDS", 0.3, raising=False)
    company = _company(db, "0000320193")
    service = CompanyEventsService(db, submissions_fetcher=_hang)
    out, elapsed = _timed(service.get_filings(company))
    assert elapsed == pytest.approx(0.3)
    assert out["sec_status"] == "unavailable"
    assert out["filings"] == []
    assert out["documents"] and out["documents"][0]["source_type"] == "SEC"
    assert "no respondió a tiempo" in out["note"]


def test_cik_lento_tambien_cuenta_en_el_presupuesto(db, monkeypatch):
    monkeypatch.setattr(company_events_service, "FILINGS_SEC_BUDGET_SECONDS", 0.3, raising=False)
    company = _company(db, None)
    service = CompanyEventsService(db, cik_fetcher=_hang, submissions_fetcher=_hang)
    out, elapsed = _timed(service.get_filings(company))
    assert elapsed == pytest.approx(0.3)
    assert out["sec_status"] == "unavailable"
    assert out["documents"]


def test_presupuesto_por_defecto_es_corto():
    assert company_events_service.FILINGS_SEC_BUDGET_SECONDS <= 5
