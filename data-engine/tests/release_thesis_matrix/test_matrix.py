"""Matriz de release de tesis: 12 casos heterogéneos, herméticos.

Cada fixture es la entrada completa de un caso y su contrato esperado. La
matriz recorre la frontera que antes permitía publicar tesis con números
incomparables: motor de valoración -> contrato API -> memo canónico que luego
maqueta el PDF. No hay red, LLM, reloj de mercado ni datos no sembrados.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, FinancialFact, FundamentalModelVersion, FXRate, MarketPrice, ThesisVersion
from app.schemas.api import ValuationResponse
from app.services import valuation_service
from app.services.thesis_memo import build_memo_markdown
from app.services.thesis_publication_gate import model_withheld_reason
from app.services.valuation_service import ValuationService
from app.valuation.engines.base import (
    ValuationContext,
    ValuationEngine,
    adr_comparable_price,
    insufficient_result,
    margin_of_safety,
)

FIXTURES = Path(__file__).parent / "fixtures"
CASE_FILES = sorted(FIXTURES.glob("*.json"))
CASES = [json.loads(path.read_text(encoding="utf-8")) for path in CASE_FILES]
CASE_BY_ID = {case["id"]: case for case in CASES}
PRICE_DAY = date(2026, 10, 23)
STAMP = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


class MatrixFcfMultipleEngine(ValuationEngine):
    """Motor cerrado de la matriz: 15 × FCF / acciones.

    El objetivo no es rehacer el DCF (cubierto por sus suites), sino hacer
    auditable la cadena release: hechos -> divisa/unidad/ADR -> contrato ->
    memo/PDF. Las cuentas se pueden comprobar a mano desde cada fixture.
    """

    key = "release_matrix_fcf_multiple"

    def value(self, context: ValuationContext) -> dict:
        snapshot = context.snapshot
        missing = [
            metric
            for metric in ("revenue", "free_cash_flow", "shares_diluted")
            if snapshot.value(metric) is None
        ]
        if missing:
            return insufficient_result(
                ticker=context.company.ticker,
                model_type=context.company.valuation_model,
                engine_key=self.key,
                current_price=context.current_price,
                missing_inputs=missing,
                reason="Faltan hechos canónicos sembrados por el fixture; no se supone ninguno.",
                snapshot=snapshot,
            )

        fcf_raw = snapshot.value("free_cash_flow")
        shares_raw = snapshot.value("shares_diluted")
        assert fcf_raw is not None
        assert shares_raw is not None
        fcf = float(fcf_raw)
        shares = float(shares_raw)
        base = 15.0 * fcf / shares
        comparable, ratio = adr_comparable_price(context.company, context.current_price)
        listed = (
            {
                "bear": base * 0.8 * ratio,
                "base": base * ratio,
                "bull": base * 1.2 * ratio,
                "expected": base * ratio,
            }
            if ratio
            else None
        )
        return {
            "ticker": context.company.ticker,
            "model_type": context.company.valuation_model,
            "status": "ok",
            "publishable": True,
            "current_price": context.current_price,
            "bear_value": base * 0.8,
            "base_value": base,
            "bull_value": base * 1.2,
            "expected_value": base,
            "margin_of_safety": margin_of_safety(base, comparable),
            "missing_inputs": [],
            "publication_blockers": [],
            "adr_ratio": ratio,
            "value_per_share_basis": "ordinary_share",
            "comparable_price_basis": "listed_share" if ratio else "ordinary_share",
            "listed_share_values": listed,
            "reverse_dcf": {},
            "sensitivity": {
                "rows": [
                    {"scenario": "low", "value_per_share": base * 0.8},
                    {"scenario": "base", "value_per_share": base},
                    {"scenario": "high", "value_per_share": base * 1.2},
                ]
            },
            "moat": {},
            "trace": {
                "engine": self.key,
                "probabilities": {"bear": 0.2, "base": 0.6, "bull": 0.2},
                "closed_form": "15 * free_cash_flow / shares_diluted",
            },
        }


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(valuation_service, "resolve", lambda _company: MatrixFcfMultipleEngine())
    with Session(engine) as session:
        yield session
    engine.dispose()


def _date(raw: str) -> date:
    return date.fromisoformat(raw)


def _seed_company(db: Session, case: dict) -> Company:
    raw = case["company"]
    company = Company(
        ticker=raw["ticker"],
        name=raw["name"],
        exchange=raw.get("exchange"),
        currency=raw.get("currency"),
        sector=raw.get("sector"),
        industry=raw.get("industry"),
        company_type=raw.get("company_type", "standard"),
        valuation_model="release_matrix_fcf_multiple",
        special_sources=[],
        special_risks=[],
        factor_tags=raw.get("factor_tags", []),
    )
    db.add(company)
    db.flush()
    return company


def _seed_valuation_case(db: Session, case: dict) -> Company:
    company = _seed_company(db, case)
    for fact in case.get("facts", []):
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=fact["metric"],
                value=Decimal(fact["value"]),
                unit=fact.get("unit"),
                period=fact.get("period", "2025-12-31:FY"),
                fiscal_year=fact.get("fiscal_year", 2025),
                fiscal_quarter=fact.get("fiscal_quarter", "FY"),
                source_type=fact.get("source_type", "SEC"),
            )
        )
    price = case.get("price")
    if price:
        close = Decimal(price["close"])
        db.add(
            MarketPrice(
                company_id=company.id,
                date=_date(price.get("date", PRICE_DAY.isoformat())),
                open=close,
                high=close,
                low=close,
                close=close,
                source=price.get("source", "matrix"),
                quote_currency=price.get("quote_currency"),
            )
        )
    for rate in case.get("fx_rates", []):
        db.add(
            FXRate(
                base_currency=rate["base_currency"],
                quote_currency=rate["quote_currency"],
                rate=Decimal(rate["rate"]),
                rate_date=_date(rate["rate_date"]),
                source=rate.get("source", "ECB"),
            )
        )
    db.commit()
    return company


def _thesis_from_valuation(company: Company, valuation: dict) -> ThesisVersion:
    publishable = valuation.get("status") == "ok" and valuation.get("publishable") is True
    return ThesisVersion(
        company_id=company.id,
        version=1,
        status="published" if publishable else "insufficient_data",
        rating="watch" if publishable else "insufficient_data",
        thesis_markdown=f"# Tesis {company.ticker}",
        executive_summary="Caso de release sembrado." if publishable else "Datos insuficientes.",
        hypothesis="Caso de release sembrado." if publishable else None,
        current_price=valuation.get("current_price"),
        bear_value=valuation.get("bear_value"),
        base_value=valuation.get("base_value"),
        bull_value=valuation.get("bull_value"),
        expected_value=valuation.get("expected_value"),
        margin_of_safety=valuation.get("margin_of_safety"),
        scenario_probabilities={"bear": 0.2, "base": 0.6, "bull": 0.2} if publishable else None,
        data_confidence_score=100 if publishable else 0,
        source_coverage_score=100 if publishable else 0,
        red_team_score=100 if publishable else 0,
        valuation_risk_score=0 if publishable else 100,
        created_at=STAMP,
        updated_at=STAMP,
        input_fingerprint="matrix-fp" if publishable else None,
        valuation_basis={
            "margin_of_safety_convention": (valuation.get("trace") or {}).get("margin_of_safety_convention"),
            "price_as_of": (valuation.get("trace") or {}).get("price_as_of"),
            "value_per_share_basis": valuation.get("value_per_share_basis"),
            "adr_ratio": valuation.get("adr_ratio"),
            "listed_share_values": valuation.get("listed_share_values"),
        },
    )


def _assert_close(actual, expected: float, case_id: str, field: str) -> None:
    assert actual == pytest.approx(expected, rel=1e-6, abs=1e-9), f"{case_id}.{field}: {actual!r} != {expected!r}"


def _assert_memo_contract(db: Session, company: Company, valuation: dict, expected: dict) -> None:
    thesis = _thesis_from_valuation(company, valuation)
    db.add(thesis)
    if thesis.status == "published":
        db.add(
            FundamentalModelVersion(
                company_id=company.id,
                version=1,
                engine_version="matrix",
                algorithm_version="matrix",
                framework_key="release_matrix_fcf_multiple",
                horizon_years=10,
                status="ok",
                publishable=True,
                input_fingerprint="matrix-fp",
                forecast_fingerprint="matrix-forecast",
                market_snapshot_fingerprint="matrix-market",
                valuation_snapshot_fingerprint="matrix-valuation",
            )
        )
    db.commit()
    model = None
    if thesis.status == "published":
        model = db.scalar(select(FundamentalModelVersion).where(FundamentalModelVersion.company_id == company.id))
    assert model_withheld_reason(thesis, model) is None

    memo = build_memo_markdown(db, company, thesis)
    for fragment in expected.get("memo_contains", []):
        assert fragment in memo
    for fragment in expected.get("memo_forbidden", []):
        assert fragment not in memo


def test_release_thesis_matrix_corpus_is_complete_and_heterogeneous() -> None:
    """Una matriz incompleta no puede quedar verde por omisión."""
    assert len(CASE_FILES) == 12
    assert len(CASES) == 12
    assert len(CASE_BY_ID) == 12
    assert [case["id"] for case in CASES] == [path.stem for path in CASE_FILES]

    by_kind = {}
    facets = set()
    for case in CASES:
        by_kind[case["kind"]] = by_kind.get(case["kind"], 0) + 1
        facets.update(case["facets"])
    assert by_kind == {"valuation": 11, "pdf_source": 1}
    assert {
        "publicable_contract",
        "insufficient_data_contract",
        "adr",
        "unit",
        "fx",
        "no_fcf",
        "pdf_no_invented_values",
    } <= facets


@pytest.mark.parametrize("case", [case for case in CASES if case["kind"] == "valuation"], ids=lambda case: case["id"])
def test_release_thesis_matrix_valuation_contract(case: dict, db: Session) -> None:
    company = _seed_valuation_case(db, case)
    valuation = ValuationService().value_company(db, company)
    expected = case["expected"]

    assert valuation["status"] == expected["status"]
    assert valuation["publishable"] is expected["publishable"]
    assert valuation["missing_inputs"] == expected["missing_inputs"]
    assert valuation.get("value_currency") == expected.get("value_currency")
    assert (valuation.get("currency") or {}).get("status") == expected.get("currency_status")
    assert valuation.get("adr_ratio") == expected.get("adr_ratio")

    for field in ("current_price", "base_value", "expected_value", "margin_of_safety"):
        wanted = expected.get(field)
        if wanted is None:
            assert valuation.get(field) is None, f"{case['id']}.{field}"
        else:
            _assert_close(valuation.get(field), wanted, case["id"], field)

    listed = valuation.get("listed_share_values") or {}
    if expected.get("listed_base_value") is None:
        assert listed.get("base") is None
    else:
        _assert_close(listed.get("base"), expected["listed_base_value"], case["id"], "listed_share_values.base")

    assert valuation["trace"].get("price_status") == expected.get("price_status", "ok")
    if expected["status"] == "insufficient_data":
        for field in ("bear_value", "base_value", "bull_value", "expected_value", "margin_of_safety"):
            assert valuation.get(field) is None, f"{case['id']} retuvo {field}"
        assert valuation["publishable"] is False
    else:
        assert valuation["publishable"] is True
        assert valuation["missing_inputs"] == []

    api = ValuationResponse.model_validate(valuation)
    assert api.status == expected["status"]
    assert api.publishable is expected["publishable"]
    assert api.missing_inputs == expected["missing_inputs"]

    _assert_memo_contract(db, company, valuation, expected)


def test_release_thesis_matrix_pdf_source_never_invents_values(db: Session) -> None:
    case = CASE_BY_ID["pdf_sparse_draft_no_invented_values"]
    company = _seed_company(db, case)
    raw = case["thesis"]
    thesis = ThesisVersion(
        company_id=company.id,
        version=raw["version"],
        status=raw["status"],
        rating=raw["rating"],
        thesis_markdown=raw["thesis_markdown"],
        executive_summary=raw["executive_summary"],
        hypothesis=raw["hypothesis"],
        current_price=Decimal(raw["current_price"]),
        bear_value=Decimal(raw["bear_value"]),
        base_value=Decimal(raw["base_value"]),
        bull_value=Decimal(raw["bull_value"]),
        expected_value=Decimal(raw["expected_value"]),
        margin_of_safety=Decimal(raw["margin_of_safety"]),
        scenario_probabilities=raw["scenario_probabilities"],
        data_confidence_score=0,
        source_coverage_score=0,
        red_team_score=0,
        valuation_risk_score=0,
        created_at=STAMP,
        updated_at=STAMP,
    )
    db.add(thesis)
    db.commit()

    memo = build_memo_markdown(db, company, thesis, draft=True)
    normalized = re.sub(
        r"Generado \d{1,2} [a-z]{3,4} \d{4}, \d{2}:\d{2} UTC",
        "Generado <generated> UTC",
        memo,
    )
    expected_markdown = (FIXTURES / case["expected_markdown"]).read_text(encoding="utf-8")
    assert normalized == expected_markdown

    for fragment in case["expected"]["memo_contains"]:
        assert fragment in memo
    for fragment in case["expected"]["memo_forbidden"]:
        assert fragment not in memo
    assert model_withheld_reason(thesis, None) is None
