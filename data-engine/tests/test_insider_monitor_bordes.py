"""Relecturas Form4 en SQLite, con respuestas locales y sin SEC."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, InsiderFiling, InsiderTransaction, Tenant
from app.services import insider_monitor as svc
from app.services import insider_persistence


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(Tenant(id=1, external_id="insider-borders"))
            session.flush()
            session.info["tenant_id"] = 1
            yield session
    finally:
        engine.dispose()


def _filing(db, acc):
    row = InsiderFiling(
        tenant_id=1,
        accession_number=acc,
        form="4",
        issuer_cik="1",
        filing_date="2026-01-02",
        parser_version="old",
        source_url=f"https://example.test/{acc}",
    )
    db.add(row)
    db.commit()
    return row


def test_backfill_vacio_marca_empty_y_pausa(db, monkeypatch):
    row = _filing(db, "empty")
    seen = []
    sleeps = []
    monkeypatch.setattr(
        svc.form4_connector, "fetch_filing_xml", lambda url, *, client: seen.append(url) or "<xml/>"
    )
    monkeypatch.setattr(svc.form4_connector, "parse_form4_xml", lambda text: {"transactions": []})
    out = svc.backfill_empty_filings(db, tenant_id=1, delay_seconds=0.25, sleeper=sleeps.append)
    assert out == {"examined": 1, "filled": 0, "empty": 1, "failed": 0}
    assert row.status == "empty"
    assert seen == ["https://example.test/empty"] and sleeps == [0.25]
    assert svc.backfill_empty_filings(db, tenant_id=1, delay_seconds=0)["examined"] == 0


def test_backfill_fallo_no_marca_empty_y_se_reintenta(db, monkeypatch):
    row = _filing(db, "failed")
    sleeps = []

    def broken(filing):
        raise ValueError("download")

    out = svc.backfill_empty_filings(
        db, tenant_id=1, fetcher=broken, delay_seconds=0.1, sleeper=sleeps.append
    )
    assert out == {"examined": 1, "filled": 0, "empty": 0, "failed": 1}
    assert row.status == "parsed" and row.parser_version == "old"
    assert sleeps == [0.1]


def test_regla_10b5_fingerprints_ajenos_no_se_pisan_y_fallo_reintenta(db, monkeypatch):
    row = _filing(db, "flags")
    tx = {"type": "P", "shares": 3, "price": 2, "rule_10b5_1": True}
    fingerprint = insider_persistence.transaction_fingerprint("flags", 0, tx)
    matched = InsiderTransaction(
        tenant_id=1,
        filing_id=row.id,
        accession_number="flags",
        form="4",
        fingerprint=fingerprint,
        rule_10b5_1=False,
    )
    unmatched = InsiderTransaction(
        tenant_id=1,
        filing_id=row.id,
        accession_number="flags",
        form="4",
        fingerprint="unmatched",
        rule_10b5_1=True,
    )
    db.add_all([matched, unmatched])
    db.commit()
    monkeypatch.setattr(svc.form4_connector, "parse_form4_xml", lambda text: {"transactions": [tx]})
    sleeps = []
    out = svc.backfill_rule_10b5_1(
        db, tenant_id=1, fetcher=lambda filing: "<xml/>", delay_seconds=0.2, sleeper=sleeps.append
    )
    assert out == {"examined": 1, "updated": 1, "flagged": 1, "failed": 0}
    assert matched.rule_10b5_1 is True and unmatched.rule_10b5_1 is True
    assert row.parser_version == svc.INSIDER_PARSER_VERSION and sleeps == [0.2]
    row.parser_version = "old"
    db.commit()

    def broken(url, *, client):
        raise RuntimeError("no download")

    monkeypatch.setattr(svc.form4_connector, "fetch_filing_xml", broken)
    out = svc.backfill_rule_10b5_1(db, tenant_id=1, delay_seconds=0)
    assert out == {"examined": 1, "updated": 0, "flagged": 0, "failed": 1}
    assert row.parser_version == "old"
    assert (
        db.scalar(select(InsiderTransaction).where(InsiderTransaction.id == matched.id)).rule_10b5_1 is True
    )
