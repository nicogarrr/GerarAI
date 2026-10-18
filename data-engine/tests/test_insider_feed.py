"""Feed insider agregado, relleno de filings vacios y backoff de la SEC."""

from datetime import date

import httpx

from app.models.entities import InsiderFiling, InsiderTransaction
from app.services import insider_feed, insider_monitor
from app.services.connectors import form4 as form4_connector
from tests.test_insider_monitor import FILING_1, _cleanup, _db
from tests.test_insider_signals import CEO_BUY_XML


def _persist(db, filing=FILING_1):
    from app.services import insider_persistence

    parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
    insider_persistence.persist_filing(db, filing, parsed, xml_text=CEO_BUY_XML, tenant_id=None)


def test_feed_lists_insider_role_side_shares_price_value():
    db = _db()
    try:
        _cleanup(db)
        _persist(db)
        feed = insider_feed.build_feed(db, days=3650, today=date(2024, 3, 20))
        assert feed["status"] == "ok"
        assert feed["count"] >= 1
        tx = feed["transactions"][0]
        assert tx["insider"] and tx["role"]
        assert tx["side"] == "compra"
        assert tx["shares"] and tx["price"] and tx["value"]
        assert feed["totals"]["buy_count"] >= 1
        assert feed["totals"]["filings_pending"] == 0
        sells = insider_feed.build_feed(db, days=3650, side="sell", today=date(2024, 3, 20))
        assert sells["count"] == 0
    finally:
        _cleanup(db)
        db.close()


def test_backfill_fills_filings_without_transactions():
    db = _db()
    try:
        _cleanup(db)
        db.add(
            InsiderFiling(
                tenant_id=None,
                accession_number=FILING_1["accession_number"],
                form="4",
                issuer_cik="0001234567",
                issuer_ticker="ACME",
                filing_date=FILING_1["filing_date"],
                source_url=FILING_1["document_url"],
                parser_version="1.1",
                status="parsed",
            )
        )
        db.commit()
        assert db.query(InsiderTransaction).count() == 0
        stats = insider_monitor.backfill_empty_filings(
            db, fetcher=lambda filing: CEO_BUY_XML, delay_seconds=0
        )
        assert stats["filled"] == 1
        assert db.query(InsiderTransaction).count() >= 1
        again = insider_monitor.backfill_empty_filings(
            db, fetcher=lambda filing: CEO_BUY_XML, delay_seconds=0
        )
        assert again["examined"] == 0
    finally:
        _cleanup(db)
        db.close()


def test_get_text_retries_on_403_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(403 if calls["n"] < 3 else 200, text="<ownershipDocument/>")

    monkeypatch.setattr(form4_connector, "_sleep", lambda seconds: None)
    monkeypatch.setattr(form4_connector, "_throttle", lambda: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        text = form4_connector._get_text("https://www.sec.gov/x.xml", client)
    assert text == "<ownershipDocument/>"
    assert calls["n"] == 3
