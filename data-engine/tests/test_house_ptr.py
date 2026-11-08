"""insiders-1: operaciones de politicos (PTR de la Camara) desde fuentes oficiales.

Fixtures grabados del Clerk of the House (PDF reales de 2026 y un recorte del
indice anual 2026FD.xml) y un recorte de congress-legislators (dominio publico).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, get_db, init_db
from app.models.entities import Document
from app.services import politician_trades
from app.services.connectors import house_ptr

FIX = Path(__file__).parent / "fixtures" / "house_ptr"


def _pdf(doc_id: str) -> bytes:
    return (FIX / f"{doc_id}.pdf").read_bytes()


def _index() -> list[dict]:
    rows = house_ptr.parse_index_xml((FIX / "2026FD_sample.xml").read_bytes())
    for row in rows:
        row["source_url"] = house_ptr.PTR_URL.format(year=row["year"], doc_id=row["doc_id"])
    return rows


def _parties() -> dict:
    return politician_trades.house_party_map(json.loads((FIX / "legislators_sample.json").read_text()))


def _db():
    init_db()
    db = SessionLocal()
    db.query(Document).filter(Document.source_type == politician_trades.SOURCE_TYPE).delete()
    db.commit()
    return db


def test_index_keeps_only_ptrs_and_marks_paper_filings():
    rows = _index()
    assert {r["doc_id"] for r in rows} == {"20033756", "20033766", "20033829", "20033845", "9115822"}
    paper = next(r for r in rows if r["doc_id"] == "9115822")
    assert paper["electronic"] is False and paper["last"] == "Khanna" and paper["state_district"] == "CA17"
    hern = next(r for r in rows if r["doc_id"] == "20033829")
    assert hern["filing_date"] == "2026-01-22" and hern["state"] == "OK" and hern["district"] == "01"


def test_parse_electronic_ptr_rows():
    parsed = house_ptr.parse_ptr_text(house_ptr.pdf_text(_pdf("20033756")))
    assert parsed["member"] == "Josh Gottheimer" and parsed["state_district"] == "NJ05"
    assert parsed["unparsed_blocks"] == 0
    tickers = [t["ticker"] for t in parsed["trades"]]
    assert tickers == ["APD", "LNG", "CVLT", "MTHRY", "SE", "NOW", "SSMXY", "UBER", "UTZ"]
    first = parsed["trades"][0]
    assert first["owner"] == "JT" and first["type"] == "S (partial)" and first["type_label"] == "venta_parcial"
    assert (first["tx_date"], first["notification_date"]) == ("2025-12-08", "2026-01-07")
    assert (first["amount_min"], first["amount_max"]) == (15001, 50000)


def test_parse_bond_without_ticker_and_wrapped_names():
    delbene = house_ptr.parse_ptr_text(house_ptr.pdf_text(_pdf("20033766")))
    (bond,) = delbene["trades"]
    assert bond["ticker"] is None and bond["asset_type"] == "GS" and bond["type"] == "P"
    taylor = house_ptr.parse_ptr_text(house_ptr.pdf_text(_pdf("20033845")))
    assert [t["ticker"] for t in taylor["trades"]].count("MSFT") == 2
    assert all(t["owner"] == "self" for t in taylor["trades"])


def test_days_late_uses_the_45_day_stock_act_rule():
    assert house_ptr.days_late("2025-12-05", "2026-01-19") == 0  # dia 45: a tiempo
    assert house_ptr.days_late("2025-12-05", "2026-01-20") == 1
    assert house_ptr.days_late(None, "2026-01-20") is None
    assert house_ptr.parse_amount("Over $50,000,000") == {"amount_text": "Over $50,000,000", "amount_min": 50000001, "amount_max": None}


def test_ingest_is_idempotent_and_reads_are_deterministic():
    db = _db()
    try:
        rows = _index()
        # Una declaracion presentada tarde (para probar los contadores).
        for row in rows:
            if row["doc_id"] == "20033829":
                row["filing_date"] = "2026-03-20"  # operacion 23-dic-2025: 87 dias -> 42 tarde
        fetched = []

        def fetch(row):
            fetched.append(row["doc_id"])
            return _pdf(row["doc_id"])

        stats = politician_trades.ingest_year(db, 2026, index_rows=rows, pdf_fetcher=fetch, party_map=_parties())
        assert stats["new"] == 5 and stats["scanned"] == 1 and stats["trades"] == 20
        assert "9115822" not in fetched  # el escaneado no se descarga ni se inventa
        again = politician_trades.ingest_year(db, 2026, index_rows=rows, pdf_fetcher=fetch, party_map=_parties())
        assert again["new"] == 0

        listing = politician_trades.politicians(db, sort="trades")
        assert listing["chambers"]["senate"] == "no_disponible"
        assert listing["coverage"] == {"years": [2026], "filings": 5, "scanned_filings": 1}
        cards = {c["member"]: c for c in listing["politicians"]}
        hern = cards["Kevin Hern"]
        assert hern["party"] == "R" and hern["late"] == 1 and hern["late_over_30"] == 1 and hern["on_time_pct"] == 0.0
        gott = cards["Josh Gottheimer"]
        assert gott["party"] == "D" and gott["trades"] == 9 and gott["on_time_pct"] == 100.0
        assert gott["volume_min"] == 15001 + 8 * 1001 and gott["volume_max"] == 50000 + 8 * 15000
        khanna = cards["Rohit Khanna"]
        assert khanna["trades"] == 0 and khanna["scanned_filings"] == 1
        assert listing["politicians"][0]["member"] in ("Josh Gottheimer", "David J. Taylor")
        assert politician_trades.politicians(db, party="R")["total"] == 2

        msft = politician_trades.ticker_trades(db, "msft")
        assert msft["trades_total"] == 2 and msft["buys"] == 2
        assert msft["members"][0]["member"] == "David J. Taylor"
        assert msft["trades"][0]["source_url"].endswith("/ptr-pdfs/2026/20033845.pdf")
        assert politician_trades.ticker_trades(db, "ZZZZ")["status"] == "sin_datos"
    finally:
        db.close()


def test_routes_list_ticker_and_member():
    from app.api.routes import politicians as module

    db = _db()
    politician_trades.ingest_year(db, 2026, index_rows=_index(), pdf_fetcher=lambda r: _pdf(r["doc_id"]), party_map=_parties())
    app = FastAPI()
    app.include_router(module.router, prefix="/api/politicians")

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as http:
        listing = http.get("/api/politicians", params={"sort": "late"}).json()
        assert listing["total"] == 5
        key = next(c["member_key"] for c in listing["politicians"] if c["member"] == "Kevin Hern")
        member = http.get(f"/api/politicians/member/{key}").json()
        assert member["trades_list"][0]["ticker"] == "UNH"
        assert http.get("/api/politicians/member/house:XX00:nadie").status_code == 404
        assert http.get("/api/politicians/ticker/UNH").json()["sells"] == 1
        assert http.get("/api/politicians", params={"party": "X"}).status_code == 422
    db.close()


def test_party_map_ignores_senators_and_maps_at_large():
    parties = politician_trades.house_party_map([
        {"id": {"bioguide": "A1"}, "name": {"last": "Solo"}, "terms": [{"type": "rep", "state": "WY", "district": 0, "party": "Republican"}]},
        {"id": {"bioguide": "S1"}, "name": {"last": "Sen"}, "terms": [{"type": "sen", "state": "WY", "party": "Democrat"}]},
    ])
    assert parties == {"WY00": {"party": "R", "bioguide": "A1", "last": "Solo"}}


def test_scheduler_registers_house_ptr_every_6h():
    from app.workers import queue_taxonomy
    from app.workers import scheduler as scheduler_module

    job = scheduler_module.build_scheduler().get_job("house_ptr")
    assert job is not None
    assert queue_taxonomy.ACTOR_CLASS.get("ingest_house_ptr") == queue_taxonomy.INGESTA


def test_exact_amounts_and_wrapped_descriptions_do_not_lose_or_pollute_rows():
    exact = house_ptr.parse_ptr_text(house_ptr.pdf_text(_pdf("20034999")))
    (row,) = exact["trades"]
    assert row["ticker"] == "ICHR" and row["amount_text"] == "$2,722.50"
    assert (row["amount_min"], row["amount_max"]) == (2722, 2723)
    wrapped = house_ptr.parse_ptr_text(house_ptr.pdf_text(_pdf("20027982")))
    assert wrapped["unparsed_blocks"] == 0
    second = wrapped["trades"][1]
    assert second["ticker"] == "BAC" and second["asset"] == "Bank of America Corporation Common Stock (BAC)"


def test_wrapped_subholding_line_is_not_glued_to_the_next_asset():
    parsed = house_ptr.parse_ptr_text(house_ptr.pdf_text(_pdf("20030868")))
    assert parsed["unparsed_blocks"] == 0
    second = parsed["trades"][1]
    assert second["owner"] == "SP" and second["ticker"] == "ALK"
    assert second["asset"].startswith("Alaska Air Group")


def test_party_match_ignores_accents_and_compound_surnames():
    from app.services.politician_trades import _name_tokens

    assert _name_tokens("Sánchez") & _name_tokens("Sanchez")
    assert _name_tokens("McClain Delaney") & _name_tokens("Delaney")
    assert not (_name_tokens("Greene") & _name_tokens("Green"))


def test_member_card_counts_trades_without_amount_range():
    recs = [{
        "member": "Jane Doe", "member_key": "jane-doe", "chamber": "house",
        "state": "CA", "district": "12", "state_district": "CA-12", "party": "D",
        "bioguide": "D000123", "filing_date": "2026-01-10", "readable": True,
        "trades": [
            {"ticker": "ABC", "tx_date": "2026-01-02", "amount_min": 1001, "amount_max": 15000, "days_late": 0},
            {"ticker": "XYZ", "tx_date": "2026-01-03", "amount_min": None, "amount_max": None, "days_late": None},
        ],
    }]
    card = politician_trades._member_card("jane-doe", recs)
    # Solo se suma la horquilla declarada; la operacion sin importes no vale 0.
    assert card["volume_min"] == 1001
    assert card["volume_max"] == 15000
    assert card["volume_unknown_trades"] == 1
