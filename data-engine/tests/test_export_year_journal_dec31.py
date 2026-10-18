"""Lista 13.2: el export anual no puede perder los asientos del 31 de diciembre.

created_at es DateTime con tz: filtrar con "<= date(year,12,31)" corta a
medianoche y excluye cualquier asiento creado durante el dia 31. El filtro
correcto es el rango semiabierto [< 1 de enero del ano siguiente].
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.export import export_year
from app.models.entities import Base, Company, DecisionJournalEntry


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = 1
        yield session


def _payload(response) -> dict:
    async def _collect():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        return b"".join(chunks)

    return json.loads(asyncio.run(_collect()))


def _entry(db, created_at: datetime) -> DecisionJournalEntry:
    company = Company(
        ticker="TSTX31", name="TSTX31", exchange="NASDAQ", currency="USD",
        sector="Technology", industry="Software", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    entry = DecisionJournalEntry(
        company_id=company.id,
        decision="buy",
        rationale="test",
        created_at=created_at,
    )
    db.add(entry)
    db.commit()
    return entry


def test_journal_entry_created_on_dec_31_is_exported(db):
    entry = _entry(db, datetime(2026, 12, 31, 15, 30, tzinfo=UTC))
    response = export_year(2026, format="json", db=db)
    payload = _payload(response)
    ids = [row["id"] for row in payload["journal_entries"]]
    assert entry.id in ids, "un asiento creado el 31 de diciembre no puede faltar del export"


def test_journal_entry_from_next_year_is_not_exported(db):
    entry = _entry(db, datetime(2027, 1, 1, 0, 0, tzinfo=UTC))
    response = export_year(2026, format="json", db=db)
    payload = _payload(response)
    ids = [row["id"] for row in payload["journal_entries"]]
    assert entry.id not in ids
