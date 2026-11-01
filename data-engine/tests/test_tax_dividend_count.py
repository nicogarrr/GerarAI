"""Impuestos: «Dividendos (nº)» cuenta los cobros, no las empresas.

El resumen fiscal devolvía ``dividend_count = len(dividends)``, el número de
bloques por ticker: dos cobros de la misma empresa salían como «1» en la
pantalla de Impuestos («Dividendos (nº)»). Las retenciones no son cobros.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company
from app.services.portfolio_ledger_service import PortfolioLedgerService
from app.services.tax_report_service import TaxReportService


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for ticker in ("KO", "PEP"):
            session.add(
                Company(
                    ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
                    sector="Consumer", company_type="operating", valuation_model="dcf",
                )
            )
        session.commit()
        yield session


def _cash(db: Session, ticker: str, action: str, amount: str, day: date) -> None:
    PortfolioLedgerService().create_transaction(
        db, ticker=ticker, action=action, quantity=Decimal("1"), price=Decimal(amount),
        trade_date=day, fees=Decimal("0"), currency="EUR",
    )


def test_dividend_count_cuenta_cada_cobro(db: Session):
    _cash(db, "KO", "dividend", "10", date(2025, 4, 1))
    _cash(db, "KO", "dividend", "10", date(2025, 7, 1))
    _cash(db, "KO", "withholding", "1.5", date(2025, 7, 1))
    _cash(db, "PEP", "dividend", "8", date(2025, 6, 1))

    summary = TaxReportService().compute_report(db, 2025)["summary"]

    assert summary["total_dividends_base"] == 28.0
    assert summary["dividend_count"] == 3


def test_dividend_count_sin_cobros_es_cero(db: Session):
    summary = TaxReportService().compute_report(db, 2025)["summary"]
    assert summary["dividend_count"] == 0
