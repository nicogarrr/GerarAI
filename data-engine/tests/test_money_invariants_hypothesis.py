"""Invariantes de dinero, fiscal y DCA con Hypothesis (property-based testing).

Cada test documenta la invariante que protege. Nada aqui toca produccion:
todo son funciones puras del data-engine con datos sinteticos.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.fx_attribution import split_unrealized_pnl
from app.services.tax_irpf_filing import (
    _treaty_creditable,
    build_loss_compensation,
    calculate_savings_tax,
    savings_bands,
)
from app.services.tax_modelo720_service import Q4_MAX_GAP_DAYS, q4_average_detail
from app.services.tax_report_service import (
    _fifo_sort_key,
    cash_amount,
    replay_tax_fifo,
    withholding_cost,
)

C = Decimal
SLOW = settings(max_examples=120, deadline=None)
FAST = settings(max_examples=60, deadline=None)

# --- Estrategias base -------------------------------------------------------

_cents = st.integers(1, 10_000_000).map(lambda c: C(c) / 100)  # 0.01 .. 100k
_qty = st.integers(1, 50_000).map(lambda c: C(c) / 100)          # 0.01 .. 500 acciones
_price = st.integers(1, 2_000_000).map(lambda c: C(c) / 100)     # 0.01 .. 20k
_fee = st.integers(0, 500).map(lambda c: C(c) / 100)             # 0 .. 5
_years = st.integers(2007, 2030)


def _tx(action, qty, price, fees, day, txid, currency="EUR"):
    from types import SimpleNamespace

    return SimpleNamespace(
        action=action, quantity=qty, price=price, fees=fees,
        currency=currency, trade_date=day, id=txid, raw_payload={},
    )


@st.composite
def covered_sequences(draw):
    """Compras/ventas siempre cubiertas (sin venta en descubierto)."""
    currency = draw(st.sampled_from(["EUR", "USD"]))
    day = date(2023, 1, 2)
    holdings = C("0")
    ops = []
    for _ in range(draw(st.integers(1, 24))):
        day += timedelta(days=draw(st.integers(1, 4)))  # estrictamente creciente
        action = draw(st.sampled_from(["buy", "sell"] if holdings > 0 else ["buy"]))
        qty = draw(_qty)
        if action == "sell":
            qty = min(qty, holdings)
        price = draw(_price)
        fees = draw(_fee)
        ops.append((action, qty, price, fees, day, currency))
        holdings = holdings + qty if action == "buy" else holdings - qty
    return ops


def _rate_fn(currency, day):
    if currency == "EUR":
        return C("1")
    return C("1.05") + C(day.toordinal() % 23) / 100


# --- Escala del ahorro IRPF -------------------------------------------------

@given(income=st.decimals(min_value=C("-100000"), max_value=C("0"), places=2), year=_years)
@FAST
def test_savings_tax_no_positive_on_losses(income, year):
    """Bases <= 0 no tributan."""
    assert calculate_savings_tax(income, year) == C("0")


@given(income=_cents, year=_years)
@FAST
def test_savings_tax_bounded(income, year):
    """0 <= cuota <= base x tipo marginal maximo del ejercicio."""
    tax = calculate_savings_tax(income, year)
    top = max(rate for _, _, rate in savings_bands(year))
    assert C("0") <= tax <= income * top


@given(x=_cents, delta=st.integers(0, 5_000_000).map(lambda c: C(c) / 100), year=_years)
@FAST
def test_savings_tax_monotonic(x, delta, year):
    """La cuota nunca baja al subir la base."""
    assert calculate_savings_tax(x, year) <= calculate_savings_tax(x + delta, year)


@given(x=_cents, year=_years)
@FAST
def test_savings_tax_continuous(x, year):
    """Sin saltos: el tipo es marginal, la cuota es continua en los bordes de tramo."""
    eps = C("0.005")
    before = calculate_savings_tax(x - eps, year)
    after = calculate_savings_tax(x + eps, year)
    top = max(rate for _, _, rate in savings_bands(year))
    assert after - before <= 2 * eps * top + C("0.0001")


# --- Replay FIFO fiscal -----------------------------------------------------

@given(ops=covered_sequences())
@SLOW
def test_fifo_conservation_native(ops):
    """Ley de conservacion: coste de compras + perdidas bloqueadas creadas
    == coste consumido por ventas + coste y diferidos que quedan en lotes."""
    events = sorted(
        (_tx(a, q, p, f, d, i, c) for i, (a, q, p, f, d, c) in enumerate(ops)),
        key=_fifo_sort_key,
    )
    lots, year_sales = replay_tax_fifo(events, lambda c, d: C("1"), date(2000, 1, 1), date(2099, 1, 1))
    buy_cost = sum((q * p + f for a, q, p, f, d, c in ops if a == "buy"), C("0"))
    blocked_created = sum(
        (e["sale"]["blocked_qty"] * e["sale"]["loss_per_share"] for e in year_sales if e["sale"]),
        C("0"),
    )
    consumed = sum((e["cost_native"] for e in year_sales), C("0"))
    remaining = sum((lot["qty"] * lot["unit"] + lot["deferred"] for lot in lots), C("0"))
    tol = C("1e-9") + buy_cost * C("1e-12")
    assert abs(buy_cost + blocked_created - consumed - remaining) <= tol


@given(ops=covered_sequences())
@SLOW
def test_fifo_base_uses_native_gain_at_sale_fx(ops):
    """DGT: every sale converts its native cost and gain at its sale-date FX.

    Historical purchase-date EUR cost is not conserved across FX movements;
    native FIFO conservation is tested separately. Native deferred losses are
    part of native cost and must be converted at the later sale date as well.
    """
    events = sorted(
        (_tx(a, q, p, f, d, i, c) for i, (a, q, p, f, d, c) in enumerate(ops)),
        key=_fifo_sort_key,
    )
    _, sales = replay_tax_fifo(events, _rate_fn, date(2000, 1, 1), date(2099, 1, 1))
    for entry in sales:
        tx = entry["transaction"]
        rate = _rate_fn(tx.currency, tx.trade_date)
        expected_cost = entry["cost_native"] * rate
        expected_gain = entry["gain_native"] * rate
        tol = C("1e-9") + abs(expected_cost) * C("1e-12")
        assert abs(entry["cost_base"] - expected_cost) <= tol
        assert abs(entry["gain_base_raw"] - expected_gain) <= tol


@given(ops=covered_sequences())
@SLOW
def test_fifo_structural_invariants(ops):
    """Lotes y ventas sanos: cantidades y diferidos no negativos, bloqueo
    conserva la cantidad de la venta, y sin sobreventa si va cubierta."""
    events = sorted(
        (_tx(a, q, p, f, d, i, c) for i, (a, q, p, f, d, c) in enumerate(ops)),
        key=_fifo_sort_key,
    )
    lots, year_sales = replay_tax_fifo(events, _rate_fn, date(2000, 1, 1), date(2099, 1, 1))
    for lot in lots:
        assert lot["qty"] > 0
        assert lot["capacity"] >= 0
        assert lot["deferred"] >= 0
    for entry in year_sales:
        assert not entry["over_sell"]
        sale = entry["sale"]
        if sale is not None:
            assert sale["loss_per_share"] >= 0
            assert sale["blocked_qty"] + sale["qty_unblocked"] == entry["transaction"].quantity
            # Lo bloqueado nunca supera la perdida de la venta.
            assert sale["blocked_qty"] * sale["loss_per_share"] <= max(-entry["gain_native"], C("0")) + C("1e-9")


@given(qty=_qty, price=_price, extra=_qty)
@FAST
def test_fifo_oversell_marked(qty, price, extra):
    """Venta descubierta: el exceso sobre lo comprado se marca con su cantidad."""
    buy = _tx("buy", qty, price, C("0"), date(2025, 3, 3), 1)
    sell = _tx("sell", qty + extra, price, C("0"), date(2025, 3, 10), 2)
    _, sales = replay_tax_fifo([buy, sell], lambda c, d: C("1"), date(2000, 1, 1), date(2099, 1, 1))
    assert sales[0]["over_sell"]
    assert sales[0]["over_sell_quantity"] == extra


def test_fifo_wash_sale_defers_loss():
    """Compra 100@10, venta 100@8, recompra 100@8,5 en <2m: la perdida (200)
    se difiere a la base del lote recomprado; al vender @9 el resultado total
    computable es el economico (-150), no -350."""
    events = [
        _tx("buy", C("100"), C("10"), C("0"), date(2025, 1, 10), 1),
        _tx("sell", C("100"), C("8"), C("0"), date(2025, 2, 10), 2),
        _tx("buy", C("100"), C("8.5"), C("0"), date(2025, 3, 1), 3),
        _tx("sell", C("100"), C("9"), C("0"), date(2025, 6, 1), 4),
    ]
    _, sales = replay_tax_fifo(events, lambda c, d: C("1"), date(2000, 1, 1), date(2099, 1, 1))
    s1, s2 = sales
    assert s1["sale"] is not None and s1["sale"]["blocked_qty"] == C("100")
    computable1 = s1["gain_native"] + s1["sale"]["blocked_qty"] * s1["sale"]["loss_per_share"]
    assert computable1 == C("0")
    assert s2["cost_native"] == C("1050")  # 850 + 200 diferidos
    assert s2["gain_native"] == C("-150")


def test_fifo_repurchase_after_window_not_blocked():
    """Recompra fuera de los 2 meses: la perdida computa integra."""
    events = [
        _tx("buy", C("100"), C("10"), C("0"), date(2025, 1, 10), 1),
        _tx("sell", C("100"), C("8"), C("0"), date(2025, 2, 10), 2),
        _tx("buy", C("100"), C("8.5"), C("0"), date(2025, 6, 1), 3),
    ]
    _, sales = replay_tax_fifo(events, lambda c, d: C("1"), date(2000, 1, 1), date(2099, 1, 1))
    assert sales[0]["sale"] is None or sales[0]["sale"]["blocked_qty"] == C("0")


# --- Deduccion por doble imposicion (tope de convenio) ----------------------


def _payments_bucket(pairs):
    return {
        "ticker": "X",
        "payments": [
            {"type": kind, "date": day, "amount_base": amount}
            for kind, day, amount in pairs
        ],
    }


@given(
    n=st.integers(1, 6),
    data=st.data(),
)
@SLOW
def test_treaty_creditable_bounded(n, data):
    """Con pagos no negativos que concilian: 0 <= acreditable <=
    min(retenido total, tope de convenio sobre el bruto total)."""
    rate = C("0.15")
    pairs = []
    gross = C("0")
    withheld = C("0")
    for i in range(n):
        g = data.draw(_cents)
        w = data.draw(st.integers(0, 60).map(lambda c: g * C(c) / 100))
        day = f"2025-0{i + 1}-10"
        pairs.append(("dividend", day, g))
        pairs.append(("withholding", day, w))
        gross += g
        withheld += w
    result = _treaty_creditable(_payments_bucket(pairs), gross, withheld, rate)
    assert C("0") <= result <= min(withheld, gross * rate)


# --- Compensacion de perdidas (art. 49 LIRPF) --------------------------------

_prior_net = st.fixed_dictionaries(
    {
        "year": st.integers(0, 5),
        "net_gyp_base": st.decimals(min_value=C("-50000"), max_value=C("50000"), places=2),
        "net_rcm_base": st.one_of(
            st.none(),
            st.decimals(min_value=C("-5000"), max_value=C("20000"), places=2),
        ),
    }
)


@given(
    prior=st.lists(_prior_net, max_size=6),
    gyp=st.one_of(st.none(), st.decimals(min_value=C("-50000"), max_value=C("80000"), places=2)),
    rcm=st.one_of(st.none(), st.decimals(min_value=C("-5000"), max_value=C("30000"), places=2)),
    data=st.data(),
)
@SLOW
def test_loss_compensation_limits(prior, gyp, rcm, data):
    """El cruce contra rendimientos (0446 + arrastres) nunca supera el 25 %
    CONJUNTO del saldo positivo de rcm; la integracion en GyP nunca supera el
    saldo positivo del ano; y por ejercicio: aplicado + pendiente == inicial."""
    fy = 2025
    prior = [
        {**e, "year": fy - 6 + e["year"], "incomplete": data.draw(st.booleans())}
        for e in prior
    ]
    out = build_loss_compensation(prior, gyp, rcm, fy)
    cross_limit = max(C("0"), C(str(rcm))) * C("0.25") if rcm is not None else C("0")
    applied_cross = C(str(out["current_year_cross"]["applied_to_income_base"])) + C(
        str(out["applied_to_income_total_base"])
    )
    assert applied_cross <= cross_limit + C("0.02")
    if gyp is not None:
        assert C(str(out["applied_to_gains_total_base"])) <= max(C("0"), C(str(gyp))) + C("0.02")
    for item in out["prior_losses"]:
        start = C(str(item["pending_start_base"]))
        applied = C(str(item["applied_to_gains_base"])) + C(str(item["applied_to_income_base"]))
        remaining = C(str(item["remaining_base"]))
        assert start >= C("0") and remaining >= C("0")
        assert abs(start - applied - remaining) <= C("0.03")


@given(
    declared=st.dictionaries(
        st.integers(2015, 2030),
        st.decimals(min_value=C("0.01"), max_value=C("50000"), places=2),
        max_size=6,
    ),
    gyp=st.decimals(min_value=C("0"), max_value=C("80000"), places=2),
    rcm=st.decimals(min_value=C("0"), max_value=C("30000"), places=2),
)
@FAST
def test_loss_compensation_window_declared(declared, gyp, rcm):
    """Con saldos declarados (anexo C.3) solo entran los 4 ejercicios
    anteriores: el resto esta prescrito y no se arrastra."""
    fy = 2025
    out = build_loss_compensation([], gyp, rcm, fy, declared_pending=declared)
    for item in out["prior_losses"]:
        assert fy - 4 <= item["year"] <= fy - 1


# --- Modelo 720: saldo medio del 4T ------------------------------------------

@given(
    balances=st.lists(
        st.decimals(min_value=C("-100000"), max_value=C("500000"), places=2),
        min_size=1,
        max_size=12,
    ),
    fy=st.integers(2020, 2026),
)
@SLOW
def test_q4_average_bounds(balances, fy):
    """La media de saldos diarios del trimestre cae entre el min y el max
    observados; con saldo constante es exactamente ese saldo."""
    q_start = date(fy, 10, 1)
    points = [(q_start + timedelta(days=7 * i), b) for i, b in enumerate(balances)]
    detail = q4_average_detail(points, fy)
    if detail is None:
        return
    assert detail["observed_days"] + detail["carried_days"] == 92
    lo, hi = min(balances), max(balances)
    assert lo <= detail["average"] <= hi
    constant = q4_average_detail([(q_start, balances[0])], fy)
    assert constant is not None and constant["average"] == balances[0]


def test_q4_average_rejects_late_first_point():
    """Sin captura del 1/10 (ni anterior dentro del margen) no hay media: None."""
    fy = 2025
    late = date(fy, 10, 1) + timedelta(days=Q4_MAX_GAP_DAYS + 1)
    assert q4_average_detail([(late, C("100"))], fy) is None


# --- Atribucion FX de la G/P latente ----------------------------------------

@given(
    native=st.one_of(st.none(), st.decimals(min_value=C("-10000"), max_value=C("10000"), places=2)),
    base=st.one_of(st.none(), st.decimals(min_value=C("-10000"), max_value=C("10000"), places=2)),
    rate=st.one_of(st.none(), st.decimals(min_value=C("-2"), max_value=C("5"), places=4)),
)
@FAST
def test_fx_attribution_splits_exactly(native, base, rate):
    """efecto precio + efecto divisa == G/P en base; sin datos o tipo <= 0: (None, None)."""
    price_effect, fx_effect = split_unrealized_pnl(
        unrealized_native=native, unrealized_base=base, fx_rate_now=rate
    )
    if native is None or base is None or rate is None or rate <= 0:
        assert price_effect is None and fx_effect is None
    else:
        assert abs((price_effect + fx_effect) - float(base)) < 1e-6


# --- Convenciones de caja ----------------------------------------------------

@given(amount=st.decimals(min_value=C("-1000"), max_value=C("1000"), places=2))
@FAST
def test_withholding_sign_convention(amount):
    """IBKR firma la retencion en negativo (coste = -importe, reversiones restan);
    la entrada manual guarda el valor absoluto."""
    from types import SimpleNamespace

    broker = SimpleNamespace(price=amount, quantity=C("1"), raw_payload={"type": "Withholding Tax"})
    manual = SimpleNamespace(price=amount, quantity=C("1"), raw_payload={})
    assert withholding_cost(broker) == -amount
    assert withholding_cost(manual) == abs(amount)
    assert cash_amount(broker) == amount


# --- DCA (SOLO LECTURA: invariantes, los fallos se reportan, no se arreglan) --

from app.services.dca_backtest import irr_monthly  # noqa: E402
from app.services.dca_signal_engine import _buy_level, _rsi_series, _sma  # noqa: E402

_closes = st.lists(
    st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    min_size=0,
    max_size=80,
)


@given(closes=_closes, period=st.integers(2, 20))
@FAST
def test_dca_rsi_bounded(closes, period):
    """RSI siempre en [0, 100] (o None antes de tener ventana)."""
    for value in _rsi_series(closes, period):
        assert value is None or 0.0 <= value <= 100.0


@given(data=st.data(), months=st.integers(1, 30))
@FAST
def test_dca_sma_within_window(data, months):
    """La media simple cae dentro del rango de su ventana (indice valido)."""
    closes = data.draw(st.lists(st.floats(min_value=0.01, max_value=10000, allow_nan=False, allow_infinity=False), min_size=1, max_size=80), label="nonempty closes")
    i = data.draw(st.integers(0, len(closes) - 1), label="valid index")
    value = _sma(closes, i, months)
    if value is None:
        return
    window = closes[i + 1 - months : i + 1]
    assert min(window) <= value <= max(window)


@pytest.mark.xfail(
    reason=(
        "_sma devuelve 0.0 inventado con la ventana vacia (indice fuera de "
        "rango o serie vacia) en vez de None; el codigo DCA esta congelado "
        "(decision del propietario): riesgo latente documentado."
    ),
    strict=False,
)
def test_dca_sma_empty_window_returns_none():
    """Riesgo latente DCA (solo reporte): ventana vacia -> 0.0 fabricado."""
    assert _sma([], 0, 1) is None


@given(
    dd=st.floats(min_value=-0.5, max_value=1.5, allow_nan=False),
    thresholds=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False), min_size=1, max_size=4
    ).map(sorted),
)
@FAST
def test_dca_buy_level_monotonic(dd, thresholds):
    """Con umbrales ordenados, mas caida nunca baja el nivel de compra."""
    level = _buy_level(dd, thresholds)
    for t in thresholds:
        if dd >= t:
            assert level >= 2
    eps = 0.0001
    assert _buy_level(dd + eps, thresholds) >= level


@given(
    flows=st.lists(
        st.floats(min_value=-5000, max_value=5000, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=60,
    )
)
@SLOW
def test_dca_irr_is_npv_root(flows):
    """Si irr_monthly devuelve TIR anualizada, su mensual anula el NPV."""
    r = irr_monthly(flows)
    if r is None:
        return
    assert r > -1.0
    monthly = (1.0 + r) ** (1.0 / 12.0) - 1.0
    npv = sum(f / (1.0 + monthly) ** i for i, f in enumerate(flows))
    scale = sum(abs(f) for f in flows)
    assert abs(npv) <= 1e-4 * max(scale, 1.0)


# --- Tandas adversariales ----------------------------------------------------

@st.composite
def adversarial_sequences(draw):
    """Mismo dia, ventas parcialmente descubiertas, recompras cruzando la
    ventana de 2 meses: la contabilidad debe seguir cerrando."""
    currency = draw(st.sampled_from(["EUR", "USD"]))
    day = date(2023, 1, 2)
    holdings = C("0")
    ops = []
    for _ in range(draw(st.integers(1, 28))):
        day += timedelta(days=draw(st.integers(0, 12)))
        action = draw(st.sampled_from(["buy", "sell"] if holdings > 0 else ["buy"]))
        qty = draw(_qty)
        price = draw(_price)
        fees = draw(_fee)
        ops.append((action, qty, price, fees, day, currency))
        holdings = holdings + qty if action == "buy" else holdings - qty
    return ops


@given(ops=adversarial_sequences())
@SLOW
def test_fifo_conservation_adversarial(ops):
    """La ley de conservacion aguanta con sobreventas y empates de fecha
    (el exceso descubierto se valora a coste cero y se marca)."""
    events = sorted(
        (_tx(a, q, p, f, d, i, c) for i, (a, q, p, f, d, c) in enumerate(ops)),
        key=_fifo_sort_key,
    )
    lots, year_sales = replay_tax_fifo(events, _rate_fn, date(2000, 1, 1), date(2099, 1, 1))
    buy_cost = sum((q * p + f for a, q, p, f, d, c in ops if a == "buy"), C("0"))
    blocked_created = sum(
        (e["sale"]["blocked_qty"] * e["sale"]["loss_per_share"] for e in year_sales if e["sale"]),
        C("0"),
    )
    consumed = sum((e["cost_native"] for e in year_sales), C("0"))
    remaining = sum((lot["qty"] * lot["unit"] + lot["deferred"] for lot in lots), C("0"))
    tol = C("1e-9") + buy_cost * C("1e-12")
    assert abs(buy_cost + blocked_created - consumed - remaining) <= tol
    # Oraculo de sobreventa en el MISMO orden que el replay (compra antes que
    # venta a igual fecha): el exceso marcado debe ser exactamente el descubierto.
    holdings = C("0")
    sales_iter = iter(year_sales)
    for event in events:
        if event.action == "buy":
            holdings += event.quantity
            continue
        if event.action != "sell":
            continue
        entry = next(sales_iter)
        expected_over = max(C("0"), event.quantity - holdings)
        assert entry["over_sell_quantity"] == expected_over
        assert entry["over_sell"] == (expected_over > 0)
        holdings = max(C("0"), holdings - event.quantity)
    for entry in year_sales:
        sale = entry["sale"]
        if sale is not None:
            assert sale["blocked_qty"] + sale["qty_unblocked"] == entry["transaction"].quantity
    for lot in lots:
        assert lot["qty"] > 0 and lot["capacity"] >= 0 and lot["deferred"] >= 0
