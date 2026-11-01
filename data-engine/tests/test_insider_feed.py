"""Feed insider agregado, relleno de filings vacios y backoff de la SEC."""

from datetime import date

import httpx

from app.models.entities import InsiderFiling, InsiderTransaction
from app.services import insider_feed, insider_monitor, insider_persistence
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

def test_group_tranches_merges_same_filing_lines():
    items = [
        {
            "ticker": "META", "insider": "ZUCKERBERG MARK", "type": "S",
            "accession_number": "0001", "shares": 100.0, "price": 10.0,
            "value": 1000.0, "date": "2026-09-24", "source_url": "https://x",
        },
        {
            "ticker": "META", "insider": "ZUCKERBERG MARK", "type": "S",
            "accession_number": "0001", "shares": 300.0, "price": 20.0,
            "value": 6000.0, "date": "2026-09-24", "source_url": "https://x",
        },
        {
            "ticker": "META", "insider": "OTRO INSIDER", "type": "S",
            "accession_number": "0001", "shares": 50.0, "price": 10.0,
            "value": 500.0, "date": "2026-09-24", "source_url": "https://x",
        },
    ]
    grouped = insider_feed._group_tranches(items)
    assert len(grouped) == 2
    main = next(g for g in grouped if g["insider"] == "ZUCKERBERG MARK")
    assert main["tranches"] == 2
    assert main["shares"] == 400.0
    assert main["value"] == 7000.0
    assert main["price"] == 7000.0 / 400.0
    other = next(g for g in grouped if g["insider"] == "OTRO INSIDER")
    assert other["tranches"] == 1
    assert other["price"] == 10.0


def test_feed_exposes_big_buys():
    db = _db()
    try:
        _cleanup(db)
        _persist(db)  # CEO compra $5M en el XML de prueba
        feed = insider_feed.build_feed(db, days=3650, today=date(2024, 3, 20))
        assert any(s["signal"] == "big_buy" for s in feed["big_buys"])
        tx = feed["transactions"][0]
        assert tx["tranches"] >= 1
    finally:
        _cleanup(db)
        db.close()

