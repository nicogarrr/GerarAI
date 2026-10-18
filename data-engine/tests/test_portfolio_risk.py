"""Tests unitarios de `app.valuation.portfolio_risk` (foto de riesgo).

Sin BD, sin red: pesos, concentracion y alertas sobre posiciones dadas.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.valuation.portfolio_risk import calculate_portfolio_risk


def _pos(ticker, value, sector="Tech", factor_tags=None):
    return {
        "ticker": ticker,
        "market_value": value,
        "sector": sector,
        "factor_tags": factor_tags or [],
    }


def test_pesos_top_y_exposiciones():
    positions = [
        _pos("AAA", 50.0, "Tech", ["momentum"]),
        _pos("BBB", 30.0, "Fin", ["pre_fcf"]),
        _pos("CCC", 10.0, "Tech", ["momentum", "quality"]),
    ]
    result = calculate_portfolio_risk(positions, [{"currency": "USD", "balance": 10.0}])

    assert result["equity_value"] == 90.0
    assert result["total_value"] == 100.0
    assert result["cash"] == {"USD": 10.0}
    assert result["top_1_weight"] == 0.5
    assert result["top_5_weight"] == pytest.approx(0.9)
    assert result["sector_exposure"] == {"Fin": 0.3, "Tech": 0.6}
    assert result["factor_exposure"] == {"momentum": 0.6, "pre_fcf": 0.3, "quality": 0.1}
    assert result["trace"]["method"] == "portfolio_risk_snapshot"
    # Posiciones ordenadas de mayor a menor peso.
    assert [row["ticker"] for row in result["positions"]] == ["AAA", "BBB", "CCC"]


def test_alerta_concentracion_mayor_del_20_por_ciento():
    result = calculate_portfolio_risk([_pos("AAA", 50.0)], [{"currency": "USD", "balance": 50.0}])
    alertas = [a for a in result["alerts"] if a["severity"] == "high" and a["ticker"] == "AAA"]
    assert len(alertas) == 1
    assert alertas[0]["threshold"] == 0.20
    assert alertas[0]["metric_value"] == 0.5


def test_sin_alerta_en_el_borde_exacto_del_20_por_ciento():
    """weight == 0.20 no dispara (> estricto)."""
    result = calculate_portfolio_risk([_pos("AAA", 20.0)], [{"currency": "USD", "balance": 80.0}])
    assert result["alerts"] == []
    assert result["positions"][0]["weight"] == 0.20


def test_alerta_pre_fcf_por_encima_del_10_por_ciento():
    result = calculate_portfolio_risk(
        [_pos("AAA", 15.0, factor_tags=["pre_fcf"])], [{"currency": "USD", "balance": 85.0}]
    )
    alertas = [a for a in result["alerts"] if a["severity"] == "medium"]
    assert len(alertas) == 1
    assert "pre-FCF" in alertas[0]["message"]
    assert alertas[0]["threshold"] == 0.10


def test_pre_fcf_en_el_borde_10_por_ciento_no_alerta():
    result = calculate_portfolio_risk(
        [_pos("AAA", 10.0, factor_tags=["pre_fcf"])], [{"currency": "USD", "balance": 90.0}]
    )
    assert result["alerts"] == []


def test_alerta_caja_negativa():
    result = calculate_portfolio_risk(
        [], [{"currency": "EUR", "balance": -5.0}, {"currency": "USD", "balance": 10.0}]
    )
    assert result["cash"] == {"EUR": -5.0, "USD": 10.0}
    alertas = [a for a in result["alerts"] if "El saldo de caja en EUR es negativo" in a["message"]]
    assert len(alertas) == 1
    assert alertas[0]["severity"] == "high"
    assert alertas[0]["ticker"] is None


def test_portfolio_vacio_no_divide_entre_cero():
    result = calculate_portfolio_risk([], [])
    assert result["total_value"] == 0
    assert result["equity_value"] == 0
    assert result["top_1_weight"] == 0
    assert result["top_5_weight"] == 0
    assert result["positions"] == []
    assert result["alerts"] == []


def test_valores_de_mercado_cero_no_dividen_entre_cero():
    result = calculate_portfolio_risk([_pos("AAA", 0.0)], [{"currency": "USD", "balance": 0.0}])
    assert result["total_value"] == 0
    assert result["positions"][0]["weight"] == 0
    assert result["alerts"] == []


def test_acepta_decimals_de_sqlalchemy():
    positions = [_pos("AAA", Decimal("60.00"), factor_tags=["quality"])]
    result = calculate_portfolio_risk(positions, [{"currency": "USD", "balance": Decimal("40.00")}])
    assert result["total_value"] == 100.0
    assert result["positions"][0]["weight"] == 0.6
    assert result["factor_exposure"] == {"quality": 0.6}


def test_valores_none_o_faltantes_se_tratan_como_cero():
    positions = [{"ticker": "AAA", "market_value": None, "sector": "Tech"}]
    result = calculate_portfolio_risk(positions, [{"currency": "USD", "balance": None}])
    assert result["equity_value"] == 0.0
    assert result["total_value"] == 0.0
    assert result["positions"][0]["weight"] == 0


def test_pesos_de_posiciones_suman_la_fraccion_de_renta_variable():
    positions = [_pos("AAA", 25.0), _pos("BBB", 25.0), _pos("CCC", 25.0)]
    result = calculate_portfolio_risk(positions, [{"currency": "USD", "balance": 25.0}])
    # El efectivo es el 25% del total: las posiciones suman el 75% restante.
    assert sum(row["weight"] for row in result["positions"]) == pytest.approx(0.75)
    assert result["top_5_weight"] == pytest.approx(0.75)


def test_top_5_acota_a_las_cinco_primeras():
    positions = [_pos(f"T{i}", 10.0 + i) for i in range(8)]
    result = calculate_portfolio_risk(positions, [])
    assert len(result["positions"]) == 8
    assert result["top_5_weight"] == pytest.approx(sum(row["weight"] for row in result["positions"][:5]))


def test_cartera_totalmente_negativa_no_rompe():
    """Borde: equity negativo -> pesos negativos, sin excepciones."""
    result = calculate_portfolio_risk([_pos("AAA", -100.0)], [{"currency": "USD", "balance": 50.0}])
    assert result["total_value"] == -50.0
    assert result["positions"][0]["weight"] == pytest.approx(2.0)


def test_mensajes_de_alerta_en_espanol():
    positions = [
        _pos("AAA", 60.0, "Tech", ["pre_fcf"]),
        _pos("BBB", 30.0),
    ]
    result = calculate_portfolio_risk(positions, [{"currency": "USD", "balance": -5.0}])

    mensajes = [a["message"] for a in result["alerts"]]
    assert "AAA supera el 20 % de peso en la cartera" in mensajes
    assert "AAA es pre-FCF y supera el 10 % de peso en la cartera" in mensajes
    assert "El saldo de caja en USD es negativo" in mensajes
    assert not any(" exceeds " in m or " is negative" in m for m in mensajes)


def test_caja_negativa_pesa_sobre_valor_bruto_y_nunca_pasa_de_100():
    positions = [_pos("AAA", 60.0, "Tech"), _pos("BBB", 40.0, "Fin")]
    result = calculate_portfolio_risk(positions, [{"currency": "EUR", "balance": -70.0}])
    assert result["total_value"] == 30.0
    assert result["weight_basis"] == "gross_equity"
    assert result["top_1_weight"] == 0.6
    assert result["top_5_weight"] == pytest.approx(1.0)
    assert sum(result["sector_exposure"].values()) == pytest.approx(1.0)
    assert any("negativo" in a["message"] for a in result["alerts"])


def test_caja_positiva_mantiene_pesos_sobre_total_con_caja():
    result = calculate_portfolio_risk([_pos("AAA", 50.0)], [{"currency": "USD", "balance": 50.0}])
    assert result["weight_basis"] == "total_with_cash"
    assert result["top_1_weight"] == 0.5
