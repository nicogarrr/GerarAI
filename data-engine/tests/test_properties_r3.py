"""Propiedades (Hypothesis) de la lógica nueva de la ronda 3.

- Proyección de ahorro: aportado = cuota × meses; con rentabilidad 0 el valor
  final es lo aportado; con rentabilidad > 0 nunca menos; monótona en la cuota
  y en la rentabilidad; en dinero de hoy nunca más que en nominal si hay
  inflación ≥ 0; fuera de rango solo ValueError, nunca otra excepción.
- Ajustes DCA: cualquier par válido se guarda y se relee igual, por tenant.
"""
from __future__ import annotations

import math
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.savings_projection import project_savings

monthly = st.floats(min_value=0, max_value=1_000_000, allow_nan=False)
years = st.integers(min_value=1, max_value=80)
rate = st.floats(min_value=-0.99, max_value=1, allow_nan=False)
small_rate = st.floats(min_value=-0.5, max_value=0.3, allow_nan=False)
inflation = st.floats(min_value=0, max_value=1, allow_nan=False)
PROPS = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@PROPS
@given(monthly, years)
def test_zero_return_is_exactly_what_you_contributed(m, y):
    out = project_savings(monthly=m, years=y, annual_return=0.0)
    assert out["contributed"] == round(m * y * 12, 2)
    assert out["terminal_value"] == out["contributed"]
    assert out["simulated_return"] == 0


@PROPS
@given(monthly, years, st.floats(min_value=0, max_value=1, allow_nan=False))
def test_non_negative_return_never_loses_money(m, y, r):
    out = project_savings(monthly=m, years=y, annual_return=r)
    assert math.isfinite(out["terminal_value"])
    assert out["terminal_value"] >= out["contributed"] - 0.01


@PROPS
@given(st.floats(min_value=0, max_value=500_000, allow_nan=False), st.floats(min_value=0, max_value=500_000, allow_nan=False),
       st.integers(min_value=1, max_value=40), small_rate)
def test_more_monthly_contribution_never_ends_lower(a, b, y, r):
    low, high = sorted((a, b))
    lo = project_savings(monthly=low, years=y, annual_return=r)["terminal_value"]
    hi = project_savings(monthly=high, years=y, annual_return=r)["terminal_value"]
    assert hi >= lo - 0.01


@PROPS
@given(st.floats(min_value=1, max_value=10_000, allow_nan=False), st.integers(min_value=1, max_value=40), small_rate, small_rate)
def test_higher_return_never_ends_lower(m, y, a, b):
    low, high = sorted((a, b))
    lo = project_savings(monthly=m, years=y, annual_return=low)["terminal_value"]
    hi = project_savings(monthly=m, years=y, annual_return=high)["terminal_value"]
    assert hi >= lo - 0.01


@PROPS
@given(monthly, years, rate, inflation, st.floats(min_value=0, max_value=0.5, allow_nan=False))
def test_today_money_and_dividends_are_consistent(m, y, r, inf, dy):
    out = project_savings(monthly=m, years=y, annual_return=r, inflation=inf, dividend_yield=dy)
    assert out["terminal_value"] >= 0
    assert out["terminal_value_today_money"] <= out["terminal_value"] + 0.01
    assert out["terminal_annual_gross_dividend"] == pytest.approx(out["terminal_value"] * dy, abs=0.02)
    assert out["terminal_monthly_gross_dividend_equivalent"] == pytest.approx(out["terminal_annual_gross_dividend"] / 12, abs=0.02)


@PROPS
@given(st.one_of(st.floats(), st.integers(min_value=-10**6, max_value=10**6), st.booleans()),
       st.one_of(st.integers(min_value=-200, max_value=200), st.booleans(), st.floats(allow_nan=True)),
       st.one_of(st.floats(), st.booleans()))
def test_out_of_range_input_only_raises_value_error(m, y, r):
    try:
        out = project_savings(monthly=m, years=y, annual_return=r)
    except ValueError:
        return
    assert math.isfinite(out["terminal_value"])


SECRET = "props-r3-secret-with-at-least-thirty-two-chars!!"


@pytest.fixture(scope="module")
def dca_client():
    import main
    from app.core import auth as auth_module
    from app.core.database import init_db
    from tests.auth_helpers import auth_settings, signed_request

    init_db()
    original = auth_module.get_settings
    auth_module.get_settings = lambda: auth_settings(strict=True, secret=SECRET, app_env="test")
    client = TestClient(main.app, raise_server_exceptions=False)
    suffix = uuid4().hex[:8]

    def call(tenant: str, method: str, path: str, body=None):
        return signed_request(client, SECRET, f"{tenant}-{suffix}", f"u-{tenant}-{suffix}", method, path, json_body=body)

    yield call
    auth_module.get_settings = original


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(st.integers(min_value=0, max_value=4), st.integers(min_value=0, max_value=4), st.integers(min_value=0, max_value=4))
def test_dca_settings_round_trip_and_stay_per_tenant(dca_client, up, down, other):
    a = dca_client("a", "PUT", "/api/settings/dca", {"up_min_level": up, "down_max_level": down})
    assert a.status_code == 200, a.text
    b = dca_client("b", "PUT", "/api/settings/dca", {"up_min_level": other, "down_max_level": other})
    assert b.status_code == 200, b.text
    read = dca_client("a", "GET", "/api/settings/dca").json()
    assert (read["up_min_level"], read["down_max_level"], read["configured"]) == (up, down, True)
    assert dca_client("b", "GET", "/api/settings/dca").json()["up_min_level"] == other


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(st.one_of(st.integers(min_value=-10, max_value=10).filter(lambda v: not 0 <= v <= 4), st.text(max_size=3),
                 st.floats(allow_nan=False), st.booleans(), st.none()))
def test_dca_settings_reject_invalid_levels_without_5xx(dca_client, bad):
    response = dca_client("a", "PUT", "/api/settings/dca", {"up_min_level": bad, "down_max_level": 1})
    assert response.status_code == 422, response.text