PLANNED_SELL_XML = """<ownershipDocument>
  <schemaVersion>X0306</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport><value>2024-03-15</value></periodOfReport>
  <issuer>
    <issuerCik>0001234567</issuerCik>
    <issuerName>ACME Corp</issuerName>
    <issuerTradingSymbol>ACME</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001111111</rptOwnerCik>
      <rptOwnerName>DOE JANE</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle><value>Chief Executive Officer</value></officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <footnotes>
    <footnote id="F1">The sales reported were effected pursuant to a Rule 10b5-1 trading plan adopted by the reporting person.</footnote>
    <footnote id="F2">Other note without plan language.</footnote>
  </footnotes>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-03-10</value></transactionDate>
      <transactionCoding>
        <transactionCode><value>S</value></transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value><footnoteId id="F1"/></transactionShares>
        <transactionPricePerShare><value>250</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-03-10</value></transactionDate>
      <transactionCoding>
        <transactionCode><value>S</value></transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value><footnoteId id="F2"/></transactionShares>
        <transactionPricePerShare><value>251</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_parser_marks_rule_10b5_1_only_on_referenced_footnotes():
    parsed = form4_connector.parse_form4_xml(PLANNED_SELL_XML)
    txs = parsed["transactions"]
    assert txs[0]["rule_10b5_1"] is True  # referencia F1 (plan 10b5-1)
    assert txs[1]["rule_10b5_1"] is False  # referencia F2 (sin plan)


def test_backfill_rule_10b5_1_budgeted_and_idempotent():
    db = _db()
    try:
        _cleanup(db)
        # Filing ya persistido con el parser antiguo (parser_version distinta).
        parsed = form4_connector.parse_form4_xml(PLANNED_SELL_XML)
        insider_persistence.persist_filing(db, FILING_1, parsed, xml_text=PLANNED_SELL_XML, tenant_id=None)
        db.query(InsiderFiling).update({"parser_version": "1.1"})
        db.query(InsiderTransaction).update({"rule_10b5_1": False})
        db.commit()

        stats = insider_monitor.backfill_rule_10b5_1(
            db, max_fetches=5, delay_seconds=0, fetcher=lambda filing: PLANNED_SELL_XML
        )
        assert stats["examined"] == 1
        assert stats["updated"] == 1
        assert stats["flagged"] == 1
        rows = db.query(InsiderTransaction).order_by(InsiderTransaction.id).all()
        assert [r.rule_10b5_1 for r in rows] == [True, False]
        assert db.query(InsiderTransaction).count() == 2  # sin duplicar
        # Ya con la version nueva: no vuelve a examinarlo.
        again = insider_monitor.backfill_rule_10b5_1(
            db, max_fetches=5, delay_seconds=0, fetcher=lambda filing: PLANNED_SELL_XML
        )
        assert again["examined"] == 0
    finally:
        _cleanup(db)
        db.close()


def test_feed_exposes_rule_10b5_1():
    db = _db()
    try:
        _cleanup(db)
        parsed = form4_connector.parse_form4_xml(PLANNED_SELL_XML)
        insider_persistence.persist_filing(db, FILING_1, parsed, xml_text=PLANNED_SELL_XML, tenant_id=None)
        feed = insider_feed.build_feed(db, days=3650, today=date(2024, 3, 20))
        assert feed["count"] >= 1
        # Tramos de un mismo filing+insider+codigo: planificado solo si todos lo son.
        tx = feed["transactions"][0]
        assert tx["rule_10b5_1"] is False
        assert tx["tranches"] == 2
    finally:
        _cleanup(db)
        db.close()


def test_primary_ticker_collapses_share_class_lists():
    from app.services.insider_feed import primary_ticker

    assert primary_ticker("LEN, LEN.B") == "LEN"
    assert primary_ticker("GTX,GTXAP") == "GTX"
    assert primary_ticker("len") == "LEN"
    assert primary_ticker("BRK.B") == "BRK.B"
    assert primary_ticker(None) is None
    assert primary_ticker("LEN; LEN.B") == "LEN"
    assert primary_ticker(" len ,len.b") == "LEN"
    assert primary_ticker("") == ""


def test_build_feed_ticker_filter_matches_multiclass_separators():
    db = _db()
    try:
        _cleanup(db)
        _persist(db)
        for raw in ("LEN, LEN.B", "LEN; LEN.B", "len,len.b"):
            db.query(InsiderFiling).update({"issuer_ticker": raw})
            db.query(InsiderTransaction).update({"issuer_ticker": raw})
            db.commit()
            for wanted in ("LEN", "len", "LEN.B", " LEN "):
                feed = insider_feed.build_feed(db, days=3650, ticker=wanted, today=date(2024, 3, 20))
                assert feed["count"] >= 1, (raw, wanted)
                tx = feed["transactions"][0]
                assert tx["ticker"] == "LEN"
                assert tx["issuer_tickers_raw"] == raw
            miss = insider_feed.build_feed(db, days=3650, ticker="XYZ", today=date(2024, 3, 20))
            assert miss["count"] == 0
    finally:
        _cleanup(db)
        db.close()


def test_feed_no_materializa_entidades_orm():
    """Perf: el feed sirve ~limit filas pero antes instanciaba TODAS las
    entidades ORM de la ventana (medido 2026-10-31: consulta+ORM = 64% del
    tiempo en benchmark sintetico de 45k filas; columnas-only = 34% de ese
    coste). La consulta principal debe leer solo columnas."""
    db = _db()
    try:
        _cleanup(db)
        _persist(db)
        # La identity_map es debil: no basta mirarla despues. Hay que contar
        # las instancias ORM cargadas DURANTE la llamada.
        from sqlalchemy import event

        loaded: list[object] = []

        def on_loaded(session, instance):
            if isinstance(instance, (InsiderTransaction, InsiderFiling)):
                loaded.append(instance)

        from sqlalchemy.orm import Session as _Session

        event.listen(_Session, "loaded_as_persistent", on_loaded)
        try:
            feed = insider_feed.build_feed(db, days=3650, today=date(2024, 3, 20))
        finally:
            event.remove(_Session, "loaded_as_persistent", on_loaded)
        assert feed["status"] == "ok"
        assert feed["count"] >= 1
        assert loaded == [], "build_feed materializo entidades ORM"
    finally:
        _cleanup(db)
        db.close()
