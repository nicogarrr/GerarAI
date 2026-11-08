"""Desglose por partes (SOTP) editable: aritmética pura, almacén sin migración y honestidad.

El ejemplo es la tabla que Nico mandó para ASTS (8-nov-2026); la aritmética es
general (cualquier empresa, cualquier número de partes).
"""

from __future__ import annotations

import math

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.sotp import get_user_sotp, put_user_sotp
from app.data.sotp_examples import ASTS_NICO_2026_11_08
from app.models.entities import Base, Company, FinancialFact, Tenant
from app.schemas.sotp import SotpModelIn
from app.services.user_sotp_service import SOTP_INPUT_KEY, USER_ASSUMPTIONS_LABEL, UserSotpService
from app.valuation.consensus_context import analyst_inputs_for_dcf
from app.valuation.sotp import normalize_user_sotp, run_sotp, run_user_sotp

T1, T2 = 1, 2


def _model(raw=ASTS_NICO_2026_11_08):
    model, problems = normalize_user_sotp(raw)
    assert problems == []
    return model


# ----------------------------------------------------------------- aritmética


def test_asts_example_reproduces_the_table_row_by_row():
    result = run_user_sotp(_model(), price=32.33)
    per_share = [round(r["value_per_share"], 2) for r in result["rows"]]
    # Columna «Precio justo HOY ($/acción)» del mensaje (Latam 9,56 y caja 1,51 en
    # el mensaje: redondeo suyo, 9,566 y 1,516).
    assert per_share == [30.00, 21.11, 12.97, 9.47, 9.57, 41.48, 11.11, 13.69, 4.91, 1.52]
    assert [round(r["value_at_maturity"]) for r in result["rows"]] == [
        21384, 15045, 9248, 6750, 6818, 29568, 7920, 9756, 3500, 1080]
    assert result["total_value_at_maturity"] == pytest.approx(111069)
    assert result["discount_factor"] == pytest.approx(1.6018, abs=1e-4)
    assert result["total_present_value"] == pytest.approx(69337, abs=5)
    assert result["shares_diluted"] == pytest.approx(445.0)
    assert result["value_per_share"] == pytest.approx(155.81, abs=0.02)
    assert result["stated_gap"] == pytest.approx(0.0, abs=1e-3)
    assert result["vs_price"] == pytest.approx(155.82 / 32.33 - 1, abs=1e-3)


def test_normalized_model_is_stable_on_reload():
    # Blacklift: EBITDA equivalente (542) mayor que los ingresos (250); releerlo no lo rechaza.
    model = _model()
    assert normalize_user_sotp(model) == (model, [])


def test_scenarios_compute_from_their_parameters_and_show_the_stated_figure_beside():
    scenarios = {s["key"]: s for s in run_user_sotp(_model(), price=32.33)["scenarios"]}
    # Tasa del 15 %: 111.069 / 1,15^4 / 445 = 142,71 (el mensaje dice 142,50).
    assert scenarios["rate_15"]["value_per_share"] == pytest.approx(111069 / 1.15**4 / 445, rel=1e-6)
    assert scenarios["rate_15"]["stated_value_per_share"] == 142.50
    # Pesimista con sus propios supuestos (ingresos ×0,35, 18 meses, 480 M acciones):
    # operativo / 1,125^5,5 + balance / 1,125^4, ÷ 480 → 46,58, no 61,40.
    operating = 111069 - 3500 - 1080
    expected = (operating * 0.35 / 1.125**5.5 + 4580 / 1.125**4) / 480
    assert scenarios["pessimistic"]["value_per_share"] == pytest.approx(expected, rel=1e-6)
    assert scenarios["pessimistic"]["stated_gap"] == pytest.approx(61.40 / expected - 1, rel=1e-6)
    # Sin parámetros: cifra declarada, no calculada.
    assert scenarios["optimistic"]["computed"] is False
    assert scenarios["optimistic"]["value_per_share"] is None
    assert scenarios["optimistic"]["stated_vs_price"] == pytest.approx(341.5 / 32.33 - 1)


