"""La exportación anual incluye las operaciones de caja sin empresa.

Intereses, depósitos, retiradas y comisiones de cuenta se guardan con
``company_id`` NULL (IBKR Flex). El JOIN interno con Company las dejaba fuera
de la «red de seguridad» anual, aunque los intereses tributan en el IRPF.
"""
import asyncio
import csv
import io
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.export import export_year
from app.core.database import Base
from app.models import Company, TaxReport, Transaction


def _body(response):
    async def collect():
        return b"".join([x if isinstance(x, bytes) else x.encode() async for x in response.body_iterator])

    return asyncio.run(collect()).decode("utf-8-sig")


def _seed(db: Session) -> None:
    company = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD", company_type="operating", valuation_model="dcf")
    db.add(company)
    db.flush()
    db.add_all(
        [
            Transaction(company_id=company.id, trade_date=date(2026, 3, 2), action="buy",
                        quantity=Decimal("2"), price=Decimal("150"), fees=Decimal("1"), currency="USD"),
            Transaction(company_id=None, trade_date=date(2026, 4, 1), action="interest",
                        quantity=Decimal("1"), price=Decimal("12.34"), fees=Decimal("0"), currency="EUR",
                        external_id="int-1"),
            Transaction(company_id=None, trade_date=date(2026, 5, 1), action="fee",
                        quantity=Decimal("1"), price=Decimal("-3"), fees=Decimal("0"), currency="USD",
                        external_id="fee-1"),
            # Otro año: sigue fuera.
            Transaction(company_id=None, trade_date=date(2025, 12, 31), action="interest",
                        quantity=Decimal("1"), price=Decimal("9"), fees=Decimal("0"), currency="EUR"),
        ]
    )
    db.add(TaxReport(fiscal_year=2026, summary={}, dividends=[], realized=[], misc={}))
    db.commit()


def test_json_export_keeps_cash_transactions_without_company():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        rows = json.loads(_body(export_year(2026, format="json", db=db)))["transactions"]
    assert [(r["date"], r["ticker"], r["action"], r["price"]) for r in rows] == [
        ("2026-03-02", "AAPL", "buy", 150.0),
        ("2026-04-01", None, "interest", 12.34),
        ("2026-05-01", None, "fee", -3.0),
    ]
    assert rows[1]["currency"] == "EUR"
    assert rows[1]["external_id"] == "int-1"


def test_csv_export_keeps_cash_transactions_with_empty_ticker():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        rows = list(csv.reader(io.StringIO(_body(export_year(2026, format="csv", db=db)))))
    tx = [r for r in rows[1:] if r[0] == "transaction"]
    assert [(r[1], r[2], r[3], r[5]) for r in tx] == [
        ("2026-03-02", "AAPL", "buy", "150.0"),
        ("2026-04-01", "", "interest", "12.34"),
        # Importe negativo: número, no texto con apóstrofo anti-fórmula.
        ("2026-05-01", "", "fee", "-3.0"),
    ]
