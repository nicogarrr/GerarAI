"""Relajacion acotada de #691: escenarios solo con un margen FCF INFERIDO que
lleve base explicita + URL https; sin base valida sigue fail-closed."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, InferredInput
from app.services.inferred_input_service import (
    InferredInputError,
    InferredInputService,
    validate,
)
from app.services.thesis_service import latest_inputs_provenance
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine

BASE = "Dado el guidance de despliegue y los contratos firmados, inferimos margen FCF negativo"
URLS = ["https://www.sec.gov/Archives/edgar/data/1780312/x.htm"]


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


BURN = {"revenue": 70_918_000.0, "shares_diluted": 255_982_592.0, "operating_cash_flow": -71_517_000.0}


def _company(db):
    company = Company(
        ticker="BRN", name="Burn", exchange="NASDAQ", company_type="growth",
        valuation_model="pre_revenue", factor_tags=["pre_fcf"],
    )
    db.add(company)
    db.commit()
    return company


def _value(db, company, values=None):
    ctx = ValuationContext(
        db=db, company=company, snapshot=_Snap(values or BURN),
        current_price=58.86, engine_key="pre_revenue",
    )
    return PreRevenueScenarioEngine().value(ctx)


def test_validation_requires_base_urls_and_range():
    assert validate("fcf_margin", 0.1, BASE, URLS) == []
    assert validate("fcf_margin", 0.1, "corta", URLS)
    assert validate("fcf_margin", 0.1, BASE, [])
    assert validate("fcf_margin", 0.1, BASE, ["http://insecure.example.com/a"])
    assert validate("fcf_margin", 5, BASE, URLS)
    assert validate("fcf_margin", -1.0, BASE, URLS)
    assert validate("otra_clave", 0.1, BASE, URLS)


def test_service_rejects_invalid_and_stores_valid(db):
    company = _company(db)
    with pytest.raises(InferredInputError):
        InferredInputService().create(
            db, company, input_key="fcf_margin", value=Decimal("0.1"), base="x", source_urls=URLS
        )
    row = InferredInputService().create(
        db, company, input_key="fcf_margin", value=Decimal("-0.3"), base=BASE, source_urls=URLS
    )
    assert InferredInputService().latest_valid(db, company.id, "fcf_margin").id == row.id


def test_without_inferred_input_still_fail_closed(db):
    result = _value(db, _company(db))
    assert result["status"] == "insufficient_data"
    assert result["base_value"] is None


def test_invalid_stored_inferred_input_is_ignored(db):
    company = _company(db)
    db.add(InferredInput(company_id=company.id, input_key="fcf_margin",
                         value=Decimal("0.1"), base="", source_urls=[], origin="llm"))
    db.commit()
    result = _value(db, company)
    assert result["status"] == "insufficient_data"
    assert result["base_value"] is None


def test_valid_inferred_input_allows_marked_non_publishable_scenarios(db):
    company = _company(db)
    InferredInputService().create(
        db, company, input_key="fcf_margin", value=Decimal("0.05"), base=BASE, source_urls=URLS
    )
    result = _value(db, company)
    assert result["status"] == "partial"
    assert result["publishable"] is False
    assert result["base_value"] is not None
    trace = result["trace"]
    assert trace["valuation_basis"] == "inferred_inputs"
    mark = trace["inferred_inputs"][0]
    assert mark["origen"] == "INFERIDO"
    assert mark["base_inferencia"] == BASE and mark["urls_inferencia"] == URLS
    assert mark["observed_cash_burn"] == {"operating_cash_flow": -71_517_000.0}
    assert trace["assumed"]["fcf_margin_base"] == pytest.approx(0.05)


def test_positive_cash_path_unchanged_without_inferred(db):
    company = _company(db)
    result = _value(db, company, {**BURN, "operating_cash_flow": 5_000_000.0})
    assert result["trace"]["valuation_basis"] == "indicative_assumptions"
    assert result["trace"]["inferred_inputs"] == []


@pytest.mark.parametrize(
    "url",
    [
        "https://user.name@localhost/x",
        "https://user:pass@example.com/a",
        "https://.",
        "https://example.com:bad/x",
        "https://example.com:99999/x",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://intranet/x",
        "http://example.com/x",
        "https://exa mple.com/x",
        " https://example.com/x",
        "https://-bad.example.com/x",
    ],
)
def test_malformed_or_credentialed_urls_are_rejected(db, url):
    assert validate("fcf_margin", 0.1, BASE, [url])
    assert validate("fcf_margin", 0.1, BASE, URLS + [url])
    with pytest.raises(InferredInputError):
        InferredInputService().create(
            db, _company(db), input_key="fcf_margin", value=Decimal("0.1"),
            base=BASE, source_urls=[url],
        )


def test_positive_cash_ignores_existing_inferred_input(db):
    company = _company(db)
    InferredInputService().create(
        db, company, input_key="fcf_margin", value=Decimal("0.05"), base=BASE, source_urls=URLS
    )
    result = _value(db, company, {**BURN, "operating_cash_flow": 5_000_000.0})
    assert result["trace"]["valuation_basis"] == "indicative_assumptions"
    assert result["trace"]["inferred_inputs"] == []
    assert result["trace"]["assumed"]["fcf_margin_base"] == pytest.approx(0.15)


def test_provenance_binds_to_used_input_and_keeps_history(db):
    from app.models.entities import FundamentalModelVersion
    from app.services.thesis_service import ThesisService

    company = _company(db)
    snapshot = {
        "assumptions": {
            "fcf_margin": {
                "value": 0.20, "source_type": "financial_facts",
                "basis": "mediana historica", "source_fact_ids": [], "confidence": 0.5,
            }
        }
    }
    db.add(FundamentalModelVersion(
        company_id=company.id, version=1, engine_version="e1", algorithm_version="a1",
        framework_key="space_network", horizon_years=5, status="ok", publishable=True,
        input_fingerprint="a" * 64, forecast_fingerprint="a" * 64,
        market_snapshot_fingerprint="a" * 64, valuation_snapshot_fingerprint="a" * 64,
        model_snapshot=snapshot,
    ))
    used = InferredInputService().create(
        db, company, input_key="fcf_margin", value=Decimal("0.05"), base=BASE, source_urls=URLS
    )
    basis = ThesisService._valuation_basis(_value(db, company))
    # Un input posterior NO cambia lo que consumio esta tesis.
    InferredInputService().create(
        db, company, input_key="fcf_margin", value=Decimal("0.30"),
        base=BASE + " (otra)", source_urls=URLS,
    )
    provenance = latest_inputs_provenance(db, company.id, basis)
    assert provenance is not None
    items = {i["key"]: i for i in provenance}
    # La mediana historica no trae base documentada con URL: se omite (N/D).
    assert "fcf_margin" not in items
    usado = items["fcf_margin_usado_en_valoracion"]
    assert usado["value"] == pytest.approx(0.05)
    assert usado["inferred_input_id"] == used.id
    assert usado["urls_inferencia"] == URLS and usado["base_inferencia"] == BASE
    # Sin valuation_basis (tesis anterior) no se inventa ningun input usado.
    legacy = {i["key"] for i in (latest_inputs_provenance(db, company.id, None) or [])}
    assert "fcf_margin_usado_en_valoracion" not in legacy


@pytest.mark.parametrize("margin", ["-0.9", "-0.3", "-0.01", "0", "0.05", "0.35", "0.5", "0.6"])
def test_scenarios_are_ordered_by_construction_across_allowed_range(db, margin):
    company = _company(db)
    InferredInputService().create(
        db, company, input_key="fcf_margin", value=Decimal(margin), base=BASE, source_urls=URLS
    )
    result = _value(db, company)
    if Decimal(margin) <= 0:
        assert result["status"] == "insufficient_data"
        assert result["base_value"] is None
        return
    assert result["status"] == "partial" and result["publishable"] is False
    assert result["bear_value"] < result["base_value"] < result["bull_value"], margin
    band = result["trace"]["assumed"]["fcf_margin_band"]
    assert band[0] < band[1] <= band[2]


def test_used_inputs_are_shown_even_without_fundamental_model(db):
    company = _company(db)
    InferredInputService().create(
        db, company, input_key="fcf_margin", value=Decimal("0.05"), base=BASE, source_urls=URLS
    )
    from app.services.thesis_service import ThesisService

    basis = ThesisService._valuation_basis(_value(db, company))
    items = latest_inputs_provenance(db, company.id, basis)
    assert items is not None
    assert [i["key"] for i in items] == ["fcf_margin_usado_en_valoracion"]
    assert items[0]["origen"] == "INFERIDO"
    assert latest_inputs_provenance(db, company.id, None) is None


@pytest.mark.parametrize("fcf", [-80_000_000.0, 0.0])
def test_relaxation_only_fills_absent_fcf_not_reported_fcf(db, fcf):
    company = _company(db)
    InferredInputService().create(
        db, company, input_key="fcf_margin", value=Decimal("0.25"), base=BASE, source_urls=URLS
    )
    result = _value(db, company, {**BURN, "free_cash_flow": fcf})
    assert result["status"] == "insufficient_data"
    assert result["base_value"] is None
    assert result.get("trace", {}).get("inferred_inputs", []) == []
