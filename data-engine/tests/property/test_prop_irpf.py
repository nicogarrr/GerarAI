"""Escala del ahorro y casillas del Modelo 100."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.services.tax_irpf_filing import build_casillas, calculate_savings_tax, savings_bands

# savings_bands falla cerrado antes de 2007 (sin escala verificada).
years = st.integers(min_value=2007, max_value=2030)
income = st.integers(min_value=-1_000, max_value=2_000_000).map(Decimal)


@given(years)
def test_bands_are_contiguous_and_rates_never_fall(year):
    bands = savings_bands(year)
    assert bands[0][0] == 0
    for (lo, hi, rate), (lo2, _hi2, rate2) in zip(bands, bands[1:]):
        assert hi == lo2 and lo < hi
        assert rate2 >= rate
    assert bands[-1][1] is None


@given(years, income, income)
def test_savings_tax_is_monotone_and_below_the_top_rate(year, a, b):
    lo, hi = sorted((a, b))
    t_lo, t_hi = calculate_savings_tax(lo, year), calculate_savings_tax(hi, year)
    assert Decimal("0") <= t_lo <= t_hi
    top = savings_bands(year)[-1][2]
    if hi > 0:
        assert t_hi <= hi * top
        # el tramo marginal nunca supera el tipo maximo
        assert t_hi - t_lo <= (hi - max(lo, Decimal("0"))) * top + Decimal("1e-9")


sale = st.fixed_dictionaries(
    {
        "date": st.just("2025-06-01"),
        "proceeds_base": st.integers(0, 10_000).map(float),
        "cost_base": st.one_of(st.none(), st.integers(0, 10_000).map(float)),
        "gain_base": st.one_of(st.none(), st.integers(-5_000, 5_000).map(float)),
        "over_sell": st.booleans(),
    }
)


@given(st.lists(st.fixed_dictionaries({"ticker": st.sampled_from(["A", "B"]), "sales": st.lists(sale, max_size=4)}), max_size=3))
def test_casillas_totals_are_exact_or_none(realized):
    block = build_casillas([], realized, 2025)["acciones_negociadas"]
    rows = block["rows"]
    unknown = any(r["gain_base"] is None or r["acquisition_base"] is None or r["transmission_base"] is None for r in rows)
    assert block["incomplete"] == unknown
    for r in rows:
        if r["over_sell"]:
            assert r["gain_base"] is None and r["acquisition_base"] is None
    if not unknown:
        gains = sum(Decimal(str(r["gain_base"])) for r in rows if r["gain_base"] >= 0)
        losses = sum(-Decimal(str(r["gain_base"])) for r in rows if r["gain_base"] < 0)
        assert Decimal(str(block["0339_suma_ganancias"])) == gains
        assert Decimal(str(block["0340_suma_perdidas"])) == losses
    else:
        assert block["0339_suma_ganancias"] is None and block["0340_suma_perdidas"] is None
