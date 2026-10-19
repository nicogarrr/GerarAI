"""Contrato de /api/insider/operations: agregado P/S por empresa e insider.

Solo compras/ventas en mercado abierto (codigos P/S) de los Form 4 ya
persistidos; el resto de codigos se cuenta en excluded_codes, nunca entra al
agregado. Empresa sin datos: lista aparte, no fila con ceros inventados.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    InsiderFiling,
    InsiderTransaction,
    Position,
    WatchItem,
)
from app.services.insider_operations import insider_operations


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str, name: str) -> Company:
    company = Company(
        ticker=ticker, name=name, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _tx(db: Session, filing: InsiderFiling, **kwargs) -> InsiderTransaction:
    tx = InsiderTransaction(
        fingerprint=filing.accession_number + kwargs.pop("fp_suffix"),
        filing_id=filing.id,
        accession_number=filing.accession_number,
        form="4",
        issuer_ticker=filing.issuer_ticker,
        data_quality={},
        **kwargs,
    )
    db.add(tx)
    db.commit()
    return tx


def _filing(db: Session, ticker: str, accession: str) -> InsiderFiling:
    filing = InsiderFiling(
        accession_number=accession, form="4", is_amendment=False,
        issuer_cik="0001", issuer_ticker=ticker, issuer_name=ticker,
        filing_date=date.today().isoformat(), parser_version="1.2",
        status="parsed",
    )
    db.add(filing)
    db.commit()
    return filing


def _seed_portfolio_and_watchlist(db: Session) -> None:
    rklb = _company(db, "RKLB", "Rocket Lab USA, Inc.")
    db.add(Position(company_id=rklb.id, quantity=100))
    _company(db, "INVA", "Innoviva, Inc.")
    db.add(WatchItem(symbol="INVA"))
    db.commit()


def test_operations_aggregates_buys_and_sales_per_insider(db):
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, "RKLB", "0001-26-000001")
    hoy = date.today().isoformat()
    ayer = (date.today() - timedelta(days=1)).isoformat()
    # Peter Beck: dos ventas y una compra.
    _tx(db, filing, fp_suffix="-1", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="S", shares=100.0, price=70.0, value=7000.0, tx_date=ayer)
    _tx(db, filing, fp_suffix="-2", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="S", shares=100.0, price=80.0, value=8000.0, tx_date=hoy)
    _tx(db, filing, fp_suffix="-3", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="P", shares=50.0, price=60.0, value=3000.0, tx_date=hoy)
    # Una concesion (codigo A): no es venta ni compra, no entra al agregado.
    _tx(db, filing, fp_suffix="-4", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="A", shares=999.0, price=0.0, value=0.0, tx_date=hoy)

    result = insider_operations(db, days=365)
    assert result["status"] == "ok"
    assert [c["ticker"] for c in result["companies"]] == ["RKLB"]
    assert result["companies_without_data"] == ["INVA"]

    rklb = result["companies"][0]
    assert rklb["origin"] == "cartera"
    assert rklb["excluded_codes"] == 1
    assert rklb["period"] == {"from": ayer, "to": hoy}
    assert rklb["totals"]["sell"]["trades"] == 2
    assert rklb["totals"]["sell"]["shares"] == 200.0
    assert rklb["totals"]["sell"]["value"] == 15000.0
    assert rklb["totals"]["sell"]["avg_price"] == 75.0
    assert rklb["totals"]["buy"]["value"] == 3000.0

    beck = rklb["insiders"][0]
    assert beck["insider"] == "BECK PETER"
    assert beck["officer_title"] == "CEO"
    assert beck["sell"]["trades"] == 2
    assert beck["sell"]["avg_price"] == 75.0
    assert beck["buy"]["trades"] == 1
    assert beck["last_tx"] == hoy


def test_operations_declares_missing_values_and_empty_universe(db):
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, "INVA", "0001-26-000002")
    hoy = date.today().isoformat()
    _tx(db, filing, fp_suffix="-1", insider="DOE JANE", role="Director",
        officer_title=None, code="S", shares=10.0, price=None, value=None, tx_date=hoy)

    result = insider_operations(db, days=365)
    inva = next(c for c in result["companies"] if c["ticker"] == "INVA")
    assert inva["txs_without_value"] == 1
    # Sin importe no se imputa: suma 0 y precio medio None, nunca inventado.
    assert inva["totals"]["sell"]["value"] == 0.0
    assert inva["totals"]["sell"]["avg_price"] is None
    assert inva["origin"] == "watchlist"


def test_operations_ignores_transactions_outside_period(db):
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, "RKLB", "0001-26-000003")
    vieja = (date.today() - timedelta(days=400)).isoformat()
    _tx(db, filing, fp_suffix="-1", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="S", shares=100.0, price=70.0, value=7000.0, tx_date=vieja)

    result = insider_operations(db, days=365)
    assert result["companies"] == []
    assert "RKLB" in result["companies_without_data"]
