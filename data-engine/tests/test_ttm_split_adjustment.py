"""BPA TTM y acciones con un split entre trimestres (regla fact_split_factor).

Calculo independiente: split 10:1 efectivo el 15/07/2026. Trimestres con BPA
presentado 1,00 / 1,20 / 1,40 (10-Q anteriores al split, base vieja) y 0,16
(10-Q del 30/06/2026 publicado el 01/08/2026, ya reexpresado).
BPA TTM en base actual = 0,10 + 0,12 + 0,14 + 0,16 = 0,52.
main sumaba bases mezcladas: 1,00 + 1,20 + 1,40 + 0,16 = 3,76 (7x).
Acciones: ultimo dato 100 (10-Q de 31/03 presentado antes del split si fuera
el ultimo) -> 1.000; aqui el ultimo es el reexpresado (1.000) y no se toca.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models import CorporateAction, FinancialFact
from app.services.ttm_service import build_company_ttm
from tests.test_ttm_service import _company, _metric, db  # noqa: F401  (fixture)

_Q = [
    ("2025-09-30", "Q1", "1.00", "2025-10-30", "95"),
    ("2025-12-31", "Q2", "1.20", "2026-01-30", "96"),
    ("2026-03-31", "Q3", "1.40", "2026-04-30", "100"),
    ("2026-06-30", "Q4", "0.16", "2026-08-01", "1000"),
]


def _seed(db, quarters):  # noqa: F811
    company = _company(db, "SPLT")
    for end, label, eps, filed, shares in quarters:
        for metric, value, unit in (("eps_diluted", eps, "USD/share"), ("shares_diluted", shares, "shares")):
            db.add(FinancialFact(
                company_id=company.id, metric=metric, value=Decimal(value), unit=unit,
                period=f"{end}:{label}", fiscal_quarter=label, source_type="SEC",
                is_reported=True, filed=date.fromisoformat(filed),
            ))
    db.add(CorporateAction(
        company_id=company.id, action_type="split", ratio=Decimal("10"),
        effective_date=date(2026, 7, 15), description="test split",
    ))
    db.commit()
    return company


def test_bpa_ttm_lleva_los_trimestres_previos_al_split_a_la_base_actual(db):  # noqa: F811
    payload = build_company_ttm(db, _seed(db, _Q))
    eps = _metric(payload, "eps_diluted")
    assert eps["basis"] == "TTM"
    assert Decimal(str(eps["value"])) == Decimal("0.52")
    shares = _metric(payload, "shares_diluted")
    assert Decimal(str(shares["value"])) == Decimal("1000")


def test_acciones_presentadas_antes_del_split_se_multiplican(db):  # noqa: F811
    payload = build_company_ttm(db, _seed(db, _Q[:3]))
    shares = _metric(payload, "shares_diluted")
    assert Decimal(str(shares["value"])) == Decimal("1000")
