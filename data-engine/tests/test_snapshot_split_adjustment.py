"""Splits posteriores al cierre en el snapshot de valoracion.

El precio es el de hoy y las acciones, las del ultimo ejercicio publicado. Un
split 4:1 efectivo entre ambos dejaba el valor razonable por accion x4 frente a
un precio ya dividido entre 4 (margen de seguridad inflado: 87 % en vez de 49 %).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models import CorporateAction
from app.valuation.engines.standard_dcf import StandardDCFEngine
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from tests.test_snapshot_pit_filed import _db_with_facts


def _split(db, company, when: date, ratio: str) -> None:
    db.add(
        CorporateAction(
            company_id=company.id,
            action_type="split" if Decimal(ratio) >= 1 else "reverse_split",
            effective_date=when,
            ratio=Decimal(ratio),
            description=f"split {ratio}",
        )
    )
    db.commit()


def _dcf(db, company, price: float) -> dict:
    engine = StandardDCFEngine()
    return engine.value(engine.build_context(db, company, price))


def test_split_after_fiscal_year_divides_value_per_share():
    """FY2024 (100 acciones, publicado 01-03-2025), split 4:1 el 01-06-2025.

    Mismo negocio, mismo valor total: por accion nueva vale 1/4 del valor por
    accion antigua, y el margen frente a 10/4 = 2,5 es el mismo que frente a 10.
    """
    db, company = _db_with_facts(filed=date(2025, 3, 1))
    try:
        before = _dcf(db, company, 10.0)
        _split(db, company, date(2025, 6, 1), "4")
        after = _dcf(db, company, 2.5)
        snapshot = FinancialSnapshotBuilder().build(db, company)
    finally:
        db.close()
    assert snapshot.value("shares_diluted") == pytest.approx(400.0)
    assert after["expected_value"] == pytest.approx(before["expected_value"] / 4)
    assert after["margin_of_safety"] == pytest.approx(before["margin_of_safety"])


def test_filing_published_after_the_split_is_already_restated():
    """10-K publicado el 15-02-2025 tras un split del 10-02-2025: ya viene
    reexpresado (ASC 260), no se vuelve a multiplicar."""
    db, company = _db_with_facts(filed=date(2025, 2, 15))
    try:
        _split(db, company, date(2025, 2, 10), "4")
        snapshot = FinancialSnapshotBuilder().build(db, company)
    finally:
        db.close()
    assert snapshot.value("shares_diluted") == pytest.approx(100.0)
    assert "shares_diluted" not in snapshot.split_factors


def test_split_after_as_of_does_not_touch_a_replay():
    """Valoracion a 30-06-2025 con un split del 01-09-2025: el precio de esa
    fecha es anterior al split, las acciones tambien."""
    db, company = _db_with_facts(filed=date(2025, 3, 1))
    try:
        _split(db, company, date(2025, 9, 1), "4")
        snapshot = FinancialSnapshotBuilder().build(db, company, as_of=date(2025, 6, 30))
    finally:
        db.close()
    assert snapshot.value("shares_diluted") == pytest.approx(100.0)


def test_reverse_split_after_fiscal_year():
    """Contrasplit 1:10 (ratio 0,1): 100 acciones pasan a 10."""
    db, company = _db_with_facts(filed=date(2025, 3, 1))
    try:
        _split(db, company, date(2025, 5, 1), "0.1")
        snapshot = FinancialSnapshotBuilder().build(db, company)
    finally:
        db.close()
    assert snapshot.value("shares_diluted") == pytest.approx(10.0)
