"""Tests dorados y de propiedades de cartera y fiscalidad (auditoría de
fórmulas, fase 2, área «portfolio»).

Cada test dorado reproduce el ``numeric_check`` de la auditoría
(GerarAI_formulas.pdf) con el cálculo a mano y la fuente en el docstring.
Las propiedades usan ``random`` con semilla fija (sin dependencias nuevas).
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.historical_stress_service import calculate_window
from app.services.paper_calibration_service import calibration
from app.services.paper_trading_service import pnl
from app.services.tax_irpf_filing import calculate_savings_tax
from app.services.tax_modelo720_file import _num
from app.services.tearsheet_service import compute_metrics
from app.valuation.portfolio_risk import calculate_portfolio_risk

SEEDS = range(200)


# --------------------------------------------------------------------------
# irpf_escala_ahorro — art. 66 y 76 LIRPF (escala del ahorro 2025)
# --------------------------------------------------------------------------


def test_golden_escala_ahorro_10000():
    """B = 10.000 € (2025): 6.000·19 % + 4.000·21 % = 1.140 + 840 = 1.980 €."""
    assert calculate_savings_tax(Decimal("10000"), 2025) == Decimal("1980")


def test_golden_escala_ahorro_350000():
    """B = 350.000 € (2025): 1.140 + 9.240 (44.000·21 %) + 34.500 (150.000·23 %)
    + 27.000 (100.000·27 %) + 15.000 (50.000·30 %) = 86.880 €."""
    assert calculate_savings_tax(Decimal("350000"), 2025) == Decimal("86880")


@pytest.mark.parametrize("seed", SEEDS)
def test_prop_escala_ahorro_monotona_y_tipo_marginal_acotado(seed):
    """Propiedad: la cuota no baja al subir la base y el tipo marginal está
    entre el 19 % y el 30 % (tramos 2025)."""
    rng = random.Random(seed)
    low = Decimal(str(round(rng.uniform(0, 400_000), 2)))
    delta = Decimal(str(round(rng.uniform(0.01, 50_000), 2)))
    t_low = calculate_savings_tax(low, 2025)
    t_high = calculate_savings_tax(low + delta, 2025)
    marginal = (t_high - t_low) / delta
    assert Decimal("0.19") - Decimal("1e-9") <= marginal <= Decimal("0.30") + Decimal("1e-9")


def test_edge_escala_ahorro_base_negativa_o_cero():
    assert calculate_savings_tax(Decimal("0"), 2025) == Decimal("0")
    assert calculate_savings_tax(Decimal("-500"), 2025) == Decimal("0")


# --------------------------------------------------------------------------
# m720_formato_numerico — Orden HAP/72/2013, diseño de registro (12+2 posiciones)
# --------------------------------------------------------------------------


def test_golden_m720_formato_numerico():
    """1.234,565 € con 12+2 posiciones -> 1.234,57 -> '00000000123457' (14 bytes);
    100 % de participación con 3+2 -> '10000'."""
    assert _num(Decimal("1234.565"), 12, 2) == "00000000123457"
    assert _num(100, 3, 2) == "10000"


@pytest.mark.parametrize("seed", SEEDS)
def test_prop_m720_ancho_fijo_y_valor_recuperable(seed):
    """Propiedad: el campo siempre mide int_len + dec_len y, leído como
    céntimos, devuelve el importe redondeado a 2 decimales."""
    rng = random.Random(seed)
    value = Decimal(str(round(rng.uniform(0, 9_999_999), 2)))
    field = _num(value, 12, 2)
    assert len(field) == 14 and field.isdigit()
    assert Decimal(field) / 100 == value


# --------------------------------------------------------------------------
# sortino_downside_dev / tearsheet_sharpe / tearsheet_mdd — Sortino & Price
# (1994); Sharpe (1966); máximo drawdown con el patrimonio inicial como pico
# --------------------------------------------------------------------------


def test_golden_sortino_un_unico_periodo_negativo():
    """[0,02; −0,01; 0,03; 0,01] mensual: media 0,0125; DD = √(0,01²/4) = 0,005;
    Sortino = 0,0125/0,005·√12 = 2,5·3,4641 = 8,660."""
    result = compute_metrics([0.02, -0.01, 0.03, 0.01], periods=12)
    assert result["sortino"] == pytest.approx(2.5 * math.sqrt(12))


def test_golden_mdd_precios_100_120_90_130():
    """100 -> 120 -> 90 -> 130: pico 120, valle 90 -> MDD = 90/120 − 1 = −25 %."""
    returns = [120 / 100 - 1, 90 / 120 - 1, 130 / 90 - 1]
    result = compute_metrics(returns, periods=252)
    assert result["max_drawdown"] == pytest.approx(-0.25)
    assert result["cumulative_return"] == pytest.approx(0.30)


@pytest.mark.parametrize("seed", SEEDS)
def test_prop_sharpe_y_sortino_invariantes_a_escala(seed):
    """Propiedad (rf = 0): multiplicar todos los retornos por k > 0 no cambia
    Sharpe ni Sortino; el MDD siempre está en [−1, 0]."""
    rng = random.Random(seed)
    returns = [rng.uniform(-0.05, 0.05) for _ in range(rng.randint(5, 60))]
    if not any(r < 0 for r in returns):
        returns[0] = -0.01
    k = rng.uniform(0.1, 0.9)
    base = compute_metrics(returns)
    scaled = compute_metrics([r * k for r in returns])
    assert scaled["sharpe"] == pytest.approx(base["sharpe"], rel=1e-9)
    assert scaled["sortino"] == pytest.approx(base["sortino"], rel=1e-9)
    assert -1.0 <= base["max_drawdown"] <= 0.0


def test_edge_tearsheet_pocas_observaciones_es_nd():
    assert compute_metrics([0.01])["status"] == "insufficient_data"
    assert compute_metrics([0.01, 0.02])["sortino"] is None  # sin periodos a la baja


# --------------------------------------------------------------------------
# risk_weights — pesos sobre el total (o bruto con caja negativa)
# --------------------------------------------------------------------------


def _positions():
    return [
        {"ticker": "AAA", "sector": "Tech", "market_value": 60},
        {"ticker": "BBB", "sector": "Salud", "market_value": 40},
    ]


def test_golden_pesos_con_caja_positiva_y_negativa():
    """Posiciones 60 + 40 y caja 100 -> pesos 60/200 = 30 % y 40/200 = 20 %.
    Con caja −50 (margen) se pesa sobre el bruto de posiciones: 60 % y 40 %."""
    rows = calculate_portfolio_risk(_positions(), [{"currency": "EUR", "balance": 100}])
    weights = {row["ticker"]: row["weight"] for row in rows["positions"]}
    assert weights == {"AAA": pytest.approx(0.30), "BBB": pytest.approx(0.20)}
    rows = calculate_portfolio_risk(_positions(), [{"currency": "EUR", "balance": -50}])
    weights = {row["ticker"]: row["weight"] for row in rows["positions"]}
    assert weights == {"AAA": pytest.approx(0.60), "BBB": pytest.approx(0.40)}


@pytest.mark.parametrize("seed", SEEDS)
def test_prop_pesos_suman_uno_con_la_caja(seed):
    """Propiedad: con caja ≥ 0, Σ pesos de posiciones + caja/total = 1; con
    caja < 0, Σ pesos de posiciones = 1 (base bruta)."""
    rng = random.Random(seed)
    positions = [
        {"ticker": f"T{i}", "sector": "S", "market_value": rng.uniform(1, 1000)}
        for i in range(rng.randint(1, 8))
    ]
    cash = rng.uniform(-200, 2000)
    rows = calculate_portfolio_risk(positions, [{"currency": "EUR", "balance": cash}])
    total_positions = sum(p["market_value"] for p in positions)
    weight_sum = sum(row["weight"] for row in rows["positions"])
    if cash >= 0:
        assert weight_sum + cash / (total_positions + cash) == pytest.approx(1.0)
    else:
        assert weight_sum == pytest.approx(1.0)


# --------------------------------------------------------------------------
# paper_pnl_hit / paper_brier — P&L con signo por dirección; Brier (1950)
# --------------------------------------------------------------------------


def _trade(direction, entry, exit_price, conviction=Decimal("0.5"), quantity=Decimal("10")):
    return SimpleNamespace(
        author="LLM", status="closed", direction=direction, entry_price=entry,
        exit_price=exit_price, quantity=quantity, conviction=conviction,
        horizon="short", close_reason="target", currency="USD", corporate_action_warning=None,
    )


def test_golden_paper_pnl_corto_y_largo():
    """Corto 10 @ 50 con salida 45: (45 − 50)·10·(−1) = +50; largo: −50."""
    assert pnl(_trade("short", Decimal("50"), None), Decimal("45")) == Decimal("50")
    assert pnl(_trade("long", Decimal("50"), None), Decimal("45")) == Decimal("-50")


@pytest.mark.parametrize("seed", SEEDS)
def test_prop_paper_pnl_antisimetrico(seed):
    """Propiedad: P&L(largo) = −P&L(corto) con la misma entrada y salida."""
    rng = random.Random(seed)
    entry = Decimal(str(round(rng.uniform(1, 500), 2)))
    exit_price = Decimal(str(round(rng.uniform(1, 500), 2)))
    long_pnl = pnl(_trade("long", entry, None), exit_price)
    short_pnl = pnl(_trade("short", entry, None), exit_price)
    assert long_pnl == -short_pnl


def test_golden_brier_y_referencia():
    """p = (0,8; 0,6; 0,3), y = (1; 0; 0): Brier = (0,04 + 0,36 + 0,09)/3 = 0,1633;
    ȳ = 1/3 -> referencia sin información = 1/3·2/3 = 0,2222 (Brier, 1950)."""
    rows = [
        _trade("long", Decimal("50"), Decimal("55"), conviction=Decimal("0.8")),
        _trade("long", Decimal("50"), Decimal("45"), conviction=Decimal("0.6")),
        _trade("long", Decimal("50"), Decimal("45"), conviction=Decimal("0.3")),
    ]
    out = calibration(rows)
    assert out["brier"] == pytest.approx(0.49 / 3)
    assert out["brier_referencia_sin_informacion"] == pytest.approx(2 / 9)


# --------------------------------------------------------------------------
# stress_buy_and_hold — MDD dentro del año, recuperación al primer cierre ≥ pico
# --------------------------------------------------------------------------


def test_golden_estres_100_120_90_130():
    """Base 100 (31-dic) -> 120 -> 90 -> 130 a lo largo de 2022:
    pico 120, valle 90 -> MDD = 90/120 − 1 = −25 %; R = 130/100 − 1 = +30 %;
    recuperación el primer día que cierra ≥ 120."""
    prices = {date(2021, 12, 31): 100.0}
    day = date(2022, 1, 3)
    path = [100 + 20 * i / 60 for i in range(1, 61)]        # sube a 120
    path += [120 - 30 * i / 60 for i in range(1, 61)]       # cae a 90
    path += [90 + 40 * i / 140 for i in range(1, 141)]      # sube a 130
    for value in path:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        prices[day] = value
        day += timedelta(days=1)
    last = max(prices)
    while last < date(2022, 12, 30):  # completa hasta fin de año a 130
        last += timedelta(days=1)
        if last.weekday() < 5:
            prices[last] = 130.0
    result = calculate_window(prices, 2022)
    assert result["status"] == "calculated"
    assert result["max_drawdown"] == pytest.approx(-0.25)
    assert result["return"] == pytest.approx(0.30)
    assert result["recovery_status"] == "recovered"
    assert prices[date.fromisoformat(result["recovery_date"])] >= 120.0
