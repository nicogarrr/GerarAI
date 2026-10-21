"""Tracked (stored_evidence_only) generation must see already-stored news.

Antes: stored_evidence_only reducia la evidencia al recibo SEC; las noticias
guardadas en NewsEvent no llegaban a la tesis (a diferencia de la manual).
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent
from app.services.thesis_evidence_service import ThesisEvidenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db):
    c = Company(ticker="HYMC", name="Hycroft", exchange="", currency="USD", sector="Mining",
                industry="Gold", company_type="holding", valuation_model="unassigned",
                special_sources=[], special_risks=[], factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("collect_stored no debe usar la red")
    for name in ("_fetch_cik", "_fetch_company_facts", "_fetch_filings", "_fetch_earnings", "_fetch_ir"):
        monkeypatch.setattr(ThesisEvidenceService, name, boom, raising=False)


def test_collect_stored_reads_news_without_network(db, monkeypatch):
    _no_network(monkeypatch)
    c = _company(db)
    db.add(NewsEvent(company_id=c.id, title="Hycroft anuncia financiación", source="Reuters",
                     date=datetime(2026, 10, 1, tzinfo=UTC), url="https://example.test/n1",
                     materiality_score=80))
    db.commit()
    out = ThesisEvidenceService().collect_stored(db, c)
    news = out["sources"]["news"]
    assert news["status"] == "ok"
    assert [i["title"] for i in news["items"]] == ["Hycroft anuncia financiación"]
    assert set(out["sources"]) == {"news", "transcript", "external_theses"}


def test_collect_stored_without_news_is_pending_not_error(db, monkeypatch):
    _no_network(monkeypatch)
    c = _company(db)
    out = ThesisEvidenceService().collect_stored(db, c)
    assert out["sources"]["news"]["status"] == "pending"
