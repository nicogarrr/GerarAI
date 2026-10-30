"""CSV sin columna currency: la divisa sale del sufijo de bolsa, no siempre USD."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService, _csv_default_currency

NO_CURRENCY = """symbol,action,quantity,price,date
SAN.MC,buy,10,4.12,2025-01-10
VOLV-B.ST,buy,5,250,2025-01-10
ZZUS,buy,1,150,2025-01-10
"""


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="csv-currency-test", name="csv currency")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def _currencies(db):
    rows = db.execute(select(Company.ticker, Transaction.currency).join(Company, Company.id == Transaction.company_id)).all()
    return {ticker: currency for ticker, currency in rows}


def test_csv_without_currency_uses_the_exchange_currency():
    db = _session()
    result = IBKRImportService().import_ibkr_csv(db, NO_CURRENCY)
    assert result["rows_skipped"] == 0, result["row_errors"]
    assert _currencies(db) == {"SAN.MC": "EUR", "VOLV-B.ST": "SEK", "ZZUS": "USD"}


def test_reimport_of_the_same_file_does_not_duplicate():
    db = _session()
    IBKRImportService().import_ibkr_csv(db, NO_CURRENCY)
    again = IBKRImportService().import_ibkr_csv(db, NO_CURRENCY)
    assert again["trades_imported"] == 0
    assert again["duplicate_trades"] == 3


def test_explicit_currency_and_subunit_exchanges():
    assert _csv_default_currency("BP.L") == "USD"  # peniques o libras: no se adivina
    assert _csv_default_currency("SAP.DE") == "EUR"
    assert _csv_default_currency("ZZ", "CHF") == "CHF"
    assert _csv_default_currency("ZZ.L", "GBX") == "USD"
