"""Tests unitarios de `app.valuation.funding_gap` (dilucion por hueco de financiacion).

Sin BD, sin red: se construye un `FinancialSnapshot` con hechos dobles (solo se
lee `.value`), nunca se toca SQLAlchemy ni la red.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.valuation.dilution_model import DilutionInput, run_dilution
from app.valuation.financial_snapshot import FinancialSnapshot
from app.valuation.funding_gap import FundingGapResult, estimate_funding_gap


def _snapshot(**metrics) -> FinancialSnapshot:
    return FinancialSnapshot(
        facts={name: SimpleNamespace(value=value) for name, value in metrics.items() if value is not None}
    )


def _snapshot_completo(**overrides) -> FinancialSnapshot:
    base = dict(
        cash_and_equivalents=100.0,
        operating_cash_flow=-50.0,
        capital_expenditure=-30.0,
        shares_diluted=1000.0,
    )
    base.update(overrides)
    return _snapshot(**base)


def test_caso_base_gap_estimado_y_dilucion_calculada():
    result = estimate_funding_gap(
        _snapshot_completo(), current_price=10.0, value_per_share=8.0
    )
    assert isinstance(result, FundingGapResult)
    # capex_need = 30*2 = 60; burn = 50*2 = 100; buffer 50; caja 100 -> gap 110.
    assert result.planned_capex == 30.0
    assert result.burn_proxy == 100.0
    assert result.funding_gap == pytest.approx(110.0)
    assert result.status == "estimated"
    assert result.missing_inputs == []
    assert result.dilution is not None
    # Emision a precio*0.85 = 8.5.
    assert result.dilution["new_shares"] == pytest.approx(110.0 / 8.5)
    esperado = run_dilution(
        DilutionInput(
            current_shares=1000.0,
            new_capital_needed=110.0,
            issuance_price=8.5,
            current_value_per_share=8.0,
        )
    )
    assert result.dilution["diluted_value_per_share"] == pytest.approx(
        esperado["diluted_value_per_share"]
    )


def test_sin_caja_es_incompleto():
    result = estimate_funding_gap(
        _snapshot(operating_cash_flow=-10.0), current_price=5.0, value_per_share=5.0
    )
    assert result.status == "incomplete"
    assert result.funding_gap is None
    assert result.dilution is None
    assert "cash_and_equivalents" in result.missing_inputs


def test_sin_capex_ni_ocf_es_incompleto():
    result = estimate_funding_gap(
        _snapshot(cash_and_equivalents=10.0), current_price=5.0, value_per_share=5.0
    )
    assert result.status == "incomplete"
    assert result.missing_inputs == ["capital_expenditure", "operating_cash_flow"]
    assert result.available_cash == 10.0


def test_snapshot_totalmente_vacio_reporta_los_dos_huecos():
    result = estimate_funding_gap(_snapshot(), current_price=5.0, value_per_share=5.0)
    assert result.status == "incomplete"
    assert result.missing_inputs == [
        "cash_and_equivalents",
        "capital_expenditure",
        "operating_cash_flow",
    ]


def test_capex_negativo_se_toma_en_absoluto():
    result = estimate_funding_gap(
        _snapshot_completo(capital_expenditure=-30.0), current_price=10.0, value_per_share=8.0
    )
    positivo = estimate_funding_gap(
        _snapshot_completo(capital_expenditure=30.0), current_price=10.0, value_per_share=8.0
    )
    assert result.planned_capex == 30.0
    assert positivo.planned_capex == 30.0
    assert result.funding_gap == positivo.funding_gap


def test_ocf_positivo_no_genera_burn():
    result = estimate_funding_gap(
        _snapshot_completo(operating_cash_flow=200.0, capital_expenditure=0.0),
        current_price=10.0,
        value_per_share=8.0,
    )
    assert result.burn_proxy == 0.0
    # capex_need 0 + burn 0 + buffer 50 - caja 100 -> sin hueco.
    assert result.funding_gap == 0.0
    assert result.status == "no_gap"
    assert result.dilution is None


def test_caja_suficiente_no_hueco():
    result = estimate_funding_gap(
        _snapshot_completo(cash_and_equivalents=10_000.0),
        current_price=10.0,
        value_per_share=8.0,
    )
    assert result.funding_gap == 0.0
    assert result.status == "no_gap"
    assert result.dilution is None


def test_solo_ocf_negativo_no_inventa_capex_cero():
    result = estimate_funding_gap(
        _snapshot(cash_and_equivalents=0.0, operating_cash_flow=-10.0),
        current_price=2.0,
        value_per_share=2.0,
    )
    assert result.status == "incomplete"
    assert result.planned_capex is None
    assert result.funding_gap is None
    assert result.missing_inputs == ["capital_expenditure"]


def test_buffer_minimo_configurable():
    result = estimate_funding_gap(
        _snapshot(cash_and_equivalents=0.0, operating_cash_flow=0.0, capital_expenditure=0.0),
        current_price=2.0,
        value_per_share=2.0,
        min_cash_buffer=250.0,
    )
    assert result.min_cash_buffer == 250.0
    assert result.funding_gap == pytest.approx(250.0)


def test_horizon_personalizable_cambia_el_burn():
    result = estimate_funding_gap(
        _snapshot_completo(),
        current_price=10.0,
        value_per_share=8.0,
        default_horizon_years=1.0,
    )
    assert result.burn_proxy == pytest.approx(50.0)
    assert result.funding_gap == pytest.approx(30.0 + 50.0 + 50.0 - 100.0)


def test_gap_cero_no_diluye_aunque_haya_datos():
    result = estimate_funding_gap(
        _snapshot_completo(cash_and_equivalents=10_000.0, operating_cash_flow=0.0),
        current_price=10.0,
        value_per_share=8.0,
    )
    assert result.funding_gap == 0.0
    assert result.dilution is None


def test_sin_shares_no_hay_dilucion():
    snapshot = _snapshot(
        cash_and_equivalents=100.0,
        operating_cash_flow=-50.0,
        capital_expenditure=-30.0,
    )
    result = estimate_funding_gap(snapshot, current_price=10.0, value_per_share=8.0)
    assert result.funding_gap == pytest.approx(110.0)
    assert result.dilution is None


def test_shares_cero_o_negativas_no_diluyen():
    for shares in (0.0, -100.0):
        result = estimate_funding_gap(
            _snapshot_completo(shares_diluted=shares),
            current_price=10.0,
            value_per_share=8.0,
        )
        assert result.dilution is None


def test_precio_cero_o_faltante_no_diluye():
    for price in (0.0, None, -5.0):
        result = estimate_funding_gap(
            _snapshot_completo(), current_price=price, value_per_share=8.0
        )
        assert result.dilution is None
        assert result.funding_gap == pytest.approx(110.0)


def test_value_per_share_faltante_no_diluye():
    result = estimate_funding_gap(
        _snapshot_completo(), current_price=10.0, value_per_share=None
    )
    assert result.dilution is None


def test_precio_muy_bajo_acota_el_precio_de_emision_al_suelo():
    """issuance_price = max(precio*0.85, 0.1): con precio ~0 no se divide por cero."""
    result = estimate_funding_gap(
        _snapshot_completo(cash_and_equivalents=0.0),
        current_price=0.01,
        value_per_share=0.01,
    )
    assert result.dilution is not None
    assert result.dilution["new_shares"] == pytest.approx(result.funding_gap / 0.1)


def test_caja_negativa_amplia_el_hueco():
    result = estimate_funding_gap(
        _snapshot_completo(cash_and_equivalents=-500.0),
        current_price=10.0,
        value_per_share=8.0,
    )
    assert result.available_cash == -500.0
    # 60 + 100 + 50 - (-500) = 710.
    assert result.funding_gap == pytest.approx(710.0)


@pytest.mark.parametrize("absent", ["capital_expenditure", "operating_cash_flow"])
def test_partial_burn_inputs_fail_closed(absent):
    result = estimate_funding_gap(_snapshot_completo(**{absent: None}), current_price=10, value_per_share=8)
    assert result.status == "incomplete"
    assert result.missing_inputs == [absent]
    assert result.funding_gap is None
    assert result.dilution is None


def test_burn_proxy_source_expone_origen_del_burn():
    result = estimate_funding_gap(_snapshot_completo(), current_price=10.0, value_per_share=8.0)
    assert result.burn_proxy_source == "operating_cash_flow"


def test_burn_proxy_source_no_se_inventa_en_resultado_incompleto():
    result = estimate_funding_gap(
        _snapshot_completo(operating_cash_flow=None), current_price=10.0, value_per_share=8.0
    )
    assert result.status == "incomplete"
    assert result.burn_proxy_source is None


def test_ocf_positivo_compensa_el_capex():
    """OCF positivo financia parte del capex: el hueco usa la quema neta (capex - OCF).

    Caja 100, OCF +20/año, capex 30/año, horizonte 2 años, colchón 50:
    quema neta = (30 - 20) * 2 = 20; hueco = max(20 + 50 - 100, 0) = 0.
    Antes se ignoraba el OCF positivo y salía (30 * 2) + 50 - 100 = 10.
    """
    result = estimate_funding_gap(
        _snapshot_completo(operating_cash_flow=20.0), current_price=10.0, value_per_share=8.0
    )
    assert result.funding_gap == pytest.approx(0.0)
    assert result.dilution is None


def test_ocf_positivo_mayor_que_capex_solo_deja_el_colchon():
    """FCF positivo (OCF 80 > capex 30) y sin caja: solo queda el colchón mínimo (50)."""
    result = estimate_funding_gap(
        _snapshot_completo(cash_and_equivalents=0.0, operating_cash_flow=80.0),
        current_price=10.0,
        value_per_share=8.0,
    )
    assert result.funding_gap == pytest.approx(50.0)


def test_ocf_positivo_menor_que_capex_reduce_el_hueco():
    """Caja 0, OCF +10, capex 30: (30 - 10) * 2 + 50 = 90 (antes 110)."""
    result = estimate_funding_gap(
        _snapshot_completo(cash_and_equivalents=0.0, operating_cash_flow=10.0),
        current_price=10.0,
        value_per_share=8.0,
    )
    assert result.funding_gap == pytest.approx(90.0)
