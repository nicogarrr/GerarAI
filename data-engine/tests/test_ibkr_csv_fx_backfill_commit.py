"""Un backfill del BCE con exito (escribe y hace commit) no debe romper el CSV.

Reproduccion hermetica del fallo: importar un CSV historico en USD sin tipos
guardados dispara la descarga del BCE (#2349) desde ``ensure_historical_fx``,
cuya escritura hace ``db.commit()`` dentro del ``with db.begin_nested()`` de la
fila en curso. El savepoint muere y la importacion entera se cae con
InvalidRequestError a mitad del fichero (y las filas ya procesadas quedan
comiteadas a medias por ese commit ajeno). La suite no lo veia: con
APP_ENV=test el backfill solo corre inyectado y los stubs no commitean.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import FXRate, Tenant, Transaction
from app.services import portfolio_ledger_service as ledger_mod
from app.services.ibkr_import_service import IBKRImportService
from app.services.portfolio_ledger_service import PortfolioLedgerService

CSV_TWO_BUYS = (
    "symbol,action,quantity,price,date,fees,currency\n"
    "ZZBK,buy,10,100.50,01/06/2025,1.25,USD\n"
    "ZZBK,buy,5,101.75,02/03/2025,0,USD\n"
)


@pytest.fixture
def db():
    ledger_mod._ECB_BACKFILL_TRIED.clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="csv-fx-commit", name="csv fx commit")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _committing_backfill(db, currencies, start, end):
    """Simula una descarga BCE con exito: escribe el tipo y COMMITEA."""
    db.add(
        FXRate(
            base_currency="EUR",
            quote_currency="USD",
            rate=Decimal("0.92"),
            rate_date=end,
            source="ecb",
        )
    )
    db.commit()
    return {"source": "ecb", "written": {"USD": 1}, "not_published": []}


def test_successful_ecb_backfill_does_not_break_csv_import(db, monkeypatch):
    real = PortfolioLedgerService
    monkeypatch.setattr(
        ledger_mod,
        "PortfolioLedgerService",
        lambda: real(fx_backfill=_committing_backfill),
    )
    result = IBKRImportService().import_ibkr_csv(db, CSV_TWO_BUYS)
    assert result["trades_imported"] == 2
    rows = sorted(
        (float(t.quantity), float(t.price), t.trade_date)
        for t in db.query(Transaction).all()
    )
    assert rows == [
        (5.0, 101.75, date(2025, 2, 3)),
        (10.0, 100.50, date(2025, 1, 6)),
    ]
    # El tipo descargado persiste (esa era la intencion del backfill).
    assert db.query(FXRate).count() == 1


def test_rows_before_and_after_backfill_keep_their_own_data(db, monkeypatch):
    """La fila que disparo el backfill no puede quedar comiteada a medias."""
    real = PortfolioLedgerService
    monkeypatch.setattr(
        ledger_mod,
        "PortfolioLedgerService",
        lambda: real(fx_backfill=_committing_backfill),
    )
    IBKRImportService().import_ibkr_csv(db, CSV_TWO_BUYS)
    first = [t for t in db.query(Transaction).all() if float(t.quantity) == 10.0][0]
    assert float(first.fees) == 1.25
    assert first.currency == "USD"
