"""Valor justo único: una sola precedencia para watchlist, inicio y screener."""
import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import valuation as valuation_routes
from app.api.routes import watchlist
from app.models.entities import (
    Base,
    Company,
    ThesisVersion,
    ValuationModel,
    ValuationOutput,
)
from app.services import fair_value_service as fvs
from app.services.fair_value_service import Candidate, choose

TODAY = date(2026, 10, 27)


def test_fresh_thesis_wins_over_publishable_engine():
    thesis = Candidate(value=150.0, as_of=TODAY - timedelta(days=30), thesis_version=3)
    engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
    out = choose(thesis, engine, today=TODAY)
    assert out["value"] == 150.0
    assert out["source"] == "tesis"
    assert out["label"] == "Tesis publicada v3"
    assert out["publishable"] is True
    assert out["stale"] is False
    assert out["rule"] == "tesis_vigente"


def test_publishable_engine_wins_over_stale_thesis():
    thesis = Candidate(value=150.0, as_of=TODAY - timedelta(days=181), thesis_version=1)
    engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
    out = choose(thesis, engine, today=TODAY)
    assert (out["value"], out["source"], out["label"]) == (90.0, "motor", "Motor de valoración")
    assert out["as_of"] == TODAY.isoformat()


def test_stale_thesis_wins_over_orientative_engine_and_says_so():
    thesis = Candidate(value=150.0, as_of=TODAY - timedelta(days=400), thesis_version=2)
    engine = Candidate(value=90.0, as_of=TODAY, publishable=False)
    out = choose(thesis, engine, today=TODAY)
    assert out["source"] == "tesis"
    assert out["stale"] is True
    assert out["label"] == "Tesis publicada v2 (antigua)"


def test_thesis_without_date_counts_as_stale():
    thesis = Candidate(value=150.0, as_of=None, thesis_version=2)
    engine = Candidate(value=90.0, as_of=TODAY, publishable=True)
    assert choose(thesis, engine, today=TODAY)["source"] == "motor"


def test_orientative_engine_is_labelled_and_not_publishable():
    out = choose(None, Candidate(value=42.5, as_of=TODAY, publishable=False), today=TODAY)
    assert out["source"] == "motor_orientativo"
    assert out["label"] == "Motor de valoración (orientativo)"
    assert out["publishable"] is False


def test_nothing_means_no_value_never_invented():
    out = choose(None, None, today=TODAY)
    assert out["value"] is None and out["source"] is None
    assert out["label"] == "Sin valor justo"


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
    from app.models import FundamentalModelVersion

    db.add(FundamentalModelVersion(
        company_id=company.id, version=1, engine_version="test", algorithm_version="test",
        framework_key="dcf", horizon_years=10, status="ok", publishable=True,
        input_fingerprint="input", forecast_fingerprint="forecast",
        market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
    ))


def _engine_output(db, company, *, status, expected, version=1, when=None):
    model = ValuationModel(company_id=company.id, model_type="dcf", version=version,
                           status=status, calculation_trace={})
    if when is not None:
        model.created_at = when
    db.add(model)
    db.flush()
    db.add(ValuationOutput(valuation_model_id=model.id, scenario="base",
                           value_per_share=expected,
                           output_payload={"expected_value": expected, "base_value": expected}))
    db.flush()


def test_batch_uses_latest_persisted_engine_when_there_is_no_thesis(db):
    company = _company(db, "ENGONLY")
    _engine_output(db, company, status="final", expected=80.0, version=1)
    _engine_output(db, company, status="draft", expected=95.0, version=2)
    db.commit()
    out = fvs.resolve_fair_values(db, [company])[company.id]
    # La última versión manda; es borrador, así que se declara orientativa.
    assert out["value"] == 95.0
    assert out["source"] == "motor_orientativo"
    assert out["ticker"] == "ENGONLY"


def test_batch_endpoint_and_watchlist_agree(db, monkeypatch):
    with_thesis = _company(db, "WITHTH")
    db.add(ThesisVersion(company_id=with_thesis.id, version=4, status="published",
                         expected_value=150, thesis_markdown="t", executive_summary="s"))
    _publishable_model(db, with_thesis)
    _engine_output(db, with_thesis, status="final", expected=60.0)
    engine_only = _company(db, "ONLYENG")
    _engine_output(db, engine_only, status="final", expected=70.0)
    db.commit()

    batch = valuation_routes.fair_values(tickers="withth,ONLYENG,NOPE", db=db)
    assert set(batch["items"]) == {"WITHTH", "ONLYENG"}
    assert batch["items"]["WITHTH"]["source"] == "tesis"
    assert batch["items"]["WITHTH"]["value"] == 150.0
    assert batch["items"]["ONLYENG"]["source"] == "motor"
    assert "Tesis publicada" in batch["precedence"]

    async def earnings(*args):
        return {"status": "unavailable", "events": []}

    monkeypatch.setattr(watchlist, "fetch_earnings_range", earnings)
    monitor = asyncio.run(watchlist.watchlist_monitor(tickers="WITHTH,ONLYENG", db=db))
    for ticker in ("WITHTH", "ONLYENG"):
        row = monitor["items"][ticker]
        assert row["fair_value"] == batch["items"][ticker]["value"]
        assert row["fair_value_source"] == batch["items"][ticker]["source"]
        assert row["fair_value_label"] == batch["items"][ticker]["label"]
    assert monitor["items"]["ONLYENG"]["fair_value_thesis_version"] is None


