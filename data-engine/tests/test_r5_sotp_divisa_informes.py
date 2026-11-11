"""Anclas del SOTP de un emisor que informa en otra divisa (r5-bugs, 11-nov-2026).

El modelo va entero en la moneda de los informes (``_reporting_currency``; un 40-F canadiense en CAD, un 20-F de
Taiwán en TWD), pero el SBC anual, el flujo de caja libre y las inversiones a corto se leían SOLO en USD: para esos
emisores salían N/D sin motivo (CNQ: SBC 180 M CAD del filing ignorado) aunque el dato estuviera en la base.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.entities import FinancialFact
from app.services.expert_team.sotp_valuer import sotp_anchors
from tests.test_sotp_agents import TODAY, _company, _seed_market, db  # noqa: F401


def _fy(db, company, metric, period, value, unit):  # noqa: F811
    db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit=unit, period=period,
                         fiscal_year=int(period[:4]), source_type="SEC", is_reported=True))
    db.flush()


def test_flujos_anuales_en_la_moneda_de_los_informes(db):  # noqa: F811
    company = _company(db)
    _seed_market(db, company)
    _fy(db, company, "revenue", "2026-09-30:FY", "41000000000", "CAD")
    _fy(db, company, "stock_based_compensation", "2026-09-30:FY", "180000000", "CAD")
    _fy(db, company, "free_cash_flow", "2026-09-30:FY", "-50000000", "CAD")
    anchors = sotp_anchors(db, company, today=TODAY)
    assert anchors["sbc_annual_millions"] == pytest.approx(180.0)
    assert anchors["sbc_period_end"] == "2026-09-30"
    assert anchors["annual_burn_millions"] == pytest.approx(50.0)
    assert anchors["stale_annual_notes"] == []


def test_no_mezcla_un_flujo_en_dolares_con_informes_en_otra_divisa(db):  # noqa: F811
    company = _company(db)
    _seed_market(db, company)
    _fy(db, company, "revenue", "2026-09-30:FY", "41000000000", "CAD")
    # Un SBC en USD (otra fuente u otra escala) no es la cifra del modelo en CAD: N/D, nunca mezclado.
    _fy(db, company, "stock_based_compensation", "2026-09-30:FY", "130000000", "USD")
    anchors = sotp_anchors(db, company, today=TODAY)
    assert anchors["sbc_annual_millions"] is None


def test_emisor_en_dolares_sin_cambios(db):  # noqa: F811
    company = _company(db)
    _seed_market(db, company)
    _fy(db, company, "revenue", "2026-09-30:FY", "4000000", "USD")
    _fy(db, company, "stock_based_compensation", "2026-09-30:FY", "47490000", "USD")
    anchors = sotp_anchors(db, company, today=TODAY)
    assert anchors["sbc_annual_millions"] == pytest.approx(47.49)
