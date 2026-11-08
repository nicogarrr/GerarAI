"""Motor de TIR para el accionista (tesis de nivel comité): cálculo puro y regla pre-registrada."""
from __future__ import annotations

import math

import pytest

from app.valuation import shareholder_irr as E
from app.valuation import shareholder_irr_rules as R


def _numantia_erf() -> E.StartingPoint:
    # Punto de partida de la tesis de Numantia sobre Eurofins (1-may-2026): 64 €, 176 M de acciones,
    # deuda neta 3.066 M€ tras MET Labs, híbrido 1.000 M€, EBITDA ajustado normalizado 1.601 M€.
    return E.StartingPoint(price=64.0, shares_diluted=176.0, revenue=7146.0, ebitda=1601.0, debt=3066.0,
                           hybrids=1000.0, currency="EUR")


def _drivers(**kw) -> E.Drivers:
    base = dict(organic_growth=0.05, organic_growth_late=0.045, mna_spend_pct_revenue=0.03, margin_target=0.24,
                cash_conversion=0.55, dividend_payout=0.2, buyback_payout=0.3, exit_multiple=11.0)
    base.update(kw)
    return E.Drivers(**base)


def test_punto_de_partida_reproduce_el_de_numantia():
    sp = _numantia_erf()
    assert sp.market_cap == pytest.approx(11264.0)
    assert sp.enterprise_value == pytest.approx(15330.0)
    assert sp.multiple == pytest.approx(9.575, abs=1e-3)  # «9,57x» en su tesis


def test_tir_de_flujos_conocidos():
    assert E.irr([-100.0, 0, 0, 0, 0, 100 * 1.1 ** 5]) == pytest.approx(0.10, abs=1e-9)
    assert E.irr([-100.0, 5, 5, 5, 5, 105]) == pytest.approx(0.05, abs=1e-9)


@pytest.mark.parametrize("kw", [{}, {"exit_multiple": 6.0}, {"organic_growth": -0.05, "organic_growth_late": -0.02},
                                {"buyback_payout": 0.0, "dividend_payout": 0.0}, {"mna_spend_pct_revenue": 0.0}])
def test_la_descomposicion_suma_exactamente_la_tir(kw):
    sp = _numantia_erf()
    for n, h in E.evaluate(sp, _drivers(**kw)).items():
        assert h.irr is not None
        assert sum(h.components.values()) == pytest.approx(h.irr, abs=1e-12), (n, h.components)
        assert set(h.components) == set(E.COMPONENTS)


def test_sin_palancas_la_tir_es_cero_y_no_hay_componentes():
    sp = E.StartingPoint(price=50.0, shares_diluted=100.0, revenue=1000.0, ebitda=200.0, debt=0.0)
    d = E.Drivers(organic_growth=0.0, organic_growth_late=0.0, cash_conversion=0.0, exit_multiple=sp.multiple or 0)
    h = E.evaluate(sp, d)[5]
    assert h.irr == pytest.approx(0.0, abs=1e-9)
    assert all(abs(v) < 1e-9 for v in h.components.values())


def test_solo_cambio_de_multiplo_va_entero_a_multiplo():
    sp = E.StartingPoint(price=50.0, shares_diluted=100.0, revenue=1000.0, ebitda=200.0)
    d = E.Drivers(organic_growth=0.0, organic_growth_late=0.0, cash_conversion=0.0, exit_multiple=50.0)  # 25x → 50x
    h = E.evaluate(sp, d)[5]
    assert h.irr == pytest.approx(2 ** (1 / 5) - 1, abs=1e-9)
    assert h.components["multiplo"] == pytest.approx(h.irr, abs=1e-12)


def test_recomprar_mas_barato_rinde_mas_por_recompras():
    sp = _numantia_erf()
    cheap = E.evaluate(sp, _drivers(exit_multiple=9.0, dividend_payout=0.0, buyback_payout=1.0))[10]
    dear = E.evaluate(sp, _drivers(exit_multiple=16.0, dividend_payout=0.0, buyback_payout=1.0))[10]
    assert cheap.components["recompras"] > dear.components["recompras"]


def test_patrimonio_negativo_usa_reparto_lineal_y_suma():
    sp = E.StartingPoint(price=5.0, shares_diluted=100.0, revenue=1000.0, ebitda=100.0, debt=900.0)
    h = E.evaluate(sp, E.Drivers(organic_growth=-0.2, organic_growth_late=-0.2, cash_conversion=0.0,
                                 exit_multiple=4.0))[5]
    assert h.exit_price == 0.0
    if h.irr is not None:
        assert sum(h.components.values()) == pytest.approx(h.irr, abs=1e-12)