def test_sensitivity_moves_only_the_operating_parts():
    model = _model()
    base = run_user_sotp(model)
    sens = {s["key"]: s for s in base["sensitivity"]}
    op_pv = sum(r["present_value"] for r in base["rows"] if r["kind"] == "operating")
    asset_pv = base["total_present_value"] - op_pv
    assert sens["multiples_minus_30"]["value_per_share"] == pytest.approx((op_pv * 0.7 + asset_pv) / 445)
    assert sens["delay_2y"]["value_per_share"] == pytest.approx((op_pv / 1.125**2 + asset_pv) / 445)
    assert sens["revenue_minus_50"]["value_per_share"] == pytest.approx((op_pv * 0.5 + asset_pv) / 445)
    assert sens["combined"]["value_per_share"] < sens["multiples_minus_30"]["value_per_share"]
    assert all(s["vs_base"] < 0 for s in base["sensitivity"])


def test_general_model_margin_probability_and_undiscounted_asset():
    raw = {
        "base_year": 2026, "valuation_year": 2029, "discount_rate": 0.10, "shares_current": 100,
        "dilution": [{"label": "opciones", "shares": 25}],
        "parts": [
            {"name": "Software", "revenue": 500, "ebitda_margin": 0.4, "multiple": 20},
            {"name": "Apuesta", "revenue": 100, "ebitda": 50, "multiple": 10, "probability": 0.25},
            {"name": "Caja hoy", "kind": "asset", "value": 300, "discounted": False},
            {"name": "Deuda", "kind": "asset", "value": -200, "discounted": False},
        ],
    }
    model = _model(raw)
    assert model["discount_years"] == 3
    result = run_user_sotp(model)
    expected = (500 * 0.4 * 20 / 1.1**3 + 50 * 10 * 0.25 / 1.1**3 + 300 - 200) / 125
    assert result["value_per_share"] == pytest.approx(expected)
    assert result["rows"][0]["ebitda"] == pytest.approx(200)
    assert result["rows"][0]["ebitda_margin"] == pytest.approx(0.4)
    # Guardado y releído da lo mismo (el modelo normalizado es estable).
    assert normalize_user_sotp(model) == (model, [])
    assert result["weighted_multiple"] == pytest.approx((4000 + 125) / (200 + 12.5))
    assert math.isfinite(result["value_per_share"])


@pytest.mark.parametrize(
    ("patch", "needle"),
    [
        ({"discount_rate": None}, "falta tasa de descuento"),
        ({"shares_current": 0}, "acciones actuales"),
        ({"parts": []}, "al menos una parte"),
        ({"parts": [{"name": "X", "revenue": 10, "multiple": 5}]}, "falta el EBITDA o el margen"),
        ({"parts": [{"name": "X", "ebitda": 10, "multiple": -1}]}, "múltiplo"),
        ({"parts": [{"name": "X", "ebitda": 10, "multiple": 5, "probability": 2}]}, "probabilidad"),
        ({"valuation_year": 2020}, "anterior al de hoy"),
        ({"discount_rate": "abc"}, "no es un número"),
    ],
)
def test_validation_names_the_problem(patch, needle):
    raw = {**ASTS_NICO_2026_11_08, "discount_years": None, **patch}
    _model_out, problems = normalize_user_sotp(raw)
    assert any(needle in p for p in problems), problems


def test_existing_engine_core_is_unchanged():
    out = run_sotp([{"name": "a", "metric": 10, "multiple": 5}], net_debt=10, shares_outstanding=4)
    assert out["value_per_share"] == 10.0
    assert out["trace"] == {"method": "sum_of_the_parts"}


# ----------------------------------------------------------------- almacén


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=T1, external_id="t1"), Tenant(id=T2, external_id="t2")])
        session.flush()
        session.info["tenant_id"] = T1
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
                      sector="Telecom", industry="Telecom Services", company_type="operating", valuation_model="standard_dcf")
    db.add(company)
    db.flush()
    return company


def _facts(db: Session, company: Company, net_income: float, ocf: float, year: int = 2025) -> None:
    for metric, value in (("net_income", net_income), ("operating_cash_flow", ocf)):
        db.add(FinancialFact(company_id=company.id, metric=metric, value=value, fiscal_year=year,
                             period=f"FY{year}", unit="USD"))
    db.flush()


