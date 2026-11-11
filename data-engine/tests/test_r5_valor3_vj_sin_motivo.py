"""Regla «vj-sin-candidato-v1»: el «Sin valor justo» nunca sale sin motivo.

Intertek (ITRK.L) en local, 11-nov-2026: sin tesis publicada ni valoración del motor guardada, la watchlist y el
resumen de valoración enseñaban «Sin valor justo» con ``reason: None`` (74 de las 98 empresas de la base local sin
valor justo). Ahora el motivo dice exactamente qué falta, para todas las empresas: tesis, motor o las dos cosas.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import i18n
from app.models.entities import Base, Company, ThesisVersion, ValuationModel, ValuationOutput
from app.services import fair_value_service as fvs

TODAY = date(2026, 11, 11)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _company(db, ticker):
    company = Company(ticker=ticker, name=ticker, exchange="LSE", currency="GBP",
                      company_type="listed", valuation_model="dcf")
    db.add(company)
    db.flush()
    return company


def _model(db, company, payload, *, status="final"):
    model = ValuationModel(company_id=company.id, model_type="dcf", version=1, status=status,
                           calculation_trace={})
    db.add(model)
    db.flush()
    if payload is not None:
        db.add(ValuationOutput(valuation_model_id=model.id, scenario="base", value_per_share=None,
                               output_payload=payload))
    db.flush()
    return model


def _read(db, company):
    return fvs.resolve_fair_values(db, [company], today=TODAY)[company.id]


def test_sin_tesis_ni_motor_guardado_dice_por_que(db):
    company = _company(db, "VJNONE")
    db.commit()
    out = _read(db, company)
    assert out["value"] is None and out["label"] == "Sin valor justo"
    assert out["reason"] == "No hay tesis publicada y no hay ninguna valoración del motor guardada para esta empresa."


def test_motor_guardado_con_valor_negativo_lo_dice(db):
    company = _company(db, "VJNEG")
    _model(db, company, {"expected_value": -12.0, "base_value": -12.0})
    db.commit()
    out = _read(db, company)
    assert out["value"] is None
    assert out["reason"].startswith("No hay tesis publicada y la última valoración del motor guardada del ")
    assert out["reason"].endswith("no da un valor por acción positivo.")


def test_motor_guardado_sin_resultado_lo_dice(db):
    company = _company(db, "VJNOOUT")
    _model(db, company, None)
    db.commit()
    assert "no tiene resultado" in _read(db, company)["reason"]


def test_adr_sin_valor_por_accion_cotizada(db):
    company = _company(db, "VJADR")
    _model(db, company, {"expected_value": 40.0, "adr_ratio": 5})
    db.commit()
    assert "no trae valor por acción cotizada (ADR)" in _read(db, company)["reason"]


def test_tesis_retenida_por_la_puerta_lo_dice(db):
    # Tesis publicada sin modelo publicable verificado: la puerta la retiene (no es candidata).
    company = _company(db, "VJWITH")
    db.add(ThesisVersion(company_id=company.id, version=2, status="published", expected_value=150,
                         thesis_markdown="t", executive_summary="s"))
    db.commit()
    reason = _read(db, company)["reason"]
    assert reason.startswith("La última tesis publicada (v2) está retenida (no hay un modelo publicable verificado")
    assert reason.endswith("y no hay ninguna valoración del motor guardada para esta empresa.")


def test_lectura_individual_sin_recalculo_mismo_motivo(db):
    company = _company(db, "VJONE")
    db.commit()
    out = fvs.resolve_fair_value(db, company, live=False, today=TODAY)
    assert out["reason"] == "No hay tesis publicada y no hay ninguna valoración del motor guardada para esta empresa."


def test_lectura_en_vivo_con_motor_caido_lo_dice(db, monkeypatch):
    company = _company(db, "VJFAIL")
    db.commit()

    class Broken:
        def value_company(self, *_args):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.services.valuation_service.ValuationService", Broken)
    out = fvs.resolve_fair_value(db, company, live=True, today=TODAY)
    assert out["value"] is None
    assert out["reason"] == "No hay tesis publicada y el motor de valoración falló al calcular."


def test_lectura_en_vivo_sin_valor_positivo_lo_dice(db, monkeypatch):
    company = _company(db, "VJLIVE")
    db.commit()

    class Negative:
        def value_company(self, *_args):
            return {"status": "draft", "publishable": False, "expected_value": -3.0}

    monkeypatch.setattr("app.services.valuation_service.ValuationService", Negative)
    out = fvs.resolve_fair_value(db, company, live=True, today=TODAY)
    assert out["reason"] == "No hay tesis publicada y el motor de valoración no dio un valor por acción positivo."


def test_motivo_en_ingles(db, monkeypatch):
    monkeypatch.setattr(i18n, "current_language", lambda: "en")
    monkeypatch.setattr(fvs, "current_language", lambda: "en")
    company = _company(db, "VJEN")
    db.commit()
    out = _read(db, company)
    assert out["label"] == "No fair value"
    assert out["reason"] == "There is no published thesis and no engine valuation is stored for this company."


def test_insuficiente_mantiene_su_motivo(db):
    # La corrida «insufficient_data» ya explica los inputs que faltan: ese motivo manda.
    company = _company(db, "VJINS")
    model = _model(db, company, None, status="insufficient_data")
    model.calculation_trace = {"missing_inputs": ["net_debt"], "reason": "x"}
    db.commit()
    reason = _read(db, company)["reason"]
    assert "faltan net_debt" in reason and "No hay tesis" not in reason
