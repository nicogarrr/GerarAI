"""Monitor Form 144: escaneo acotado de watchlist/cartera, dedup por
accession, presupuesto de descargas, watermark en connector_states,
verificacion del emisor contra el CIK del ticker y evento de noticias
factual (aviso de venta propuesta, nunca venta ejecutada)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, ConnectorState, Form144Notice, NewsEvent, WatchItem
from app.services import form144_monitor

FIXTURES = Path(__file__).parent / "fixtures"
REAL_144_XML = (FIXTURES / "form144" / "slgn_0000849869-26-000005.xml").read_text(encoding="utf-8")

# El fixture real es el Form 144 de un director de SLGN: emisor CIK 849869.
CIK = "0000849869"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "accessionNumber": ["0000849869-26-000005"],
            "form": ["144"],
            "filingDate": ["2026-11-13"],
            "reportDate": [""],
            "primaryDocument": ["xsl144X01/primary_doc.xml"],
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


@pytest.fixture(autouse=True)
def _own_databases():
    # Own the complete schema, not DELETE subsets of a suite-wide DB:
    # watchlist_tickers also reads portfolio positions from previous tests.
    yield
    for engine in _isolated_engines:
        engine.dispose()
    _isolated_engines.clear()


_isolated_engines = []


def _db(cik: str = CIK, ticker: str = "ZZT"):
    engine = create_engine("sqlite:///:memory:")
    _isolated_engines.append(engine)
    Base.metadata.create_all(engine)
    db = Session(engine)
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
    return REAL_144_XML


def _state(db):
    return db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == form144_monitor.CONNECTOR_NAME
        )
    )


def test_scan_ingests_new_notice_and_skips_known():
    db = _db()
    stats = form144_monitor.scan(
        db, client=_FakeClient(), fetcher=_fetcher, delay_seconds=0
    )
    assert stats["status"] == "ok"
    assert stats["tickers_scanned"] == 1
    assert stats["filings_seen"] == 1
    assert stats["filings_new"] == 1
    row = db.scalar(select(Form144Notice))
    assert row is not None
    assert row.issuer_ticker == "ZZT"
    assert row.issuer_cik == "0000849869"
    assert row.seller_name == "LEWIS ROBERT B"
    assert row.relationships == ["Director"]
    assert row.shares_to_sell == 88861
    assert row.aggregate_market_value == 3687731.50
    assert row.approx_sale_date == "11/16/2026"
    assert row.status == "parsed"

    # Segunda corrida: el accession ya persistido no se vuelve a descargar.
    stats = form144_monitor.scan(
        db, client=_FakeClient(), fetcher=_fetcher, delay_seconds=0
    )
    assert stats["filings_new"] == 0
    assert db.query(Form144Notice).count() == 1

    state = _state(db)
    assert state is not None


def test_scan_creates_one_factual_news_event():
    db = _db()
    form144_monitor.scan(db, client=_FakeClient(), fetcher=_fetcher, delay_seconds=0)
    events = db.scalars(select(NewsEvent)).all()
    assert len(events) == 1
    event = events[0]
    assert "Aviso de venta propuesta" in event.title
    assert "LEWIS ROBERT B" in event.title
    # Nunca se redacta como venta ejecutada ni como senal direccional.
    assert "no acredita una venta ejecutada" in event.summary
    assert event.event_type == "insider_proposed_sale"
    assert event.impact_direction == "neutral"
    assert event.source == "SEC"


def test_scan_rejects_issuer_mismatch():
    # El documento declara otro issuer_cik: no se persiste ni se publica.
    db = _db(cik="0001501796")  # AURA; el fixture declara SLGN (849869)
    stats = form144_monitor.scan(
        db,
        client=_FakeClient(url="https://data.sec.gov/submissions/CIK0001501796.json"),
        fetcher=_fetcher,
        delay_seconds=0,
    )
    assert stats["filings_rejected"] == 1
    assert stats["filings_new"] == 0
    assert db.query(Form144Notice).count() == 0


def test_scan_unparsed_document_stays_nd():
    db = _db()
    stats = form144_monitor.scan(
        db,
        client=_FakeClient(),
        fetcher=lambda filing: "<div>AccessDenied</div>",
        delay_seconds=0,
    )
    assert stats["filings_new"] == 1
    assert stats["filings_unparsed"] == 1
    row = db.scalar(select(Form144Notice))
    assert row.status == "unparsed"
    assert row.shares_to_sell is None  # N/D, nunca una cifra inventada


def test_scan_skips_empty_watchlist():
    engine = create_engine("sqlite:///:memory:")
    _isolated_engines.append(engine)
    Base.metadata.create_all(engine)
    db = Session(engine)
    stats = form144_monitor.scan(db, client=_FakeClient(), fetcher=_fetcher, delay_seconds=0)
    assert stats["status"] == "skipped"
    assert stats["reason"] == "watchlist and portfolio are empty"


def test_scan_resumes_rotation_after_listing_budget(monkeypatch):
    # Presupuesto de listados agotado: la corrida siguiente reanuda donde
    # quedo (next_offset persistido en connector_states), sin repetir emisores
    # ya listados ni perder los pendientes.
    db = _db()
    ciks = {f"T{i}": str(1000 + i) for i in range(6)}
    monkeypatch.setattr(form144_monitor, "resolve_ciks", lambda *a, **k: ciks)
    listing = Mock(return_value=[])
    monkeypatch.setattr(form144_monitor.form144_connector, "recent_form144_filings", listing)

    first = form144_monitor.scan(db, tickers=list(ciks), max_new_fetches=4, delay_seconds=0)
    assert first["tickers_scanned"] == 6
    assert first["tickers_listed"] == 4
    assert first["next_offset"] == 4
    assert listing.call_count == 4

    listing.reset_mock()
    second = form144_monitor.scan(db, tickers=list(ciks), max_new_fetches=4, delay_seconds=0)
    assert listing.call_count == 2  # solo los emisores pendientes
    assert second["next_offset"] == 0  # rotacion completa: la proxima reinicia

    listing.reset_mock()
    third = form144_monitor.scan(db, tickers=list(ciks), max_new_fetches=4, delay_seconds=0)
    assert listing.call_count == 4
