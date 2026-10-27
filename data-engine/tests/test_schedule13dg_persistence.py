"""Persistencia SC 13D/13G: idempotencia por accession, enmiendas como filas
propias y N/D (NULL) para lo no parseado."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.entities import Schedule13DGFiling
from app.services import schedule13dg_persistence
from app.services.connectors import form13dg as form13dg_connector

FIXTURES = Path(__file__).parent / "fixtures"
REAL_13G_XML = (FIXTURES / "schedule13g_asts_blackrock.xml").read_text(encoding="utf-8")

FILING = {
    "form": "SCHEDULE 13G",
    "accession_number": "0002012383-26-003748",
    "filing_date": "2026-10-27",
    "report_date": "2026-09-30",
    "issuer_ticker": "ASTS",
    "document_url": "https://www.sec.gov/Archives/edgar/data/1780312/000201238326003748/xslSCHEDULE_13G_X02/primary_doc.xml",
    "index_url": "https://www.sec.gov/Archives/edgar/data/1780312/000201238326003748/",
}
AMENDED_FILING = {
    **FILING,
    "form": "SCHEDULE 13G/A",
    "accession_number": "0002012383-27-000100",
    "filing_date": "2027-02-13",
}


def _db():
    init_db()
    db = SessionLocal()
    db.query(Schedule13DGFiling).delete()
    db.commit()
    return db


def test_persist_real_13g_creates_row_with_provenance():
    db = _db()
    parsed = form13dg_connector.parse_schedule13dg(REAL_13G_XML)
    result = schedule13dg_persistence.persist_filing(db, FILING, parsed, raw_text=REAL_13G_XML)
    db.commit()
    assert result["filing_created"] is True
    assert result["status"] == "parsed"
    row = db.scalar(select(Schedule13DGFiling))
    assert row is not None
    assert row.holder_name == "BlackRock, Inc."
    assert row.aggregate_shares == 16115870
    assert row.percent_of_class == 5.4
    assert row.snapshot_date == "2026-09-30"
    assert row.issuer_ticker == "ASTS"
    assert row.issuer_cik == "1780312"
    assert row.is_amendment is False
    assert row.source_url == FILING["document_url"]
    assert row.index_url == FILING["index_url"]
    assert row.raw_sha256
    assert row.parser_version == schedule13dg_persistence.PARSER_VERSION
    db.close()


def test_reingest_same_accession_is_idempotent():
    db = _db()
    parsed = form13dg_connector.parse_schedule13dg(REAL_13G_XML)
    first = schedule13dg_persistence.persist_filing(db, FILING, parsed)
    second = schedule13dg_persistence.persist_filing(db, FILING, parsed)
    db.commit()
    assert first["filing_created"] is True
    assert second["filing_created"] is False
    assert db.query(Schedule13DGFiling).count() == 1
    db.close()


def test_amendment_gets_its_own_immutable_row():
    db = _db()
    parsed = form13dg_connector.parse_schedule13dg(REAL_13G_XML)
    schedule13dg_persistence.persist_filing(db, FILING, parsed)
    amendment = schedule13dg_persistence.persist_filing(db, AMENDED_FILING, parsed)
    db.commit()
    assert amendment["filing_created"] is True
    rows = db.scalars(select(Schedule13DGFiling).order_by(Schedule13DGFiling.filing_date)).all()
    assert len(rows) == 2
    original, amendment_row = rows
    assert original.form == "SCHEDULE 13G" and original.is_amendment is False
    assert amendment_row.form == "SCHEDULE 13G/A" and amendment_row.is_amendment is True
    db.close()


def test_unparsed_document_stays_null_never_invented():
    db = _db()
    parsed = form13dg_connector.parse_schedule13dg("<html><body>not a schedule</body></html>")
    assert parsed["parsed_ok"] is False
    result = schedule13dg_persistence.persist_filing(db, FILING, parsed)
    db.commit()
    assert result["filing_created"] is True
    assert result["status"] == "unparsed"
    row = db.scalar(select(Schedule13DGFiling))
    assert row.holder_name is None
    assert row.aggregate_shares is None
    assert row.percent_of_class is None
    assert row.snapshot_date is None
    assert row.error
    db.close()


def test_flush_error_rolls_back_savepoint_and_session_survives(monkeypatch):
    """Un flush que viola una constraint real (issuer_cik NULL) queda acotado
    a su savepoint: la sesion NO queda envenenada y el filing siguiente
    persiste con normalidad."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    db = _db()
    parsed = form13dg_connector.parse_schedule13dg(REAL_13G_XML)
    real_init = Schedule13DGFiling.__init__

    def poisoned_init(self, **kwargs):
        kwargs["issuer_cik"] = None  # viola el NOT NULL real de issuer_cik
        real_init(self, **kwargs)

    monkeypatch.setattr(Schedule13DGFiling, "__init__", poisoned_init)
    with pytest.raises(IntegrityError):
        schedule13dg_persistence.persist_filing(db, FILING, parsed)
    monkeypatch.undo()

    # La misma sesion sigue operativa sin rollback manual del caller.
    result = schedule13dg_persistence.persist_filing(db, FILING, parsed)
    db.commit()
    assert result["filing_created"] is True
    assert result["status"] == "parsed"
    assert db.query(Schedule13DGFiling).count() == 1
    db.close()
