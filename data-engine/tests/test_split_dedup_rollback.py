"""Regresion Auditoria (parche dedup batch): rollback entre syncs de splits.

Mismo contraejemplo que en dividendos: commit fallido, rollback y reintento
en la MISMA sesion. La cache de dedup en db.info solo aprende inserts tras
un commit con exito; si los aprende pendientes, el reintento dedupa contra
filas que ya no existen y la ingesta se pierde en silencio.
"""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, CorporateAction
from app.services.split_ingestion_service import SplitIngestionService

SPLIT_PAYLOAD = [
    {"symbol": "AAPL", "date": "2020-08-31", "numerator": 4, "denominator": 1, "label": "4-for-1 split"},
    {"symbol": "AAPL", "date": "2014-06-09", "numerator": 7, "denominator": 1, "label": "7-for-1 split"},
]


class _FakeYahoo:
    async def splits(self, ticker: str):
        raise RuntimeError("yahoo down")


class _FakeFMP:
    async def splits(self, ticker: str):
        return SPLIT_PAYLOAD


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def company(db):
    company = Company(
        ticker="AAPL", name="AAPL", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_failed_commit_rollback_retry_reingests_splits(db, company, monkeypatch):
    service = SplitIngestionService(fmp=_FakeFMP(), yahoo=_FakeYahoo())
    real_commit = db.commit
    calls = {"n": 0}

    def fail_first_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("commit caido (simulado)")
        return real_commit()

    monkeypatch.setattr(db, "commit", fail_first_commit)
    with pytest.raises(RuntimeError, match="commit caido"):
        asyncio.run(service.sync_company(db, ticker="AAPL"))
    db.rollback()
    result = asyncio.run(service.sync_company(db, ticker="AAPL"))
    assert result["status"] == "ok"
    assert result["inserted"] == len(SPLIT_PAYLOAD), (
        f"reintento tras rollback perdio la ingesta: {result['inserted']} inserts, "
        f"{result['existing']} 'existentes' fantasma"
    )
    persisted = db.scalars(
        select(CorporateAction).where(CorporateAction.company_id == company.id)
    ).all()
    assert len(persisted) == len(SPLIT_PAYLOAD)
