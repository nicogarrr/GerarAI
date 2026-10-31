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
    assert rklb["excluded_derivative"] == 0
    assert rklb["rows_without_date"] == 0
    assert rklb["period"] == {"from": ayer, "to": hoy}
    assert rklb["totals"]["sell"]["trades"] == 2
    assert rklb["totals"]["sell"]["shares"] == 200.0
    assert rklb["totals"]["sell"]["value"] == 15000.0
    assert rklb["totals"]["sell"]["avg_price"] == 75.0
    assert rklb["totals"]["sell"]["rows_without_value"] == 0
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
    # Sin importe no se imputa: suma 0, medio None (nunca 0.0 que pareceria
    # dato) y las acciones sin valor declaradas aparte.
    assert inva["totals"]["sell"]["value"] == 0.0
    assert inva["totals"]["sell"]["avg_price"] is None
    assert inva["totals"]["sell"]["rows_without_value"] == 1
    assert inva["totals"]["sell"]["shares_without_value"] == 10.0
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


def test_operations_excludes_derivatives_and_other_codes(db):
    """Auditor #1896: mismo filtro que el feed — derivados fuera y declarados."""
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, "RKLB", "0001-26-000010")
    hoy = date.today().isoformat()
    _tx(db, filing, fp_suffix="-1", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="S", shares=100.0, price=70.0, value=7000.0, tx_date=hoy)
    _tx(db, filing, fp_suffix="-2", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="S", shares=50.0, price=1.0, value=50.0, tx_date=hoy,
        is_derivative=True)
    _tx(db, filing, fp_suffix="-3", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="M", shares=10.0, price=0.0, value=0.0, tx_date=hoy)

    result = insider_operations(db, days=365)
    rklb = result["companies"][0]
    assert rklb["totals"]["sell"]["trades"] == 1
    assert rklb["totals"]["sell"]["value"] == 7000.0
    assert rklb["excluded_derivative"] == 1
    assert rklb["excluded_codes"] == 1


def test_operations_partial_priced_rows_make_avg_none(db):
    """Auditor #1896: value de unas filas y shares de todas subestimaba el
    medio. Con una fila sin importe, el medio es None y se declara."""
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, "RKLB", "0001-26-000011")
    hoy = date.today().isoformat()
    _tx(db, filing, fp_suffix="-1", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="S", shares=100.0, price=70.0, value=7000.0, tx_date=hoy)
    _tx(db, filing, fp_suffix="-2", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="S", shares=100.0, price=None, value=None, tx_date=hoy)

    result = insider_operations(db, days=365)
    sell = result["companies"][0]["totals"]["sell"]
    assert sell["trades"] == 2
    assert sell["shares"] == 200.0
    assert sell["avg_price"] is None
    assert sell["shares_without_value"] == 100.0
    assert sell["rows_without_value"] == 1


def test_operations_company_without_ps_is_not_zero_row(db):
    """Auditor #1896: empresa con filings pero sin P/S va a sin-datos."""
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, "RKLB", "0001-26-000012")
    hoy = date.today().isoformat()
    _tx(db, filing, fp_suffix="-1", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="A", shares=10.0, price=0.0, value=0.0, tx_date=hoy)

    result = insider_operations(db, days=365)
    assert result["companies"] == []
    assert result["companies_without_data"] == ["INVA", "RKLB"]


def test_operations_coalesces_tx_date_with_filing_date(db):
    """Auditor #1896: fecha efectiva = coalesce(tx_date, filing_date); las
    filas sin ninguna fecha suman pero se declaran y no marcan el periodo."""
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, "RKLB", "0001-26-000013")
    filing.filing_date = date.today().isoformat()
    db.commit()
    _tx(db, filing, fp_suffix="-1", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="S", shares=100.0, price=70.0, value=7000.0, tx_date=None)

    result = insider_operations(db, days=365)
    rklb = result["companies"][0]
    assert rklb["totals"]["sell"]["trades"] == 1
    assert rklb["period"]["from"] == filing.filing_date
    assert rklb["rows_without_date"] == 0

    filing2 = _filing(db, "INVA", "0001-26-000014")
    filing2.filing_date = None
    db.commit()
    _tx(db, filing2, fp_suffix="-1", insider="DOE JANE", role="Director",
        officer_title=None, code="S", shares=5.0, price=1.0, value=5.0, tx_date=None)
    result = insider_operations(db, days=365)
    inva = next(c for c in result["companies"] if c["ticker"] == "INVA")
    assert inva["totals"]["sell"]["trades"] == 1
    assert inva["rows_without_date"] == 1
    assert inva["period"] == {"from": None, "to": None}


