"""Tests de helpers puros de app/services/market_regime_quant.py.

Beta pareada (sin forward-fill ni cierres sinteticos) y concentracion top-10
(fail-closed ante capitalizaciones incompletas o no fechadas).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import app.services.market_regime_quant as mrq


def _series(start: date, days: int, base: float = 100.0, drift: float = 0.001):
    return {start + timedelta(days=i): base * ((1 + drift) ** i) for i in range(days)}


def test_paired_beta_horizonte_no_soportado():
    with pytest.raises(ValueError, match="Horizonte no soportado"):
        mrq.paired_beta({}, {}, sessions=10)


def test_paired_beta_sin_datos_si_faltan_pares():
    asset = _series(date(2024, 1, 1), 30)
    benchmark = _series(date(2024, 1, 1), 30)
    out = mrq.paired_beta(asset, benchmark, sessions=63)
    assert out["status"] == "sin datos"
    assert out["paired_sessions"] < 63


def _volatile_series(start: date, days: int, base: float, multiplier: float = 1.0):
    """Serie con retornos oscilantes +-2% (multiplicados): varianza real, sin deriva constante."""
    values = {}
    price = base
    for i in range(days):
        values[start + timedelta(days=i)] = price
        r = 0.02 if i % 2 == 0 else -0.015
        price *= 1 + multiplier * r
    return values


def test_paired_beta_happy_path():
    start = date(2024, 1, 1)
    benchmark = _volatile_series(start, 70, 100.0)
    asset = _volatile_series(start, 70, 50.0, multiplier=2.0)  # retornos ~2x
    out = mrq.paired_beta(asset, benchmark, sessions=63)
    assert out["status"] == "disponible"
    assert out["sessions"] == 63
    assert abs(out["beta"] - 2.0) < 0.05
    assert "cov(" in out["method"]


def test_paired_beta_omite_sesiones_sin_cierre_pareado():
    start = date(2024, 1, 1)
    benchmark = _volatile_series(start, 70, 100.0)
    asset_full = _volatile_series(start, 70, 50.0, multiplier=2.0)
    # un dia ausente en el activo NO cuenta como retorno multi-dia: el par se
    # omite y el beta usa solo sesiones pareadas validas
    missing = start + timedelta(days=40)
    asset = {d: v for d, v in asset_full.items() if d != missing}
    out = mrq.paired_beta(asset, benchmark, sessions=63)
    assert out["status"] == "disponible"  # quedan 63+ pares validos
    # si faltan tantas que no llega a la ventana: sin datos
    asset2 = {d: v for i, (d, v) in enumerate(asset_full.items()) if i < 56}
    out2 = mrq.paired_beta(asset2, benchmark, sessions=63)
    assert out2["status"] == "sin datos"
    assert out2["paired_sessions"] < 63


def test_paired_beta_descarta_valores_no_positivos():
    start = date(2024, 1, 1)
    benchmark = _volatile_series(start, 70, 100.0)
    asset = _volatile_series(start, 70, 50.0, multiplier=2.0)
    for i in range(8, 12):  # 4 cierres invalidos: los pares afectados no cuentan
        asset[start + timedelta(days=i)] = 0.0
    out = mrq.paired_beta(asset, benchmark, sessions=63)
    assert out["status"] == "sin datos"


def test_paired_beta_varianza_nula_es_sin_datos():
    days = 70
    flat = {date(2024, 1, 1) + timedelta(days=i): 100.0 for i in range(days)}
    asset = _volatile_series(date(2024, 1, 1), days, 50.0)
    out = mrq.paired_beta(asset, flat, sessions=63)
    assert out == {"status": "sin datos", "reason": "varianza de benchmark nula"}


def _caps(symbols, as_of: date, cap: float = 100.0):
    return dict.fromkeys(symbols, (cap, "proveedor", as_of))


def test_top_ten_concentration_exige_universo_completo():
    out = mrq.top_ten_concentration({"A", "B"}, {}, date(2024, 6, 1))
    assert out == {"status": "sin datos", "reason": "universo de constituyentes incompleto"}


def test_top_ten_concentration_exige_caps_completas_fechadas_y_positivas():
    as_of = date(2024, 6, 1)
    symbols = {f"S{i}" for i in range(12)}
    # falta un constituyente en market_caps
    caps = _caps(symbols - {"S0"}, as_of)
    assert mrq.top_ten_concentration(symbols, caps, as_of)["status"] == "sin datos"
    # fecha distinta del corte
    caps2 = _caps(symbols, as_of)
    caps2["S0"] = (100.0, "proveedor", date(2024, 5, 31))
    assert mrq.top_ten_concentration(symbols, caps2, as_of)["status"] == "sin datos"
    # cap no positiva
    caps3 = _caps(symbols, as_of)
    caps3["S0"] = (0.0, "proveedor", as_of)
    assert mrq.top_ten_concentration(symbols, caps3, as_of)["status"] == "sin datos"
    # sin fuente declarada
    caps4 = _caps(symbols, as_of)
    caps4["S0"] = (100.0, "", as_of)
    assert mrq.top_ten_concentration(symbols, caps4, as_of)["status"] == "sin datos"


def test_top_ten_concentration_happy_path():
    as_of = date(2024, 6, 1)
    symbols = {f"S{i}" for i in range(20)}
    caps = {s: (float(100 - i), "proveedor", as_of) for i, s in enumerate(sorted(symbols))}
    out = mrq.top_ten_concentration(symbols, caps, as_of)
    assert out["status"] == "disponible"
    assert out["constituents"] == 20
    assert out["date"] == "2024-06-01"
    top10_sum = sum(100 - i for i in range(10))
    total = sum(100 - i for i in range(20))
    assert abs(out["fraction"] - top10_sum / total) < 1e-9
    assert out["leaders"][0] == "S0"
