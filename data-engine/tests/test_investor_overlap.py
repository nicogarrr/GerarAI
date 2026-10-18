from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FundManager, ManagerHolding, Position
from app.models.entities import Base, InstrumentReference
from app.services.investor_overlap import _cusip, holders_by_ticker, portfolio_overlap


def setup_portfolio():
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", company_type="mature", valuation_model="dcf", isin="US0378331005")
    private = Company(ticker="PRIVATE", name="Private", exchange="NASDAQ", company_type="mature", valuation_model="dcf")
    db.add_all([company, private])
    db.flush()
    db.add_all([Position(tenant_id=1, company_id=company.id, quantity=2),
                Position(tenant_id=2, company_id=private.id, quantity=2)])
    manager = FundManager(tenant_id=1, cik="0001067983", name="Berkshire", last_report_date=date(2026, 6, 30), coverage="partial")
    db.add(manager)
    db.flush()
    for accession, filing, cusip, put_call in [("A-1", date(2026, 8, 14), "037833100", ""),
                                               ("A-2", date(2026, 8, 20), "037833100", ""),
                                               ("A-2", date(2026, 8, 20), "037833100", "CALL")]:
        db.add(ManagerHolding(tenant_id=1, manager_id=manager.id, accession_number=accession, report_date=date(2026, 6, 30),
                              filing_date=filing, name_of_issuer="Apple", title_of_class="COM", cusip=cusip,
                              put_call=put_call, value_usd_thousands=Decimal(100), shares=Decimal(10),
                              filing_url="https://www.sec.gov/Archives/example"))
    db.commit()
    db.info["tenant_id"] = 1
    # El fixture debe tener informes del tenant. NULL queda fuera correctamente.
    assert db.query(FundManager).count() == 1
    assert db.query(ManagerHolding).count() == 3
    return db


def test_exact_isin_derivation_and_invalid_checksum():
    company = Company(isin="US0378331005")
    assert _cusip(company, None)[0] == "037833100"
    company.isin = "US0378331006"
    assert _cusip(company, None) == (None, "ISIN registrado sin CUSIP derivable verificado.")
    company.isin = "GB0378331005"
    assert _cusip(company, None) == (None, "ISIN registrado sin CUSIP derivable verificado.")


def test_overlap_latest_filing_no_options_no_other_tenant():
    result = portfolio_overlap(setup_portfolio())
    assert result["status"] == "ok" and result["kind"] == "derivado"
    assert len(result["positions"]) == 1
    position = result["positions"][0]
    assert position["status"] == "coincidencia" and len(position["holders"]) == 1
    assert position["holders"][0]["filing_date"] == "2026-08-20"
    assert position["holders"][0]["report_date"] == "2026-06-30"
    assert position["holders"][0]["coverage"] == "partial"


def test_unknown_identity_never_claims_not_owned(monkeypatch):
    db = setup_portfolio()
    company = db.query(Company).filter_by(ticker="AAPL").one()
    company.isin = None
    db.commit()
    import app.services.investor_overlap as overlap
    monkeypatch.setattr(overlap, "most_bought", lambda db: {"items": [{"cusip": "123456789", "buyers_count": 3}], "report_dates": []})
    result = portfolio_overlap(db)
    assert result["unresolved_positions"] == 1
    assert result["not_owned"] == []
    assert result["positions"][0]["status"] == "sin_identificador"


def test_reference_exact_ticker_can_match_without_isin():
    db = setup_portfolio()
    company = db.query(Company).filter_by(ticker="AAPL").one()
    company.isin = None
    db.add(InstrumentReference(ticker_normalized="AAPL", cusip="037833100", source="openfigi", as_of=date(2026, 10, 1)))
    db.commit()
    assert portfolio_overlap(db)["positions"][0]["status"] == "coincidencia"


def test_empty_and_missing_tenant():
    db = setup_portfolio()
    db.info.clear()
    assert portfolio_overlap(db)["status"] == "sin_datos"
    db.info["tenant_id"] = 9
    assert portfolio_overlap(db)["positions"] == []


