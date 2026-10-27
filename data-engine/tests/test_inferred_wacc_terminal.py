# pyright: reportArgumentType=false, reportOptionalOperand=false, reportOperatorIssue=false
"""PR-A/PR-B: wacc y terminal_growth INFERIDOS (base + URLs https) con
procedencia; sin base/URL o fuera de rango siguen fail-closed."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company
from app.services.inferred_input_service import (
    InferredInputError,
    InferredInputService,
    validate,
)
from app.services.thesis_provenance import (
    build_inputs_provenance,
    classify_origin,
)
from app.valuation.engines.base import resolve_rates

BASE = "Dado rf 5,11% (FRED), ERP 4,33% y beta 2,726 (yfinance), inferimos un coste de capital por CAPM"
URLS = ["https://fred.stlouisfed.org/series/DGS10"]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _company(db):
    c = Company(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", company_type="growth", valuation_model="pre_revenue", factor_tags=["pre_fcf"])
    db.add(c)
    db.commit()
    return c


def test_ranges_and_fail_closed():
    assert validate("wacc", 0.17, BASE, URLS) == []
    assert validate("terminal_growth", 0.025, BASE, URLS) == []
    assert "valor fuera de rango" in validate("wacc", 0.80, BASE, URLS)
    assert "valor fuera de rango" in validate("terminal_growth", 0.09, BASE, URLS)
    assert validate("wacc", 0.17, "corta", URLS)
    assert validate("wacc", 0.17, BASE, [])


def test_create_rejects_without_base(db):
    c = _company(db)
    with pytest.raises(InferredInputError):
        InferredInputService().create(
            db, c, input_key="wacc", value=Decimal("0.17"), base="x", source_urls=URLS
        )


def test_engine_uses_inferred_wacc_and_terminal(db):
    c = _company(db)
    assert resolve_rates(db, c)[:4] == (0.13, "tag_default", 0.025, "tag_default")
    svc = InferredInputService()
    svc.create(db, c, input_key="wacc", value=Decimal("0.17"), base=BASE, source_urls=URLS)
    svc.create(db, c, input_key="terminal_growth", value=Decimal("0.02"), base=BASE, source_urls=URLS)
    assert resolve_rates(db, c)[:4] == (0.17, "inferred_input", 0.02, "inferred_input")


def test_provenance_carries_urls_as_inferido():
    model = {
        "assumptions": {
            "wacc": {
                "value": 0.17,
                "unit": "decimal",
                "source_type": "inferred_input",
                "basis": BASE,
                "source_fact_ids": [],
                "confidence": 0.5,
                "source_urls": URLS,
            }
        }
    }
    items = classify_origin(build_inputs_provenance(model), {})
    assert items[0]["origen"] == "INFERIDO"
    assert items[0]["urls_inferencia"] == URLS
    assert items[0]["base_documentada"] is True


def test_pick_rate_pair_drops_inferred_without_spread():
    from app.services.inferred_input_service import pick_rate_pair

    w, g, dropped = pick_rate_pair(
        wacc=0.045, wacc_inferred=True, terminal=0.05, terminal_inferred=True,
        default_wacc_value=0.13, default_terminal_value=0.025,
    )
    assert dropped == ["terminal_growth"]
    assert w - g >= 0.02 - 1e-9


def test_resolve_rates_ignores_bad_inferred_pair(db):
    c = _company(db)
    svc = InferredInputService()
    svc.create(db, c, input_key="wacc", value=Decimal("0.045"), base=BASE, source_urls=URLS)
    svc.create(db, c, input_key="terminal_growth", value=Decimal("0.05"), base=BASE, source_urls=URLS)
    wacc, wsrc, g, gsrc, dropped = resolve_rates(db, c)
    assert wacc - g >= 0.02 - 1e-9
    assert dropped
    assert "terminal_growth" in dropped
    assert gsrc == "tag_default"


class _Snap:
    # FinancialSnapshot.excluded_present (928a2cec): los motores lo leen siempre.
    excluded_present: list = []
    coherent = False
    as_of_period = None
    income_statement = None
    balance_sheet = None
    shares_period = None
    warnings: list = []
    facts: dict = {}
    missing_inputs = ["revenue_history_two_periods"]

    def __init__(self, values):
        self._v = values

    def value(self, metric):
        return self._v.get(metric)

    def fact_ids(self):
        return {}

    def periods(self):
        return {}


def test_pre_revenue_engine_does_not_break_on_bad_pair(db):
    from app.valuation.engines.base import ValuationContext
    from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine

    c = _company(db)
    svc = InferredInputService()
    svc.create(db, c, input_key="fcf_margin", value=Decimal("-0.3"), base=BASE, source_urls=URLS)
    svc.create(db, c, input_key="wacc", value=Decimal("0.045"), base=BASE, source_urls=URLS)
    svc.create(db, c, input_key="terminal_growth", value=Decimal("0.05"), base=BASE, source_urls=URLS)
    snap = _Snap({"revenue": 70_918_000.0, "shares_diluted": 255_982_592.0,
                  "operating_cash_flow": -71_517_000.0})
    ctx = ValuationContext(db=db, company=c, snapshot=snap, current_price=58.86,
                           engine_key="pre_revenue")
    result = PreRevenueScenarioEngine().value(ctx)
    assert result["status"] != "error"
    assert "terminal_growth" in result["inputs"]["inferred_inputs_ignored"] if "inputs" in result else True


def test_long_term_assumptions_inferred_and_bad_pair(db):
    from app.services.long_term_model_service import LongTermModelService

    c = _company(db)
    svc = InferredInputService()
    svc.create(db, c, input_key="wacc", value=Decimal("0.17"), base=BASE, source_urls=URLS)
    svc.create(db, c, input_key="terminal_growth", value=Decimal("0.02"), base=BASE, source_urls=URLS)
    kw = dict(db=db, fact_cache={}, revenue_history={}, years=[], company=c)
    a, meta = LongTermModelService()._assumptions(**kw)
    assert a["wacc"].source_type == "inferred_input"
    assert a["wacc"].as_dict()["source_urls"] == URLS
    assert a["terminal_growth"].source_type == "inferred_input"
    assert meta["wacc_trace"]["status"] == "inferred_input"

    svc.create(db, c, input_key="wacc", value=Decimal("0.045"), base=BASE, source_urls=URLS)
    svc.create(db, c, input_key="terminal_growth", value=Decimal("0.05"), base=BASE, source_urls=URLS)
    a, meta = LongTermModelService()._assumptions(**kw)
    assert a["wacc"].value - a["terminal_growth"].value >= 0.02 - 1e-9
    assert "terminal_growth" in meta["wacc_trace"]["inferred_inputs_ignored"]
