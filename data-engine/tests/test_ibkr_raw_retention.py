"""A7: retención de ibkr_raw_rows. Solo caducan las fotos diarias antiguas."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, IbkrRawRow, Position
from app.services.ibkr_raw_retention import prune_ibkr_raw_rows
from app.services.portfolio_ledger_service import PortfolioLedgerService

TODAY = date(2026, 10, 30)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _row(db, section, path, day, n):
    payload = {"symbol": "AAPL", "reportDate": day.strftime("%Y%m%d") if day else ""}
    db.add(IbkrRawRow(section=section, path=path, row_hash=f"h{n}", payload=payload))


def test_poda_fotos_antiguas_y_conserva_eventos_recientes_y_fecha_de_coste(db):
    company = PortfolioLedgerService().ensure_company(db, "AAPL")
    db.add(Position(company_id=company.id, quantity=Decimal("1"), as_of=TODAY,
                    statement_as_of=date(2024, 3, 1)))
    _row(db, "OpenPositions", "OpenPositions/OpenPosition", date(2024, 1, 2), 1)  # foto vieja -> fuera
    _row(db, "ConversionRates", "ConversionRates/ConversionRate", date(2024, 1, 2), 2)  # foto vieja -> fuera
    _row(db, "OpenPositions", "OpenPositions/OpenPosition", date(2024, 3, 1), 3)  # fecha de coste -> se queda
    _row(db, "OpenPositions", "OpenPositions/OpenPosition", date(2026, 10, 29), 4)  # reciente -> se queda
    _row(db, "Trades", "Trades/Trade", date(2023, 5, 5), 5)  # evento -> nunca caduca
    _row(db, "CashReport", "CashReport/CashReportCurrency", None, 6)  # sin fecha -> se queda
    db.flush()

    assert prune_ibkr_raw_rows(db, keep_days=400, today=TODAY) == 2
    kept = sorted(db.scalars(select(IbkrRawRow.row_hash)).all())
    assert kept == ["h3", "h4", "h5", "h6"]


def test_keep_days_cero_desactiva_la_poda(db):
    _row(db, "OpenPositions", "OpenPositions/OpenPosition", date(2020, 1, 2), 1)
    db.flush()
    assert prune_ibkr_raw_rows(db, keep_days=0, today=TODAY) == 0
    assert db.scalars(select(IbkrRawRow)).first() is not None


def test_default_de_retencion_es_400_dias():
    from app.core.config import Settings

    assert Settings.model_fields["ibkr_raw_rows_retention_days"].default == 400
