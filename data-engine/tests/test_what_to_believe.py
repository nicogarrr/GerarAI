"""«Qué hace falta creer»: WACC implícito, crecimiento del DCF inverso y
múltiplo de salida leídos del DCF ya calculado (sin cambiar cómo calcula)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company
from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.normalized_fcf import ProjectionPlan, run_planned
from app.valuation.what_to_believe import (
    EXIT_FCF_MULTIPLE,
    IMPLIED_WACC_BOUNDS,
    build_what_to_believe,
    dcf_paths_from_trace,
    exit_multiple_value,
    implied_exit_multiple,
    solve_implied_wacc,
    value_at_wacc,
)
from tests.auth_helpers import auth_settings, signed_request
from tests.test_cross_tenant_probes import _no_network

SECRET = "what-to-believe-secret-with-32-chars-ok!!"


def _flat_trace(**over) -> dict:
    inputs: dict = dict(
        revenue=1_000.0, revenue_growth=0.0, fcf_margin=0.08, wacc=0.10,
        terminal_growth=0.0, net_debt=0.0, shares_outstanding=1.0,
    )
    inputs.update(over)
    return run_dcf(DCFInputs(**inputs)).trace


def _valuation(base_trace: dict, *, base_value: float, price: float, **extra) -> dict:
    result = {
        "status": "ok",
        "base_value": base_value,
        "current_price": price,
        "value_currency": "USD",
        "reverse_dcf": {"status": "ok", "required_revenue_growth": 0.21},
        "trace": {"engine": "standard_dcf", "wacc": base_trace["inputs"]["wacc"],
                  "scenarios": {"base": {"value_per_share": base_value, "trace": base_trace}}},
    }
    result.update(extra)
    return result


def test_wacc_implicito_analitico_perpetuidad_sin_crecimiento():
    # FCF constante 80 y g = 0: el DCF es exactamente 80 / WACC por acción.
    paths = dcf_paths_from_trace(_flat_trace())
    assert paths is not None
    assert value_at_wacc(paths, 0.10) == pytest.approx(800.0)
    solved = solve_implied_wacc(paths, 1_000.0)
    assert solved["status"] == "ok"
    assert solved["wacc"] == pytest.approx(0.08, abs=1e-9)


def test_ida_y_vuelta_dcf_multietapa_al_wacc_implicito_da_el_precio():
    plan = ProjectionPlan(growth_fade=True, margin_start=0.20)
    trace = run_planned(
        plan, revenue=7_288.0, growth=0.45, margin=0.40, base_margin=0.40, wacc=0.085,
        terminal_growth=0.03, net_debt=-6_000.0, shares_outstanding=2_565.0, minority_interest=100.0,
    ).trace
    paths = dcf_paths_from_trace(trace)
    assert paths is not None and len(paths.growth_path) == 10
    # La reconstrucción reproduce el valor del motor al WACC usado.
    assert value_at_wacc(paths, 0.085) == pytest.approx(
        run_planned(plan, revenue=7_288.0, growth=0.45, margin=0.40, base_margin=0.40, wacc=0.085,
                    terminal_growth=0.03, net_debt=-6_000.0, shares_outstanding=2_565.0,
                    minority_interest=100.0).value_per_share)
    for price in (40.0, 175.4, 900.0):
        solved = solve_implied_wacc(paths, price)
        assert solved["status"] == "ok"
        assert value_at_wacc(paths, solved["wacc"]) == pytest.approx(price, rel=1e-6)


def test_fuera_de_rango_en_los_dos_sentidos():
    paths = dcf_paths_from_trace(_flat_trace())
    assert paths is not None
    top = value_at_wacc(paths, IMPLIED_WACC_BOUNDS[0])  # 80 / 3 % = 2.666,7
    below = solve_implied_wacc(paths, top * 1.5)
    assert below["status"] == "out_of_range" and below["direction"] == "below_min"
    assert below["wacc"] is None
    above = solve_implied_wacc(paths, 1.0)
    assert above["status"] == "out_of_range" and above["direction"] == "above_max"


def test_limite_inferior_respeta_el_crecimiento_terminal():
    paths = dcf_paths_from_trace(_flat_trace(terminal_growth=0.05, wacc=0.09))
    assert paths is not None
    solved = solve_implied_wacc(paths, 50.0)
    assert solved["bounds"][0] > 0.05


def test_fcf_negativo_no_da_wacc_implicito():
    paths = dcf_paths_from_trace(_flat_trace(fcf_margin=-0.05))
    assert paths is not None
    assert solve_implied_wacc(paths, 10.0)["status"] == "not_available"


def test_multiplo_de_salida_equivalente_a_gordon_y_su_inverso():
    trace = _flat_trace(revenue_growth=0.05, terminal_growth=0.02, wacc=0.09)
    paths = dcf_paths_from_trace(trace)
    assert paths is not None
    gordon = value_at_wacc(paths, 0.09)
    # Con múltiplo (1+g)/(WACC-g) el terminal por múltiplo ES el de Gordon.
    same = exit_multiple_value(paths, 0.09, multiple=1.02 / 0.07)
    assert same == pytest.approx(gordon)
    assert implied_exit_multiple(paths, 0.09, gordon) == pytest.approx(1.02 / 0.07)
    assert exit_multiple_value(paths, 0.09) > gordon  # 25x > 14,6x


def test_bloque_completo_convierte_divisa_y_adr_desde_el_propio_resultado():
    trace = _flat_trace()  # 800 por acción ordinaria, divisa de reporte
    # Publicado: 0,5 unidades de listado por unidad de reporte y 2 ordinarias por ADR.
    valuation = _valuation(trace, base_value=400.0, price=1_000.0, adr_ratio=2.0)
    block = build_what_to_believe("zz", valuation, consensus_price=1_600.0,
                                  consensus_currency="usd", consensus_source="Yahoo")
    assert block.status == "ok" and block.ticker == "ZZ"
    assert block.wacc_used == pytest.approx(0.10)
    assert block.base_value == pytest.approx(800.0)  # por ADR
    # Precio 1.000 por ADR = 1.000 en unidades de la traza: 80 / 8 %.
    assert block.implied_wacc_price is not None
    assert block.implied_wacc_price.wacc == pytest.approx(0.08, abs=1e-9)
    assert block.implied_wacc_consensus is not None
    assert block.implied_wacc_consensus.wacc == pytest.approx(0.05, abs=1e-9)
    assert block.implied_growth is not None
    assert block.implied_growth.required_revenue_growth == pytest.approx(0.21)
    assert block.exit_multiple is not None
    assert block.exit_multiple.multiple == EXIT_FCF_MULTIPLE
    assert block.exit_multiple.gordon_value_per_share == pytest.approx(800.0)
    assert block.exit_multiple.value_per_share is not None
    assert block.exit_multiple.implied_multiple_for_price is not None


def test_consenso_en_otra_divisa_no_se_usa():
    valuation = _valuation(_flat_trace(), base_value=800.0, price=1_000.0)
    block = build_what_to_believe("ZZ", valuation, consensus_price=50.0, consensus_currency="EUR")
    assert block.status == "ok"
    assert block.implied_wacc_consensus is None and block.consensus_price is None


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda v: v.update(status="insufficient_data"), "valuation_unavailable"),
        (lambda v: v["trace"]["scenarios"]["base"].update(trace={"method": "ddm"}), "engine_not_dcf"),
        (lambda v: v["trace"].update(scenarios={}), "engine_not_dcf"),
        (lambda v: v.update(base_value=None), "no_base_value"),
        (lambda v: v.update(current_price=None), "no_price"),
    ],
)
def test_no_aplica_con_motivo(mutate, code):
    valuation = _valuation(_flat_trace(), base_value=800.0, price=1_000.0)
    mutate(valuation)
    block = build_what_to_believe("ZZ", valuation)
    assert block.status == "not_applicable" and block.reason_code == code
    assert block.reason and block.implied_wacc_price is None


# ------------------------------------------------------------------ API


@pytest.fixture()
def env(monkeypatch):
    _no_network(monkeypatch)
    init_db()
    monkeypatch.setattr(auth_module, "get_settings",
                        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"))
    suffix = uuid4().hex[:8]
    client = TestClient(main.app)
    ticker = f"WB{suffix[:4].upper()}"
    with SessionLocal() as db:
        db.add(Company(ticker=ticker, name=f"Empresa {ticker}", exchange="NASDAQ", currency="USD",
                       sector="Test", industry="Test", company_type="standard",
                       valuation_model="standard_dcf"))
        db.commit()
    seen: list[object] = []

    def fake_value_company(self, db, company, **_kw):
        seen.append(db.info.get("tenant_id"))
        return _valuation(_flat_trace(), base_value=800.0, price=1_000.0)

    from app.services import analyst_targets_service as ats
    from app.services.valuation_service import ValuationService

    async def fake_targets(symbol: str):
        return ats.AnalystTargets(symbol=symbol, status="available", fetched_at=0, currency="USD",
                                  consensus=ats.AnalystConsensus(mean=1_600.0))

    monkeypatch.setattr(ValuationService, "value_company", fake_value_company)
    monkeypatch.setattr(ats.analyst_targets_service, "get", fake_targets)

    def call(tenant: str, path: str):
        return signed_request(client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}", "GET", path)

    return {"call": call, "client": client, "ticker": ticker, "seen": seen}


def test_api_por_tenant_y_contrato(env):
    path = f"/api/valuation/{env['ticker']}/what-to-believe"
    assert env["client"].get(path).status_code == 401
    ra = env["call"]("a", path)
    rb = env["call"]("b", path)
    assert ra.status_code == 200 and rb.status_code == 200
    body = ra.json()
    assert body["status"] == "ok"
    assert body["implied_wacc_price"]["wacc"] == pytest.approx(0.08, abs=1e-9)
    assert body["implied_wacc_consensus"]["wacc"] == pytest.approx(0.05, abs=1e-9)
    # Cada valoración se calcula en el ámbito del tenant que la pide.
    assert len(env["seen"]) == 2 and None not in env["seen"] and env["seen"][0] != env["seen"][1]


def test_api_ticker_inexistente_404(env):
    assert env["call"]("a", "/api/valuation/NOPE0000/what-to-believe").status_code == 404



def test_extremo_a_extremo_con_el_motor_real_adr_y_ordinaria_mismo_wacc_implicito():
    from app.services.valuation_service import ValuationService
    from tests.test_valuation_engines_refined import (
        _add_facts,
        _add_price,
        _add_traceable_wacc,
        _cleanup,
        _make_company,
    )

    facts = {"revenue": 1000, "free_cash_flow": 120, "revenue_growth": 0.07,
             "shares_diluted": 100, "net_debt": 200}
    init_db()
    db = SessionLocal()
    tickers = ["WTBA", "WTBO"]
    try:
        out = {}
        for ticker, tags, price in (("WTBA", ["adr:2"], 30.0), ("WTBO", [], 15.0)):
            company = _make_company(db, ticker, company_type="standard",
                                    valuation_model="standard_dcf", factor_tags=tags)
            _add_facts(db, company, facts)
            _add_price(db, company, price)
            _add_traceable_wacc(db, company)
            valuation = ValuationService().value_company(db, company)
            assert valuation["status"] == "ok"
            out[ticker] = (valuation, build_what_to_believe(ticker, valuation))
        (adr_val, adr), (ord_val, ordinary) = out["WTBA"], out["WTBO"]
        assert adr.status == "ok" and ordinary.status == "ok"
        # El WACC «usado» es el de la traza del motor, sin recalcularlo.
        assert ordinary.wacc_used == pytest.approx(ord_val["trace"]["wacc"])
        assert adr.implied_wacc_price is not None and ordinary.implied_wacc_price is not None
        assert adr.implied_wacc_price.wacc == pytest.approx(ordinary.implied_wacc_price.wacc)
        # Ida y vuelta con el DCF del propio motor: a ese WACC sale el precio.
        paths = dcf_paths_from_trace(ord_val["trace"]["scenarios"]["base"]["trace"])
        assert paths is not None
        assert value_at_wacc(paths, paths.wacc) == pytest.approx(ord_val["base_value"])
        if ordinary.implied_wacc_price.status == "ok":
            assert value_at_wacc(paths, ordinary.implied_wacc_price.wacc) == pytest.approx(15.0, rel=1e-6)
        assert adr.base_value == pytest.approx(adr_val["base_value"] * 2)
    finally:
        _cleanup(db, tickers)
        db.close()