def test_joint_buys_exclude_owned_and_single_buyers(monkeypatch):
    db = setup_portfolio()
    import app.services.investor_overlap as overlap
    monkeypatch.setattr(overlap, "most_bought", lambda db: {"items": [
        {"cusip": "037833100", "buyers_count": 3},
        {"cusip": "111111111", "buyers_count": 1},
        {"cusip": "222222222", "buyers_count": 2},
    ], "report_dates": ["2026-06-30"]})
    result = portfolio_overlap(db)
    assert result["not_owned"] == [{"cusip": "222222222", "buyers_count": 2}]
    assert result["comparison_complete"] is False


def test_contradictory_reference_rejected_even_if_ticker_matches():
    company = Company(ticker="AAPL", isin="US0378331005")
    reference = InstrumentReference(ticker_normalized="AAPL", isin="US5949181045",
                                    cusip="594918104", source="openfigi", as_of=date(2026, 10, 1))
    cusip, reason = _cusip(company, reference)
    assert cusip is None and "conflicto" in reason
    reference.isin = None
    assert _cusip(company, reference)[0] is None
    reference.cusip = "037833100"
    assert _cusip(company, reference)[0] == "037833100"


def test_reference_internal_conflict_malformed_and_bad_isin_checksum():
    company = Company(ticker="AAPL")
    reference = InstrumentReference(ticker_normalized="AAPL", isin="US0378331005",
                                    cusip="594918104", source="openfigi", as_of=date(2026, 10, 1))
    assert _cusip(company, reference)[0] is None
    reference.cusip = "INVALID"
    assert _cusip(company, reference)[0] is None
    reference.cusip = "037833100"
    reference.isin = "US0378331006"
    assert _cusip(company, reference)[0] is None
    reference.isin = None
    company.isin = "US0378331006"
    assert _cusip(company, reference)[0] is None


def test_identity_conflict_never_matches_or_claims_not_owned(monkeypatch):
    db = setup_portfolio()
    db.add(InstrumentReference(ticker_normalized="AAPL", isin="US5949181045",
                              cusip="594918104", source="openfigi", as_of=date(2026, 10, 1)))
    db.commit()
    result = portfolio_overlap(db)
    assert result["positions"][0]["status"] == "sin_identificador"
    assert "conflicto" in result["positions"][0]["identity_source"]
    assert result["not_owned"] == []


def test_portfolio_companies_query_no_distinct_sobre_entidad():
    """Postgres no tiene operador de igualdad para json: SELECT DISTINCT
    companies.* revienta en prod (500 en /api/investors/portfolio-overlap)
    aunque sqlite lo tolera. La deduplicacion debe vivir en una subquery de
    ids, no sobre la entidad con columnas JSON."""
    from sqlalchemy.dialects import postgresql

    db = setup_portfolio()
    statements = []
    original = db.scalars

    def recording_scalars(statement, *args, **kwargs):
        statements.append(statement)
        return original(statement, *args, **kwargs)

    db.scalars = recording_scalars  # type: ignore[method-assign]
    try:
        portfolio_overlap(db)
    finally:
        db.scalars = original  # type: ignore[method-assign]

    assert statements, "portfolio_overlap no consulto la base de datos"
    outer_sql = str(statements[0].compile(dialect=postgresql.dialect())).upper()
    companies_select = outer_sql.split("FROM COMPANIES")[0]
    assert "DISTINCT" not in companies_select, (
        "SELECT DISTINCT sobre companies.* es invalido en postgres (columnas json): "
        + companies_select
    )


def test_holders_by_ticker_reverse_lookup():
    result = holders_by_ticker(setup_portfolio(), "aapl")
    assert result is not None and result["status"] == "ok"
    assert result["cusip"] == "037833100"
    assert len(result["holders"]) == 1
    holder = result["holders"][0]
    assert holder["slug"] == "buffett"
    assert holder["filing_date"] == "2026-08-20"  # la enmienda A-2 sustituye al filing base
    assert holder["value_usd"] == 100.0
    assert result["managers_with_data"] == 1


def test_holders_by_ticker_unknown_company_returns_none():
    assert holders_by_ticker(setup_portfolio(), "NOEXISTE") is None


def test_holders_by_ticker_without_identity_claims_nothing():
    db = setup_portfolio()
    company = db.query(Company).filter_by(ticker="AAPL").one()
    company.isin = None
    db.commit()
    result = holders_by_ticker(db, "AAPL")
    assert result["status"] == "sin_identificador"
    assert result["holders"] == []
