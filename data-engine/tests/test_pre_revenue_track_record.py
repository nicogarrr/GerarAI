"""Empresas que queman caja: «sin valor justo fiable» con su historial (gerarai-dcavalor4, 7-nov-2026)."""

from app.valuation.pre_revenue_track_record import pre_revenue_track_record
from tests.test_valuation_engines_refined import _add_facts, _cleanup, _make_company


def _burning(**extra):
    trace = {"engine": "pre_revenue", "rejected_reported_fcf": {"free_cash_flow": -300.0}}
    trace.update(extra)
    return {"status": "insufficient_data", "expected_value": None, "trace": trace}


def test_cash_burner_gets_no_reliable_value_and_the_measured_history():
    record = pre_revenue_track_record(_burning())
    assert record is not None
    assert record["reliable_value"] is False
    assert record["cases"] == 4002
    assert record["price_ratio_12m"] == {"p10": 0.24, "p50": 0.81, "p90": 1.95}
    assert record["beat_spy_12m_share"] == 0.31
    assert record["stopped_filing_24m_share"] == 0.17
    assert record["message_es"] == (
        "Sin valor justo fiable: la empresa aún quema caja. En el backtest (4.002 casos así en "
        "EE. UU., 2014–2026) ningún método acertó el nivel: el DCF para empresas jóvenes salió "
        "fuera de 0,2x–5x el precio la mitad de las veces. A 12 meses, 8 de cada 10 veces el "
        "precio quedó entre 0,24x y 1,95x el de partida (mediana 0,81x); solo el 31 % batió al "
        "S&P 500, y el 17 % dejó de presentar cuentas en 2 años."
    )
    assert record["message_en"].startswith("No reliable fair value: the company still burns cash.")


def test_margin_convergence_orientation_from_negative_margin_also_carries_it():
    result = {
        "status": "ok",
        "expected_value": 24.4,
        "trace": {"engine": "pre_revenue", "method": "fcff_dcf_margin_convergence", "reported_fcf_margin": -15.46},
    }
    assert pre_revenue_track_record(result)["reliable_value"] is False
    missing_only = {"missing_inputs": ["non_negative_fcf_margin"], "trace": {"engine": "pre_revenue"}}
    assert pre_revenue_track_record(missing_only) is not None


def test_other_engines_and_positive_cash_flow_get_nothing():
    assert pre_revenue_track_record({"trace": {"engine": "standard_dcf", "rejected_reported_fcf": {"x": -1}}}) is None
    assert pre_revenue_track_record({"expected_value": 10.0, "trace": {"engine": "pre_revenue"}}) is None
    assert pre_revenue_track_record({"trace": {"engine": "pre_revenue", "reported_fcf_margin": 0.12}}) is None
    assert pre_revenue_track_record({"trace": {"engine": "pre_revenue", "reported_fcf_margin": True}}) is None
    assert pre_revenue_track_record({"expected_value": 1.0}) is None


def test_value_company_attaches_it_for_a_cash_burning_pre_revenue_name():
    from app.core.database import SessionLocal, init_db
    from app.services.valuation_service import ValuationService

    init_db()
    db = SessionLocal()
    ticker = "BURNX"
    try:
        company = _make_company(
            db, ticker, company_type="space_telecom_pre_fcf",
            valuation_model="probability_weighted_scenarios+dilution",
            factor_tags=["space", "speculative", "pre_fcf"],
        )
        _add_facts(
            db, company,
            {
                "revenue": 5, "shares_diluted": 250, "net_debt": -2000,
                "free_cash_flow": -1100, "operating_cash_flow": -300,
                "capital_expenditure": -800, "cash_and_equivalents": 4300,
            },
        )
        result = ValuationService().value_company(db, company)
        assert result["trace"]["engine"] == "pre_revenue"
        assert result["expected_value"] is None
        assert result["track_record"]["method"] == "pre_revenue"
        assert result["track_record"]["reliable_value"] is False
    finally:
        _cleanup(db, [ticker])
        db.close()
