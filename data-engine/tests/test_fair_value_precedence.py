"""Precedencia tesis/motor: frescura de inputs y version del motor.

Una tesis publicada de menos de 180 dias ganaba SIEMPRE al motor, aunque
hubiera datos mas recientes que ella o el motor hubiera cambiado de version.
Ahora gana solo si sus inputs siguen vigentes y salio del motor actual; si
pierde, la ficha dice por que (reason/thesis_displaced) y, cuando no hay
motor publicable, la cifra revisada se sigue sirviendo marcada: nunca se
oculta el numero.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import i18n
from app.models.entities import (
    Base,
    Company,
    FinancialFact,
    ThesisVersion,
    ValuationModel,
    ValuationOutput,
)
from app.services import fair_value_service as fvs
from app.services.fair_value_service import Candidate, choose
from app.valuation.engines.base import MODEL_VERSION

TODAY = date(2026, 11, 4)
THESIS_STAMP = datetime(2026, 11, 1, 12, 0)


# ---------------------------------------------------------------- choose()


def test_fresh_thesis_with_newer_inputs_loses_to_publishable_engine():
    thesis = Candidate(
        value=150.0, as_of=TODAY - timedelta(days=3), thesis_version=3, inputs_fresh=False
    )
    engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
    out = choose(thesis, engine, today=TODAY)
    assert (out["value"], out["source"], out["rule"]) == (90.0, "motor", "motor_publicable")
    assert out["thesis_displaced"] == {"version": 3, "cause": "inputs_nuevos"}
    assert "datos más recientes" in out["reason"]


def test_fresh_thesis_from_previous_model_loses_to_publishable_engine():
    thesis = Candidate(
        value=150.0, as_of=TODAY - timedelta(days=3), thesis_version=2, model_current=False
    )
    engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
    out = choose(thesis, engine, today=TODAY)
    assert out["source"] == "motor"
    assert out["thesis_displaced"] == {"version": 2, "cause": "modelo_anterior"}
    assert "versión anterior del motor" in out["reason"]


def test_unknown_freshness_is_neutral_and_keeps_the_reviewed_figure():
    # None = sin evidencia (tesis anterior a la señal engine_version, o inputs
    # no comprobables): NO desplaza. La cifra revisada no se esconde por no
    # poder comprobar.
    thesis = Candidate(
        value=150.0,
        as_of=TODAY - timedelta(days=3),
        thesis_version=3,
        inputs_fresh=None,
        model_current=None,
    )
    engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
    out = choose(thesis, engine, today=TODAY)
    assert (out["source"], out["rule"]) == ("tesis", "tesis_vigente")
    assert "thesis_displaced" not in out
    assert out["reason"] is None


def test_confirmed_fresh_inputs_and_current_model_keep_the_thesis():
    thesis = Candidate(
        value=150.0,
        as_of=TODAY - timedelta(days=3),
        thesis_version=3,
        inputs_fresh=True,
        model_current=True,
    )
    engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
    assert choose(thesis, engine, today=TODAY)["rule"] == "tesis_vigente"


def test_displaced_thesis_keeps_its_number_visible_without_publishable_engine():
    # Sin motor publicable la tesis desplazada se sigue sirviendo (la cifra
    # revisada no se oculta), marcada como antigua y con el motivo a la vista.
    thesis = Candidate(
        value=150.0, as_of=TODAY - timedelta(days=3), thesis_version=3, inputs_fresh=False
    )
    engine = Candidate(value=90.0, as_of=TODAY, publishable=False)
    out = choose(thesis, engine, today=TODAY)
    assert (out["value"], out["source"], out["stale"]) == (150.0, "tesis", True)
    assert out["rule"] == "tesis_inputs_nuevas"
    assert "datos más recientes" in out["reason"]


def test_displaced_thesis_keeps_its_number_visible_without_engine_at_all():
    thesis = Candidate(
        value=150.0, as_of=TODAY - timedelta(days=3), thesis_version=3, model_current=False
    )
    out = choose(thesis, None, today=TODAY)
    assert (out["value"], out["source"], out["stale"]) == (150.0, "tesis", True)
    assert out["rule"] == "tesis_modelo_anterior"
    assert "versión anterior del motor" in out["reason"]


def test_newer_inputs_cause_wins_over_previous_model_cause():
    thesis = Candidate(
        value=150.0,
        as_of=TODAY - timedelta(days=3),
        thesis_version=3,
        inputs_fresh=False,
        model_current=False,
    )
    engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
    out = choose(thesis, engine, today=TODAY)
    assert out["thesis_displaced"]["cause"] == "inputs_nuevos"


def test_displaced_reason_is_english_in_english_scope(monkeypatch):
    monkeypatch.setattr(i18n, "language_enabled", lambda: True)
    token = i18n.set_language_scope("en")
    try:
        thesis = Candidate(
            value=150.0, as_of=TODAY - timedelta(days=3), thesis_version=3, inputs_fresh=False
        )
        engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
        out = choose(thesis, engine, today=TODAY)
        assert "newer data" in out["reason"]
    finally:
        i18n.reset_language_scope(token)


# ------------------------------------------------------- integración (sqlite)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _company(db, ticker):
    company = Company(ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
                      company_type="listed", valuation_model="dcf")
    db.add(company)
    db.flush()
    return company


def _publishable_model(db, company):
    # La compuerta de publicación exige un modelo verificado: sin él la tesis
    # archivada no es evidencia de una valoración publicable (regla previa).
    from app.models import FundamentalModelVersion

    db.add(FundamentalModelVersion(
        company_id=company.id, version=1, engine_version="test", algorithm_version="test",
        framework_key="dcf", horizon_years=10, status="ok", publishable=True,
        input_fingerprint="input", forecast_fingerprint="forecast",
        market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
    ))


def _thesis(db, company, *, basis=None, stamp=THESIS_STAMP):
    _publishable_model(db, company)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="published", expected_value=150,
        thesis_markdown="t", executive_summary="s", valuation_basis=basis,
    )
    db.add(thesis)
    db.flush()
    thesis.updated_at = stamp
    db.flush()
    return thesis


def _engine_output(db, company, *, status, expected, version=1):
    model = ValuationModel(company_id=company.id, model_type="dcf", version=version,
                           status=status, calculation_trace={})
    db.add(model)
    db.flush()
    db.add(ValuationOutput(valuation_model_id=model.id, scenario="base",
                           value_per_share=expected,
                           output_payload={"expected_value": expected, "base_value": expected}))
    db.flush()


def test_candidates_flags_inputs_newer_than_thesis(db):
    company = _company(db, "STALEIN")
    _thesis(db, company)
    fact = FinancialFact(company_id=company.id, metric="revenue", value=10, period="FY",
                         fiscal_year=2026, source_type="sec")
    db.add(fact)
    db.flush()
    fact.updated_at = datetime(2026, 11, 3, 12, 0)  # posterior a la tesis
    db.commit()
    candidate = fvs.thesis_candidates(db, [company.id])[company.id]
    assert candidate.inputs_fresh is False


def test_candidates_fresh_when_no_input_is_newer(db):
    company = _company(db, "FRESHIN")
    _thesis(db, company)
    fact = FinancialFact(company_id=company.id, metric="revenue", value=10, period="FY",
                         fiscal_year=2026, source_type="sec")
    db.add(fact)
    db.flush()
    fact.updated_at = datetime(2026, 10, 30, 12, 0)  # anterior a la tesis
    db.commit()
    candidate = fvs.thesis_candidates(db, [company.id])[company.id]
    assert candidate.inputs_fresh is True


def test_candidates_flags_previous_engine_version(db):
    company = _company(db, "OLDMODEL")
    _thesis(db, company, basis={"engine_version": "valuation-engines-v1"})
    db.commit()
    candidate = fvs.thesis_candidates(db, [company.id])[company.id]
    assert candidate.model_current is False


def test_candidates_confirms_current_engine_version(db):
    company = _company(db, "CURMODEL")
    _thesis(db, company, basis={"engine_version": MODEL_VERSION})
    db.commit()
    candidate = fvs.thesis_candidates(db, [company.id])[company.id]
    assert candidate.model_current is True


def test_candidates_without_engine_version_is_neutral(db):
    # Tesis anterior a la señal (sin engine_version persistido): None, y por
    # tanto NO desplaza la cifra revisada (decisión documentada).
    company = _company(db, "NOSIGNAL")
    _thesis(db, company, basis={"expected_value": 150})
    db.commit()
    candidate = fvs.thesis_candidates(db, [company.id])[company.id]
    assert candidate.model_current is None


def test_batch_serves_engine_and_explains_when_thesis_is_displaced(db):
    company = _company(db, "DISPLACED")
    _thesis(db, company, basis={"engine_version": "valuation-engines-v1"})
    _engine_output(db, company, status="final", expected=90.0)
    db.commit()
    out = fvs.resolve_fair_values(db, [company])[company.id]
    assert (out["value"], out["source"]) == (90.0, "motor")
    assert out["thesis_displaced"] == {"version": 1, "cause": "modelo_anterior"}
    assert "versión anterior del motor" in out["reason"]


def test_single_resolve_recalculates_live_only_when_thesis_is_displaced(db, monkeypatch):
    displaced = _company(db, "LIVEYES")
    _thesis(db, displaced, basis={"engine_version": "valuation-engines-v1"})
    fresh = _company(db, "LIVENO")
    _thesis(db, fresh, basis={"engine_version": MODEL_VERSION})
    db.commit()

    calls = []

    def fake_value_company(self, db_, company_):
        calls.append(company_.ticker)
        return {"publishable": True, "expected_value": 90.0, "base_value": 90.0}

    from app.services.valuation_service import ValuationService

    monkeypatch.setattr(ValuationService, "value_company", fake_value_company)
    out = fvs.resolve_fair_value(db, displaced, live=True, today=TODAY)
    assert calls == ["LIVEYES"]  # la tesis desplazada dispara el recálculo
    assert (out["value"], out["source"]) == (90.0, "motor")
    out = fvs.resolve_fair_value(db, fresh, live=True, today=TODAY)
    assert calls == ["LIVEYES"]  # la tesis vigente no paga el cálculo
    assert (out["value"], out["source"]) == (150.0, "tesis")
