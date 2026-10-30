"""Pre-revenue con ADR: el filing da acciones ORDINARIAS y el precio es del ADR.

Antes el margen de seguridad y el DCF inverso usaban el precio del ADR contra
un valor por ordinaria (error xN) y un ADR sin ratio se valoraba igual. Ahora,
como standard_dcf: precio por ordinaria = precio ADR / N.
"""

from __future__ import annotations

import pytest

from app.valuation.engines.base import ValuationContext
from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from tests.test_pre_revenue_net_debt_and_wacc_honesty import (  # noqa: F401 - fixtures
    _add_wacc_metric,
    _coherent_facts,
    _indicative_facts,
    company,
    db,
)


def _run(db, company, price):
    return PreRevenueScenarioEngine().value(
        ValuationContext(
            db=db,
            company=company,
            snapshot=FinancialSnapshotBuilder().build(db, company),
            current_price=price,
            engine_key="pre_revenue",
        )
    )


def test_adr_margin_and_reverse_dcf_use_price_per_ordinary_share(db, company):  # noqa: F811
    _coherent_facts(db, company)
    _add_wacc_metric(db, company, 0.11)
    plain = _run(db, company, 2.5)
    company.factor_tags = ["pre_fcf", "speculative", "adr:4"]
    db.commit()
    adr = _run(db, company, 10.0)  # 1 ADR = 4 ordinarias -> 2,5 por ordinaria
    assert adr["expected_value"] == pytest.approx(plain["expected_value"])
    expected = adr["expected_value"]
    # (V - P/N) / V con P/N = 10 / 4 = 2,5; antes (V - 10) / V.
    assert adr["margin_of_safety"] == pytest.approx((expected - 2.5) / expected)
    assert adr["margin_of_safety"] == pytest.approx(plain["margin_of_safety"])
    assert adr["current_price"] == 10.0
    assert adr["adr_ratio"] == 4
    assert adr["listed_share_values"]["expected"] == pytest.approx(expected * 4)
    assert adr["listed_share_values"]["bear"] == pytest.approx(adr["bear_value"] * 4)
    assert adr["reverse_dcf"] == plain["reverse_dcf"]
    assert "listed_share_values" not in plain or plain.get("listed_share_values") is None


def test_adr_without_ratio_is_refused(db, company):  # noqa: F811
    _coherent_facts(db, company)
    company.factor_tags = ["pre_fcf", "speculative", "adr"]
    db.commit()
    result = _run(db, company, 10.0)
    assert result["status"] != "ok"
    assert result["missing_inputs"] == ["adr_ratio"]


def test_indicative_range_also_uses_ordinary_price(db, company):  # noqa: F811
    _indicative_facts(db, company, net_debt=-150_000_000.0)
    plain = _run(db, company, 2.5)
    company.factor_tags = ["pre_fcf", "speculative", "adr:4"]
    db.commit()
    adr = _run(db, company, 10.0)
    assert adr["current_price"] == 10.0
    assert adr.get("margin_of_safety") == plain.get("margin_of_safety")
    assert adr.get("expected_value") == plain.get("expected_value")
