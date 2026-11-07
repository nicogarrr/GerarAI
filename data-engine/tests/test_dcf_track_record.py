"""Fiabilidad histórica del DCF estándar junto al valor (gerarai-dcavalor1, 7-nov-2026)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.valuation.track_record import dcf_track_record


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _result(engine="standard_dcf", value=100.0):
    return {"expected_value": value, "trace": {"engine": engine}}


def test_standard_dcf_value_carries_the_measured_track_record():
    record = dcf_track_record(_result())
    assert record is not None
    assert record["horizon_months"] == 12
    assert (record["price_to_value_p10"], record["price_to_value_p50"], record["price_to_value_p90"]) == (
        0.63,
        1.65,
        3.69,
    )
    assert record["undervalued_beat_spy_share"] == 0.49
    assert record["message_es"] == (
        "Fiabilidad del método: en el backtest, 8 de cada 10 veces el precio a 12 meses quedó "
        "entre 0,63x y 3,69x este valor (mediana 1,65x; el método suele quedarse corto). Sirve para "
        "comparar empresas entre sí, sobre todo a 2 años, no como precio objetivo."
    )
    assert record["message_en"].startswith("Method track record: in the backtest, 8 times out of 10")


def test_other_engines_or_no_value_get_no_track_record():
    assert dcf_track_record(_result(engine="relative_multiples")) is None
    assert dcf_track_record(_result(engine="reit")) is None
    assert dcf_track_record(_result(value=None)) is None
    assert dcf_track_record(_result(value=0.0)) is None
    assert dcf_track_record(_result(value=True)) is None
    assert dcf_track_record({"expected_value": 10.0}) is None


def test_value_company_attaches_it_for_a_standard_dcf(db):
    from app.services.valuation_service import ValuationService
    from tests.test_valgrandes_normalized_fcf import AMZN, M, _seed

    company = _seed(db, "TRKX", AMZN, shares=10_827 * M, net_debt=-5_233 * M, price=251.36, wacc=0.11141566)
    result = ValuationService().value_company(db, company)
    assert result["trace"]["engine"] == "standard_dcf"
    assert result["expected_value"] and result["expected_value"] > 0
    assert result["track_record"]["price_to_value_p50"] == 1.65


def test_api_schema_keeps_the_track_record():
    from app.schemas.api import ValuationResponse

    out = ValuationResponse(ticker="X", model_type="dcf", track_record={"price_to_value_p50": 1.65}).model_dump()
    assert out["track_record"]["price_to_value_p50"] == 1.65
    assert ValuationResponse(ticker="X", model_type="dcf").model_dump()["track_record"] is None
