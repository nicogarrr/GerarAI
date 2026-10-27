"""Beneficio del propietario (Buffett, carta de Berkshire Hathaway de 1986).

OE = beneficio neto + D&A + ΔCC(signo de flujo de caja) − |capex de mantenimiento|

Convención de signos que fijan estos tests:
* capex se guarda NEGATIVO (salida de caja); se resta su valor absoluto.
* ``change_in_working_capital`` va en signo de flujo de caja: negativo cuando
  el circulante absorbe caja. FMP ``changeInWorkingCapital`` ya viene así; el
  concepto SEC ``IncreaseDecreaseInOperatingCapital`` viene al revés y la
  ingesta lo niega.

Los valores esperados son literales calculados a mano, con la cuenta al lado.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.financial_ingestion_service import (
    CASH_FLOW_METRICS,
    SEC_METRIC_MAP,
    _merge_for_metric,
)
from app.services.long_term_model_service import LongTermModelService
from app.services.owner_earnings import (
    MAINTENANCE_RULE_ESTIMATED,
    MAINTENANCE_RULE_REPORTED,
    owner_earnings,
)

# --- Fórmula pura -----------------------------------------------------------


def test_ejemplo_de_referencia_con_capex_de_mantenimiento_publicado():
    # 100 (BN) + 30 (D&A) + (−10) (ΔCC: el circulante absorbe 10) − |−40| = 80
    result = owner_earnings(
        net_income=Decimal("100"),
        depreciation_amortization=Decimal("30"),
        change_in_working_capital=Decimal("-10"),
        maintenance_capex=Decimal("-40"),
    )
    assert result is not None
    assert result.value == Decimal("80")
    assert result.maintenance_capex == Decimal("40")
    assert result.maintenance_capex_rule == MAINTENANCE_RULE_REPORTED


def test_capex_de_mantenimiento_positivo_o_negativo_da_lo_mismo():
    # El capex nunca se suma dos veces: |40| = |−40| -> 80 en ambos casos.
    kwargs = dict(
        net_income=Decimal("100"),
        depreciation_amortization=Decimal("30"),
        change_in_working_capital=Decimal("-10"),
    )
    positive = owner_earnings(**kwargs, maintenance_capex=Decimal("40"))
    negative = owner_earnings(**kwargs, maintenance_capex=Decimal("-40"))
    assert positive is not None and negative is not None
    assert positive.value == negative.value == Decimal("80")


def test_circulante_que_libera_caja_suma():
    # ΔCC = +10 (el circulante baja y libera caja): 100 + 30 + 10 − 40 = 100
    result = owner_earnings(
        net_income=Decimal("100"),
        depreciation_amortization=Decimal("30"),
        change_in_working_capital=Decimal("10"),
        maintenance_capex=Decimal("-40"),
    )
    assert result is not None
    assert result.value == Decimal("100")


def test_sin_desglose_de_mantenimiento_se_estima_con_la_regla_declarada():
    # mantenimiento = min(|−40|, 30) = 30; crecimiento = 40 − 30 = 10
    # OE = 100 + 30 + (−10) − 30 = 90
    result = owner_earnings(
        net_income=Decimal("100"),
        depreciation_amortization=Decimal("30"),
        change_in_working_capital=Decimal("-10"),
        capital_expenditure=Decimal("-40"),
    )
    assert result is not None
    assert result.value == Decimal("90")
    assert result.maintenance_capex == Decimal("30")
    assert result.estimated_growth_capex == Decimal("10")
    assert result.maintenance_capex_rule == MAINTENANCE_RULE_ESTIMATED


def test_sin_capex_ni_mantenimiento_no_hay_numero():
    assert (
        owner_earnings(
            net_income=Decimal("100"),
            depreciation_amortization=Decimal("30"),
            change_in_working_capital=Decimal("-10"),
        )
        is None
    )


# --- Modelo a largo plazo -----------------------------------------------------


def _fact(value, fact_id="f"):
    return SimpleNamespace(value=value, id=fact_id, period="FY2024")


def _service():
    svc = LongTermModelService.__new__(LongTermModelService)
    svc._annual_by_year = lambda facts: {2024: facts[0]} if facts else {}
    return svc


def _cache(**overrides):
    base = {
        "net_income": [_fact(100, "ni")],
        "depreciation_amortization": [_fact(30, "da")],
        "depreciation_and_amortization": [],
        "capital_expenditure": [_fact(-40, "capex")],
        "maintenance_capex": [],
        "change_in_working_capital": [_fact(-10, "wc")],
    }
    base.update(overrides)
    return base


def test_modelo_largo_plazo_calcula_oe_con_capex_de_mantenimiento_publicado():
    # 100 + 30 + (−10) − |−40| = 80
    result = _service()._owner_earnings(_cache(maintenance_capex=[_fact(-40, "mc")]), 2024)
    assert result["status"] == "ok"
    assert result["value"] == 80.0
    assert result["maintenance_capex_rule"] == MAINTENANCE_RULE_REPORTED
    assert set(result["source_fact_ids"]) == {"ni", "da", "mc", "wc", "capex"}


def test_modelo_largo_plazo_estima_el_mantenimiento_y_lo_declara():
    # min(40, 30) = 30 -> 100 + 30 − 10 − 30 = 90
    result = _service()._owner_earnings(_cache(), 2024)
    assert result["status"] == "ok"
    assert result["value"] == 90.0
    assert result["maintenance_capex"] == 30.0
    assert result["maintenance_capex_rule"] == MAINTENANCE_RULE_ESTIMATED


def test_modelo_largo_plazo_sin_circulante_es_insuficiente_y_lo_nombra():
    # Sin ΔCC no se asume 0: sería afirmar que el circulante no se movió.
    result = _service()._owner_earnings(_cache(change_in_working_capital=[]), 2024)
    assert result["status"] == "insufficient_data"
    assert result["value"] is None
    assert result["missing_inputs"] == ["change_in_working_capital"]


def test_modelo_largo_plazo_sin_capex_ni_mantenimiento_es_insuficiente():
    result = _service()._owner_earnings(_cache(capital_expenditure=[]), 2024)
    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["maintenance_capex_or_capital_expenditure"]


# --- Ingesta: el signo del circulante -----------------------------------------


def test_fmp_ingesta_change_in_working_capital_del_estado_de_flujos():
    assert ("change_in_working_capital", "changeInWorkingCapital", "USD") in CASH_FLOW_METRICS


def test_sec_mapea_el_concepto_de_circulante_operativo():
    concepts = {metric: names for metric, names, _unit in SEC_METRIC_MAP}
    assert concepts["change_in_working_capital"] == ["IncreaseDecreaseInOperatingCapital"]


def test_sec_niega_increase_decrease_in_operating_capital():
    # IncreaseDecreaseInOperatingCapital = +25 significa que el circulante
    # SUBIÓ 25 (caja consumida). En signo de flujo de caja eso es −25.
    entry = {"end": "2024-12-31", "filed": "2025-02-01", "val": 25, "fy": 2024}
    merged = _merge_for_metric(
        {"IncreaseDecreaseInOperatingCapital": {"2024-12-31": entry}},
        "change_in_working_capital",
    )
    assert merged["2024-12-31"]["val"] == -25
    # El dato crudo del companyfacts no se toca.
    assert entry["val"] == 25


def test_sec_otras_metricas_no_cambian_de_signo():
    entry = {"end": "2024-12-31", "filed": "2025-02-01", "val": 25}
    merged = _merge_for_metric({"NetIncomeLoss": {"2024-12-31": entry}}, "net_income")
    assert merged["2024-12-31"]["val"] == 25