def test_example_draft_until_the_user_saves_then_versions_and_delete(db):
    asts = _company(db, "ASTS")
    service = UserSotpService()
    first = service.read(db, asts, T1)
    assert first["origin"] == "example"
    assert first["label"] == USER_ASSUMPTIONS_LABEL and first["validated"] is False
    assert first["result"]["value_per_share"] == pytest.approx(155.82, abs=0.01)

    mine = {**ASTS_NICO_2026_11_08, "discount_rate": 0.15, "scenarios": []}
    saved = service.save(db, asts, T1, mine)
    assert saved["origin"] == "saved"
    assert saved["saved"]["versions"] == 1
    assert saved["result"]["value_per_share"] == pytest.approx(111069 / 1.15**4 / 445, rel=1e-6)
    again = service.save(db, asts, T1, {**mine, "discount_rate": 0.2})
    assert again["saved"]["versions"] == 2

    # Otro tenant no ve el modelo guardado: sigue viendo el borrador.
    db.info["tenant_id"] = T2
    assert service.read(db, asts, T2)["origin"] == "example"
    db.info["tenant_id"] = T1
    assert service.delete(db, asts, T1) is True
    assert service.read(db, asts, T1)["origin"] == "example"


def test_any_company_without_example_starts_empty_and_can_save(db):
    other = _company(db, "SYNTH")
    service = UserSotpService()
    assert service.read(db, other, T1)["available"] is False
    out = service.save(db, other, T1, {"base_year": 2026, "valuation_year": 2028, "discount_rate": 0.1,
                                       "shares_current": 10, "parts": [{"name": "A", "ebitda": 10, "multiple": 10}]})
    assert out["result"]["value_per_share"] == pytest.approx(100 / 1.1**2 / 10)
    # Sin divisa en el modelo se usa la de la empresa, nunca un USD inventado.
    assert out["model"]["currency"] == "USD" == other.currency
    with pytest.raises(ValueError, match="al menos una parte"):
        service.save(db, other, T1, {"base_year": 2026, "valuation_year": 2028, "discount_rate": 0.1,
                                     "shares_current": 10, "parts": []})


def test_base_rate_always_beside_and_applies_only_to_cash_burners(db):
    burner = _company(db, "BURN")
    _facts(db, burner, net_income=-300, ocf=-150)
    profitable = _company(db, "PROF")
    _facts(db, profitable, net_income=300, ocf=450)
    service = UserSotpService()
    burn = service.read(db, burner, T1)["base_rate"]
    assert burn["applies"] is True
    assert burn["median_return_24m"] < -0.4
    assert "quema caja" in burn["message_es"]
    assert service.read(db, profitable, T1)["base_rate"]["applies"] is False
    assert service.read(db, _company(db, "NODATA"), T1)["base_rate"]["applies"] is None


def test_saved_model_never_feeds_the_valuation_engines(db):
    asts = _company(db, "ASTS")
    UserSotpService().save(db, asts, T1, ASTS_NICO_2026_11_08)
    assert analyst_inputs_for_dcf(db, asts).rows == []
    from app.models.declared_input_value import DeclaredInputValue

    row = db.query(DeclaredInputValue).filter_by(input_key=SOTP_INPUT_KEY).one()
    assert row.method == "manual" and row.status == "manual"


def test_routes_need_user_context_and_reject_bad_models(db):
    _company(db, "ASTS")
    assert get_user_sotp("asts", db)["origin"] == "example"
    saved = put_user_sotp("ASTS", SotpModelIn(**ASTS_NICO_2026_11_08), db)
    assert saved["origin"] == "saved"
    assert saved["result"]["value_per_share"] == pytest.approx(155.82, abs=0.01)
    with pytest.raises(HTTPException) as bad:
        put_user_sotp("ASTS", SotpModelIn(parts=[]), db)
    assert bad.value.status_code == 422
    db.info.pop("tenant_id")
    with pytest.raises(HTTPException) as no_user:
        get_user_sotp("ASTS", db)
    assert no_user.value.status_code == 403