def test_without_data_detail_says_why_never_a_generic_no_data(db):
    from app.services.insider_operations import _without_data_reason

    us = _company(db, "BN", "Brookfield Corporation")
    us.cik = "0001001085"
    uk = _company(db, "CGEO.L", "Georgia Capital PLC")
    uk.exchange = "LSE"
    otc = _company(db, "KRKNF", "Kraken Robotics")
    otc.exchange = "OTC PINK"
    nocik = _company(db, "XYZ", "Xyz Inc")

    assert _without_data_reason("CGEO.L", uk, False)["reason"] == "foreign_issuer_no_form4"
    assert _without_data_reason("KRKNF", otc, False)["reason"] == "otc_no_cik"
    assert _without_data_reason("BN", us, False)["reason"] == "no_form4_as_issuer"
    assert _without_data_reason("XYZ", nocik, False)["reason"] == "cik_unresolved"
    assert _without_data_reason("BN", us, True)["reason"] == "no_open_market_trades"


def test_dotted_us_tickers_with_cik_are_never_called_foreign(db):
    from app.services.insider_operations import _without_data_reason

    for tk, name in (("BRK.B", "Berkshire Hathaway B"), ("BF.B", "Brown-Forman B")):
        co = _company(db, tk, name)
        co.exchange = "NYSE"
        co.cik = "0000000001"
        assert _without_data_reason(tk, co, False)["reason"] == "no_form4_as_issuer"
    # Sin CIK y con sufijo: sigue siendo extranjero sin registro SEC.
    uk = _company(db, "CGEO.L", "Georgia Capital")
    uk.exchange = "LSE"
    assert _without_data_reason("CGEO.L", uk, False)["reason"] == "foreign_issuer_no_form4"


def test_us_exchange_or_empty_exchange_without_cik_is_unresolved_not_foreign(db):
    from app.services.insider_operations import _without_data_reason

    brk = _company(db, "BRK.B", "Berkshire Hathaway B")
    brk.exchange = "NYSE"
    assert _without_data_reason("BRK.B", brk, False)["reason"] == "cik_unresolved"
    blank = _company(db, "FOO.X", "Foo")
    blank.exchange = ""
    assert _without_data_reason("FOO.X", blank, False)["reason"] == "cik_unresolved"


def test_operations_prefilters_universe_in_sql(db):
    """El agregado solo mira cartera + watchlist: el universo Form 4 no debe
    cargarse entero (986 ms medidos en prod, barrido 2026-10-31). El prefiltro
    SQL es un SUPERCONJUNTO (cualquier columna de ticker crudo que normalice a
    una seguida); el filtro exacto sigue siendo el de Python."""
    from sqlalchemy import event

    _seed_portfolio_and_watchlist(db)
    hoy = date.today().isoformat()
    # 60 emisores NO seguidos con ventas: ruido que el prefiltro debe evitar.
    for i in range(60):
        noise = _filing(db, f"ZZ{i:02d}", f"9999-26-{i:06d}")
        _tx(db, noise, fp_suffix="-n", insider="NOBODY", role="Director",
            officer_title=None, code="S", shares=10.0, price=1.0, value=10.0, tx_date=hoy)
    filing = _filing(db, "RKLB", "0001-26-000100")
    _tx(db, filing, fp_suffix="-1", insider="BECK PETER", role="Officer",
        officer_title="CEO", code="P", shares=50.0, price=60.0, value=3000.0, tx_date=hoy)

    engine = db.get_bind()
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = insider_operations(db, days=365)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    # Resultado intacto: solo la seguida agrega.
    assert [c["ticker"] for c in result["companies"]] == ["RKLB"]
    assert result["companies"][0]["totals"]["buy"]["value"] == 3000.0
    # Y la consulta principal va prefiltrada por ticker (no carga el universo).
    joined = [
        s for s in statements
        if "insider_transactions" in s and "JOIN" in s.upper() and "insider_filings" in s
    ]
    assert joined, "consulta principal no encontrada entre las emitidas"
    assert any("issuer_ticker IN" in s for s in joined), (
        "la consulta principal no lleva prefiltro SQL por issuer_ticker"
    )


def test_operations_prefilter_keeps_multiclass_raw_tickers(db):
    """Emisor multiclase: crudo "LEN, LEN.B" con seguida LEN. El prefiltro SQL
    debe aceptar el valor crudo aunque no sea literalmente la seguida."""
    from app.models.entities import WatchItem

    company = _company(db, "LEN", "Lennar Corp.")
    db.add(WatchItem(symbol="LEN"))
    db.commit()
    hoy = date.today().isoformat()
    filing = _filing(db, "LEN, LEN.B", "0001-26-000200")
    _tx(db, filing, fp_suffix="-1", insider="MILLER STUART", role="Officer",
        officer_title="CEO", code="P", shares=100.0, price=150.0, value=15000.0, tx_date=hoy)

    result = insider_operations(db, days=365)
    assert [c["ticker"] for c in result["companies"]] == ["LEN"]
    assert result["companies"][0]["totals"]["buy"]["value"] == 15000.0
