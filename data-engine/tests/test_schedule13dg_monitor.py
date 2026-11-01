"""Monitor SC 13D/13G: escaneo acotado de watchlist/cartera, dedup por
accession, presupuesto de descargas, watermark en connector_states,
verificacion del emisor contra el CIK del ticker y rollback por filing."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.entities import Company, ConnectorState, Schedule13DGFiling, WatchItem
from app.services import schedule13dg_monitor

FIXTURES = Path(__file__).parent / "fixtures"
REAL_13G_XML = (FIXTURES / "schedule13g_asts_blackrock.xml").read_text(encoding="utf-8")

# El fixture real es el 13G de BlackRock sobre ASTS: emisor CIK 1780312.
CIK = "0001780312"
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

TWO_FILINGS_URL = SUBMISSIONS_URL
TWO_FILINGS_PAYLOAD = {
    "filings": {
        "recent": {
            "accessionNumber": ["0002012383-26-003748", "0002012383-26-003749"],
            "form": ["SCHEDULE 13G", "SCHEDULE 13G"],
            "filingDate": ["2026-10-27", "2026-10-27"],
            "reportDate": ["2026-09-30", "2026-09-30"],
            "primaryDocument": [
                "xslSCHEDULE_13G_X02/primary_doc.xml",
                "xslSCHEDULE_13G_X02/primary_doc.xml",
            ],
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
    def __init__(self, url: str = SUBMISSIONS_URL, payload: dict = SUBMISSIONS_PAYLOAD):
        self.url = url
        self.payload = payload

    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        assert url == self.url, f"unexpected URL: {url}"
        return _FakeResponse(json.dumps(self.payload))


def _db(cik: str = CIK, ticker: str = "ZZT"):
    init_db()
    db = SessionLocal()
    db.query(Schedule13DGFiling).delete()
    db.query(ConnectorState).filter(
        ConnectorState.connector == schedule13dg_monitor.CONNECTOR_NAME
    ).delete()
    db.query(WatchItem).delete()
    db.query(Company).filter(Company.ticker.in_([ticker])).delete()
    db.commit()
    db.add(WatchItem(symbol=ticker, company="ZZ Test Corp"))
    if db.scalar(select(Company).where(Company.ticker == ticker)) is None:
        db.add(
            Company(
                ticker=ticker, name="ZZ Test Corp", exchange="NASDAQ",
                company_type="compounders", valuation_model="dcf", cik=cik,
            )
        )
    db.commit()
    return db


def _fetcher(filing: dict) -> str:
    return REAL_13G_XML


def _state(db):
    return db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == schedule13dg_monitor.CONNECTOR_NAME
        )
    )


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
    assert row.issuer_cik == "1780312"
    assert row.holder_name == "BlackRock, Inc."

    # Segunda corrida: el accession ya persistido no se vuelve a descargar.
    stats = schedule13dg_monitor.scan(
        db, client=_FakeClient(), fetcher=_fetcher, delay_seconds=0
    )
    assert stats["filings_new"] == 0
    assert db.query(Schedule13DGFiling).count() == 1

    state = _state(db)
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


def test_scan_skips_filing_when_issuer_cik_mismatches():
    """El ticker pedido resuelve a CIK 1234567 pero el filing declara otro
    emisor (1780312): NO se persiste ni se publica; se registra y se sigue."""
    db = _db(cik="0001234567")
    stats = schedule13dg_monitor.scan(
        db,
        client=_FakeClient(url="https://data.sec.gov/submissions/CIK0001234567.json"),
        fetcher=_fetcher,
        delay_seconds=0,
    )
    assert stats["tickers_scanned"] == 1
    assert stats["filings_seen"] == 1
    assert stats["filings_new"] == 0
    assert stats["filings_rejected"] == 1
    assert db.query(Schedule13DGFiling).count() == 0
    assert any("1780312" in error for error in stats["errors"])
    # La corrida sigue sana: watermark y metricas registrados.
    state = _state(db)
    assert state is not None
    assert (state.metadata_ or {}).get("runs") == 1
    db.close()


def test_scan_flush_error_rolls_back_and_keeps_scanning(monkeypatch):
    """Un flush que viola una constraint real (issuer_cik NULL) hace rollback
    de ESE filing (savepoint) sin envenenar el resto del escaneo ni perder
    filings previos; _record_success commitea sin PendingRollbackError."""
    db = _db()
    prior = Schedule13DGFiling(
        tenant_id=None,
        accession_number="0002012383-25-000001",
        form="SC 13G",
        issuer_cik="1780312",
        issuer_ticker="ZZT",
        holders=[],
        parser_version="1.0",
        status="parsed",
    )
    db.add(prior)
    db.commit()

    real_init = Schedule13DGFiling.__init__
    calls = {"n": 0}

    def poisoned_init(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            kwargs["issuer_cik"] = None  # viola el NOT NULL real de issuer_cik
        real_init(self, **kwargs)

    monkeypatch.setattr(Schedule13DGFiling, "__init__", poisoned_init)
    stats = schedule13dg_monitor.scan(
        db,
        client=_FakeClient(payload=TWO_FILINGS_PAYLOAD),
        fetcher=_fetcher,
        delay_seconds=0,
    )
    assert stats["filings_seen"] == 2
    assert stats["filings_new"] == 1
    # stats se sirve en la API: razon publica constante, sin tipo de excepcion.
    assert any("form13dg_filing_error" in error for error in stats["errors"])
    assert not any("IntegrityError" in error for error in stats["errors"])
    # El filing previo y el segundo filing nuevo sobreviven; el envenenado no.
    rows = db.scalars(select(Schedule13DGFiling).order_by(Schedule13DGFiling.id)).all()
    assert [row.accession_number for row in rows] == [
        "0002012383-25-000001",
        "0002012383-26-003749",
    ]
    # _record_success pudo commitear (sin PendingRollbackError) y dejo metricas.
    state = _state(db)
    assert state is not None
    assert (state.metadata_ or {}).get("runs") == 1
    assert state.last_error is None
    db.close()
