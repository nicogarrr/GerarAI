"""A reachable old CSV must not replace a newer stored issuer snapshot."""
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, EtfHolding
from app.services import etf_holdings as eh
from tests.test_etf_holdings_bordes import NASA_PAGE, UFO_CSV_URL, UFO_HTML, UFO_PAGE, _client, _procure_csv


def test_older_csv_preserves_newer_stored_holdings():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EtfHolding(etf="UFO", ticker="ASTS", weight_pct=5,
                          as_of=date(2026, 10, 20), source_url="newer"))
        db.commit()
        files = {UFO_PAGE: UFO_HTML, UFO_CSV_URL: _procure_csv([1] * 10), NASA_PAGE: "no links"}
        with _client(files) as client:
            result = eh.refresh_etf_holdings(db, client)
        assert "anterior" in result["UFO"]
        rows = db.scalars(select(EtfHolding).where(EtfHolding.etf == "UFO")).all()
        assert [(r.ticker, r.as_of, r.source_url) for r in rows] == [("ASTS", date(2026, 10, 20), "newer")]


def test_same_or_newer_csv_can_replace_stored_holdings():
    for previous in (date(2026, 10, 18), date(2026, 10, 19)):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(EtfHolding(etf="UFO", ticker="ASTS", weight_pct=5,
                              as_of=previous, source_url="stored"))
            db.commit()
            files = {UFO_PAGE: UFO_HTML, UFO_CSV_URL: _procure_csv([1] * 10), NASA_PAGE: "no links"}
            with _client(files) as client:
                result = eh.refresh_etf_holdings(db, client)
            assert result["UFO"].startswith("ok")
            rows = db.scalars(select(EtfHolding).where(EtfHolding.etf == "UFO")).all()
            assert len(rows) == 10 and all(r.as_of == date(2026, 10, 19) for r in rows)
