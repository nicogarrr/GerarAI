"""Bancos/aseguradoras/REITs y SOTP: acciones ajustadas por splits posteriores.

Libro tangible 1.000 y 100 acciones del ejercicio 2024; split 2:1 el
01-05-2025. Hoy hay 200 acciones: libro/accion 5, no 10. Valor base del banco
= libro/accion x (ROE - g) / (Ke - g) = 5 x 0,10 / 0,06 = 8,333 (antes 16,667,
el doble del real frente a un precio que ya refleja el split).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, CorporateAction, FinancialFact
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.sector_specific import BankValuationEngine
from tests.test_adr_sector_engines import BANK, _Snap


def _bank_db(split: bool) -> tuple[Session, Company]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    company = Company(ticker="SPLITBK", name="Split Bank", currency="USD", exchange="NYSE",
                      sector="Financials", industry="Banks", company_type="bank",
                      valuation_model="bank_residual_income", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.flush()
    for metric, value in BANK.items():
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(str(value)),
                             unit="decimal" if abs(value) < 1 else "USD",
                             period="2024-12-31:FY", fiscal_year=2024, fiscal_quarter="FY",
                             filed=date(2025, 2, 20), source_type="SEC", is_reported=True,
                             confidence=Decimal("0.9")))
    if split:
        db.add(CorporateAction(company_id=company.id, action_type="split",
                               effective_date=date(2025, 5, 1), ratio=Decimal("2"),
                               description="2:1"))
    db.commit()
    return db, company


def _value(split: bool, price: float) -> dict:
    db, company = _bank_db(split)
    try:
        return BankValuationEngine().value(ValuationContext(
            db=db, company=company, snapshot=_Snap({"shares_diluted": 100.0}),
            current_price=price, engine_key="bank"))
    finally:
        db.close()


def test_bank_book_per_share_follows_a_split_after_the_fiscal_year():
    before = _value(False, 10.0)
    after = _value(True, 5.0)
    assert before["base_value"] == pytest.approx(10 * 0.10 / 0.06)
    assert after["base_value"] == pytest.approx(5 * 0.10 / 0.06)
    assert after["margin_of_safety"] == pytest.approx(before["margin_of_safety"])