def test_sensibilidad_crece_con_crecimiento_y_multiplo():
    sp = _numantia_erf()
    t = E.sensitivity(sp, _drivers(), [0.025, 0.045, 0.065], [9.0, 11.0, 13.0])
    for row in t:
        assert row == sorted(row)
    for col in zip(*t, strict=True):
        assert list(col) == sorted(col)


def test_valor_a_la_tasa_exigida_es_el_precio_que_iguala_la_tir():
    sp = _numantia_erf()
    d = _drivers()
    r10 = E.evaluate(sp, d)[10].irr
    assert E.value_at_rate(sp, d, r10) == pytest.approx(sp.price, rel=1e-6)


def test_base_pe_sin_deuda():
    sp = E.StartingPoint(price=40.0, shares_diluted=100.0, revenue=10000.0, ebitda=None, net_income=250.0,
                         debt=5000.0, basis="pe")
    assert sp.multiple == pytest.approx(16.0)
    h = E.evaluate(sp, E.Drivers(organic_growth=0.05, organic_growth_late=0.05, cash_conversion=0.5,
                                 dividend_payout=0.5, exit_multiple=16.0))[5]
    assert h.components["deuda"] == pytest.approx(0.0, abs=1e-12)
    assert sum(h.components.values()) == pytest.approx(h.irr, abs=1e-12)


def _hist() -> R.History:
    return R.History(years=[2021, 2022, 2023, 2024], revenue=[5000.0, 5600.0, 6000.0, 6400.0],
                     earnings=[1100.0, 1250.0, 1300.0, 1450.0], operating_cash_flow=[900.0, 1000.0, 1050.0, 1200.0],
                     capex=[-300.0, -320.0, -330.0, -350.0], dividends=[-100.0, -110.0, -120.0, -130.0],
                     buybacks=[0.0, -200.0, -100.0, -150.0], acquisitions=[-200.0, -250.0, -150.0, -300.0], sbc=20.0)


def test_regla_determinista_y_ordenada():
    sp = E.StartingPoint(price=60.0, shares_diluted=180.0, revenue=6400.0, ebitda=1450.0, debt=3000.0)
    a = R.build_scenarios(sp, _hist(), peer_multiples=[14.0, 16.0, 18.0])
    b = R.build_scenarios(sp, _hist(), peer_multiples=[18.0, 14.0, 16.0])
    assert a.drivers == b.drivers
    g = {k: d.organic_growth for k, d in a.drivers.items()}
    m = {k: d.exit_multiple for k, d in a.drivers.items()}
    assert g["bear"] < g["base"] < g["bull"]
    assert m["bear"] <= m["base"] <= m["bull"]
    assert m["base"] == pytest.approx(((sp.multiple or 0) + 16.0) / 2)
    assert a.trace["multiplo"]["n_comparables"] == 3
    # crecimiento: ½ histórico orgánico + ½ mediana de la tasa base de su tramo
    tr = a.trace["crecimiento"]
    assert g["base"] == pytest.approx(0.5 * tr["historico_organico"] + 0.5 * tr["tasa_base"]["p50"])
    # reparto: suma ≤ 100 % y política igual en los tres escenarios
    assert len({(d.dividend_payout, d.buyback_payout) for d in a.drivers.values()}) == 1


def test_sin_comparables_la_base_no_cambia_de_multiplo():
    sp = E.StartingPoint(price=60.0, shares_diluted=180.0, revenue=6400.0, ebitda=1450.0, debt=3000.0)
    s = R.build_scenarios(sp, _hist(), peer_multiples=[15.0])
    assert s.drivers["base"].exit_multiple == pytest.approx(sp.multiple or 0)
    assert any("comparables" in w for w in s.warnings)


def test_multiplo_de_partida_absurdo_no_se_proyecta():
    sp = E.StartingPoint(price=41.0, shares_diluted=2368.0, revenue=75100.0, ebitda=None, net_income=1307.0,
                         basis="pe")  # PER ~74x: beneficio contable que no representa al accionista
    with pytest.raises(ValueError, match="fuera del rango"):
        R.build_scenarios(sp, _hist())


def test_tasas_base_tienen_todos_los_tramos_y_recuento():
    assert {name for name, _, _ in R.BASE_RATE_BUCKETS} == set(R.BASE_RATES)
    for row in R.BASE_RATES.values():
        assert row["p25"] <= row["p50"] <= row["p75"] and row["n"] > 30


def test_probabilidades_solo_de_la_lista():
    assert R.probabilities("inventada") == ("simetrico", R.PROBABILITY_SETS["simetrico"])
    for probs in R.PROBABILITY_SETS.values():
        assert math.isclose(sum(probs.values()), 1.0)
