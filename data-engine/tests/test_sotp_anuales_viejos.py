"""Flujos anuales viejos en las anclas del SOTP (carril regen, 9-nov-2026).

FRPH: el último SBC etiquetado es de 2020 y sus cuentas van por 2025; KKR: flujo de caja libre de 2019.
Un flujo anual de un ejercicio anterior al último presentado sale N/D con su motivo, nunca como «el anual».
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.entities import FinancialFact
from app.services.expert_team.sotp_valuer import sotp_anchors
from tests.test_sotp_agents import TODAY, _company, _seed_market, db  # noqa: F401


def _fy(db, company, metric, period, value, unit="USD"):  # noqa: F811
    db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit=unit, period=period,
                         fiscal_year=int(period[:4]), source_type="SEC", is_reported=True))
    db.flush()


def test_annual_sbc_and_fcf_older_than_the_latest_fiscal_year_are_nd_with_reason(db):  # noqa: F811
    company = _company(db)
    _seed_market(db, company)
    _fy(db, company, "stock_based_compensation", "2020-12-31:FY", "92000")
    _fy(db, company, "free_cash_flow", "2019-12-31:FY", "-50000000")
    _fy(db, company, "revenue", "2025-12-31:FY", "41000000")
    anchors = sotp_anchors(db, company, today=TODAY)
    assert anchors["sbc_annual_millions"] is None and anchors["sbc_period_end"] is None
    assert anchors["annual_burn_millions"] is None and anchors["burn_period_end"] is None
    notes = anchors["stale_annual_notes"]
    assert any("SBC anual N/D" in n and "2020-12-31" in n and "2025-12-31" in n for n in notes)
    assert any("Consumo de caja anual N/D" in n and "2019-12-31" in n for n in notes)


def test_annual_flows_of_the_latest_fiscal_year_are_kept(db):  # noqa: F811
    company = _company(db)
    _seed_market(db, company)
    _fy(db, company, "stock_based_compensation", "2025-12-31:FY", "47490000")
    _fy(db, company, "free_cash_flow", "2025-12-31:FY", "-1136258000")
    _fy(db, company, "revenue", "2025-12-31:FY", "4000000")
    anchors = sotp_anchors(db, company, today=TODAY)
    assert anchors["sbc_annual_millions"] == pytest.approx(47.49) and anchors["sbc_period_end"] == "2025-12-31"
    assert anchors["annual_burn_millions"] == pytest.approx(1136.258)
    assert anchors["stale_annual_notes"] == []


def test_stale_notes_reach_the_model_warnings():
    from app.services.expert_team.sotp_valuer import parse_proposal
    from tests.test_sotp_agents import ANCHORS, _good, _ledger

    note = "SBC anual N/D: el último dato es de 2020-12-31 y el ejercicio más reciente cierra el 2025-12-31"
    model, problems = parse_proposal(_good(), _ledger(), {**ANCHORS, "stale_annual_notes": [note]})
    assert problems == [] and note + "." in model["warnings"]


def test_unvalued_parts_say_the_total_is_a_floor_and_why_it_can_be_negative():
    from app.services.expert_team.sotp_valuer import parse_proposal
    from tests.test_sotp_agents import ANCHORS, _good, _ledger

    model, problems = parse_proposal(_good(), _ledger(), ANCHORS)
    assert problems == []
    floor = [w for w in model["warnings"] if w.startswith("Valor parcial")]
    assert len(floor) == 1 and "«Defensa»" in floor[0] and "sale" not in floor[0]  # vale > 0: solo el suelo
    # Deuda que pesa más que las partes valoradas (FRPH): el aviso explica el negativo.
    model, problems = parse_proposal(_good(), _ledger(), {**ANCHORS, "debt_millions": 9000.0})
    floor = [w for w in model["warnings"] if w.startswith("Valor parcial")]
    assert problems == [] and "porque la deuda pesa más que las partes valoradas" in floor[0]


def test_no_floor_warning_without_unvalued_business_parts():
    from app.services.expert_team.sotp_valuer import partial_value_warning

    assert partial_value_warning({"unvalued": []}) is None
    assert partial_value_warning({"unvalued": [{"name": "Clase B", "reason": "dilución: sin cita válida"}]}) is None
