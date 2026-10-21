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


# -- _generate_atomic con tracked + noticias almacenadas ------------------------
from sqlalchemy import select as _select  # noqa: E402

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.models import Company as _Company  # noqa: E402
from app.models import NewsEvent as _News
from app.seed import seed  # noqa: E402
from app.services.thesis_service import ThesisService  # noqa: E402

try:
    from tests.test_thesis_auto_ingest import (  # type: ignore[import-not-found]
        _clean_asts_evidence,
        _seed_evidence_rows,
    )
except ImportError:  # pragma: no cover - ejecucion desde data-engine/tests
    from test_thesis_auto_ingest import _clean_asts_evidence, _seed_evidence_rows  # type: ignore

NEWS_TITLE = "ASTS firma acuerdo comercial con operadora"
RECEIPT = {"status": "ok", "provider": "SEC", "facts_imported": 5}


@pytest.fixture
def tracked_env(monkeypatch):
    init_db()
    seed()
    _clean_asts_evidence()
    calls: list[str] = []

    def spy(name):
        def _fn(self, *a, **k):
            calls.append(name)
            raise AssertionError(f"red invocada en tracked: {name}")
        return _fn

    for name in ("_fetch_cik", "_fetch_company_facts", "_fetch_filings", "_fetch_quote",
                 "_fetch_profile", "_fetch_earnings", "_fetch_ir"):
        monkeypatch.setattr(ThesisEvidenceService, name, spy(name))
    yield calls
    _clean_asts_evidence()


def _tracked_generate(force=True):
    db = SessionLocal()
    try:
        t = ThesisService().generate(
            db, "ASTS", force_new_version=force, stored_evidence_only=True, refresh_receipt=dict(RECEIPT)
        )
        return t.id, t.version, t.executive_summary, t.thesis_markdown, t.input_fingerprint
    finally:
        db.close()


def test_tracked_generate_sees_stored_news_without_network(tracked_env):
    _seed_evidence_rows()
    _id, _v, summary, markdown, _fp = _tracked_generate()
    assert tracked_env == []  # ningun fetch de red
    assert NEWS_TITLE in markdown  # fuentes: noticia almacenada alcanzable
    assert NEWS_TITLE in summary or "ASTS firma acuerdo" in summary  # tarjeta
    assert "Última transcripción: Q4 2024 earnings call transcript" in markdown
    fund = next(line for line in markdown.splitlines() if line.startswith("- Fundamentales:"))
    assert "no intentado" not in fund  # recibo SEC no pisado por collect_stored
    # Las fuentes de red siguen sin entrar en tracked (earnings/IR no inventados).
    assert "Investor Day 2025 Presentation" not in markdown


def test_tracked_news_changes_fingerprint_but_repeat_does_not(tracked_env):
    _seed_evidence_rows()
    id1, v1, *_rest1, fp1 = _tracked_generate(force=True)
    # Sin cambios y sin force: misma version (no hay regeneracion espuria).
    id2, v2, *_rest2, fp2 = _tracked_generate(force=False)
    assert (id2, v2, fp2) == (id1, v1, fp1)
    # Noticia nueva: huella distinta -> version nueva (consecuencia esperada).
    db = SessionLocal()
    try:
        company = db.scalar(_select(_Company).where(_Company.ticker == "ASTS"))
        db.add(_News(company_id=company.id, date=datetime.now(UTC), title="ASTS segunda noticia material",
                     source="press", url="https://example.com/asts-2", summary="x",
                     event_type="partnership", materiality_score=9, impact_direction="positive"))
        db.commit()
    finally:
        db.close()
    id3, v3, *_rest3, fp3 = _tracked_generate(force=False)
    assert v3 == v1 + 1 and fp3 != fp1
    assert tracked_env == []