def test_single_ticker_computes_engine_live_only_when_thesis_is_not_enough(db, monkeypatch):
    company = _company(db, "LIVE")
    db.commit()
    calls = []

    class FakeValuation:
        def value_company(self, _db, _company):
            calls.append(_company.ticker)
            return {"expected_value": 120.0, "publishable": True}

    monkeypatch.setattr("app.services.valuation_service.ValuationService", FakeValuation)
    out = valuation_routes.fair_value("live", db=db)
    assert (out["value"], out["source"]) == (120.0, "motor")
    assert calls == ["LIVE"]

    _publishable_model(db, company)
    db.add(ThesisVersion(company_id=company.id, version=1, status="published",
                         expected_value=200, thesis_markdown="t", executive_summary="s"))
    db.commit()
    calls.clear()
    out = valuation_routes.fair_value("LIVE", db=db)
    assert (out["value"], out["source"]) == (200.0, "tesis")
    assert calls == []  # tesis vigente: el motor no se paga


def test_single_ticker_engine_failure_degrades_to_no_value(db, monkeypatch):
    _company(db, "BROKEN")
    db.commit()

    class Boom:
        def value_company(self, *_args):
            raise RuntimeError("motor caído")

    monkeypatch.setattr("app.services.valuation_service.ValuationService", Boom)
    out = valuation_routes.fair_value("BROKEN", db=db)
    assert out["value"] is None and out["source"] is None


def test_stale_thesis_is_dated_from_its_last_update(db):
    company = _company(db, "OLDTH")
    old = datetime.now(UTC) - timedelta(days=400)
    db.add(ThesisVersion(company_id=company.id, version=1, status="published",
                         expected_value=150, thesis_markdown="t", executive_summary="s",
                         created_at=old, updated_at=old))
    _engine_output(db, company, status="final", expected=99.0)
    db.commit()
    out = fvs.resolve_fair_values(db, [company])[company.id]
    assert out["source"] == "motor"
    assert out["value"] == 99.0



# --- ADR: el valor justo se compara con el precio del ADR (base ADR) ---------
# Cálculo independiente: ordinaria 10, ratio 8 ordinarias por ADR -> 80 por ADR.


def _adr_engine_output(db, company, *, listed):
    model = ValuationModel(company_id=company.id, model_type="dcf", version=1,
                           status="final", calculation_trace={})
    db.add(model)
    db.flush()
    payload = {"expected_value": 10.0, "base_value": 10.0, "adr_ratio": 8.0,
               "value_per_share_basis": "ordinary_share"}
    if listed:
        payload["listed_share_values"] = {"base": 80.0, "expected": 80.0}
    db.add(ValuationOutput(valuation_model_id=model.id, scenario="base",
                           value_per_share=10.0, output_payload=payload))
    db.flush()


def test_adr_persisted_engine_value_is_per_adr_not_per_ordinary(db):
    company = _company(db, "ADRX")
    _adr_engine_output(db, company, listed=True)
    db.commit()
    out = fvs.resolve_fair_values(db, [company])[company.id]
    assert out["value"] == 80.0


def test_adr_engine_without_listed_values_is_not_comparable(db):
    company = _company(db, "ADRY")
    _adr_engine_output(db, company, listed=False)
    db.commit()
    out = fvs.resolve_fair_values(db, [company])[company.id]
    assert out["value"] is None


def test_adr_thesis_value_uses_listed_share_basis(db):
    company = _company(db, "ADRT")
    db.add(ThesisVersion(company_id=company.id, version=1, status="published",
                         expected_value=10, thesis_markdown="t", executive_summary="s",
                         valuation_basis={"adr_ratio": 8.0, "value_per_share_basis": "ordinary_share",
                                          "listed_share_values": {"base": 80.0, "expected": 80.0}}))
    _publishable_model(db, company)
    db.commit()
    thesis = fvs.thesis_candidates(db, [company.id]).get(company.id)
    assert thesis is not None and thesis.value == 80.0


def test_adr_live_engine_value_is_per_adr(db, monkeypatch):
    from app.services import valuation_service

    company = _company(db, "ADRL")
    db.commit()
    monkeypatch.setattr(valuation_service.ValuationService, "value_company",
                        lambda self, db, company: {"expected_value": 10.0, "adr_ratio": 8.0,
                                                   "publishable": True,
                                                   "listed_share_values": {"expected": 80.0}})
    out = fvs.resolve_fair_value(db, company, live=True)
    assert out["value"] == 80.0
