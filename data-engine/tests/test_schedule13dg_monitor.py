"""Monitor SC 13D/13G: escaneo acotado de watchlist/cartera, dedup por
accession, presupuesto de descargas y watermark en connector_states."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.entities import Company, ConnectorState, Schedule13DGFiling, WatchItem
from app.services import schedule13dg_monitor

FIXTURES = Path(__file__).parent / "fixtures"
REAL_13G_XML = (FIXTURES / "schedule13g_asts_blackrock.xml").read_text(encoding="utf-8")

CIK = "0001234567"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "accessionNumber": ["0002012383-26-003748"],
            "form": ["SCHEDULE 13G"],
            "filingDate": ["2026-10-27"],
            "reportDate": ["2026-09-30"],
            "primaryDocument": ["xslSCHEDULE_13G_X02/primary_doc.xml"],
        }
    }
}


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return json.loads(self.text)


class _FakeClient:
    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        assert url == SUBMISSIONS_URL, f"unexpected URL: {url}"
        return _FakeResponse(json.dumps(SUBMISSIONS_PAYLOAD))


def _db():
    init_db()
    db = SessionLocal()
    db.query(Schedule13DGFiling).delete()
    db.query(ConnectorState).filter(
        ConnectorState.connector == schedule13dg_monitor.CONNECTOR_NAME
    ).delete()
    db.query(WatchItem).delete()
    db.query(Company).filter(Company.ticker.in_(["ZZT"])).delete()
    db.commit()
    db.add(WatchItem(symbol="ZZT", company="ZZ Test Corp"))
    if db.scalar(select(Company).where(Company.ticker == "ZZT")) is None:
        db.add(
            Company(
                ticker="ZZT", name="ZZ Test Corp", exchange="NASDAQ",
                company_type="compounders", valuation_model="dcf", cik=CIK,
            )
        )
    db.commit()
    return db


def _fetcher(filing: dict) -> str:
    return REAL_13G_XML


def test_scan_ingests_new_filing_and_skips_known():
    db = _db()
    stats = schedule13dg_monitor.scan(
        db, client=_FakeClient(), fetcher=_fetcher, delay_seconds=0
    )
    assert stats["status"] == "ok"
    assert stats["tickers_scanned"] == 1
    assert stats["filings_seen"] == 1
    assert stats["filings_new"] == 1
    row = db.scalar(select(Schedule13DGFiling))
    assert row is not None
    assert row.issuer_ticker == "ZZT"
    assert row.holder_name == "BlackRock, Inc."

    # Segunda corrida: el accession ya persistido no se vuelve a descargar.
    stats = schedule13dg_monitor.scan(
        db, client=_FakeClient(), fetcher=_fetcher, delay_seconds=0
    )
    assert stats["filings_new"] == 0
    assert db.query(Schedule13DGFiling).count() == 1

    state = db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == schedule13dg_monitor.CONNECTOR_NAME
        )
    )
    assert state is not None
    assert (state.metadata_ or {}).get("runs") == 2
    db.close()


def test_scan_respects_fetch_budget():
    db = _db()
    stats = schedule13dg_monitor.scan(
        db, client=_FakeClient(), fetcher=_fetcher, delay_seconds=0, max_new_fetches=0
    )
    assert stats["filings_new"] == 0
    assert any("presupuesto" in error for error in stats["errors"])
    db.close()


def test_scan_broken_document_marks_unparsed_and_continues():
    db = _db()
    stats = schedule13dg_monitor.scan(
        db,
        client=_FakeClient(),
        fetcher=lambda filing: "<html><body>broken</body></html>",
        delay_seconds=0,
    )
    assert stats["filings_new"] == 1
    assert stats["filings_unparsed"] == 1
    row = db.scalar(select(Schedule13DGFiling))
    assert row.status == "unparsed"
    assert row.holder_name is None
    db.close()
