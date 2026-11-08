"""Propiedades de las reglas DCA de la app: zonas, avisos e importes del plan.

Cada test fija una regla documentada en ``dca_signal_engine``,
``dca_signal_service`` o ``plan_contribution_split`` y la comprueba sobre
series generadas (hypothesis) y casos limite: precio ausente, nivel caducado,
serie plana, split y cierres no validos.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    LEVEL_LIGHT_TRIM,
    LEVEL_STRONG_TRIM,
    DailyBar,
    evaluate_series,
)
from app.services.dca_signal_service import PriceRow, alert_direction, build_bars, should_alert
from app.services.plan_contribution_split import (
    DCA_MULTIPLIER,
    LOW_VOLATILITY_THRESHOLD,
    SplitCandidate,
    split_contribution,
)

VALID_LEVELS = {4, 3, 2, 1, LEVEL_LIGHT_TRIM, LEVEL_STRONG_TRIM}
SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _bars_from_monthly(
    rets: list[float], start: float = 100.0, day0: date = date(2010, 1, 4)
) -> list[DailyBar]:
    """Un cierre por mes (dia 4 de cada mes) a partir de rentabilidades mensuales."""
    bars = []
    px = start
    for i, r in enumerate(rets):
        px = max(px * (1.0 + r), 0.01)
        y, m = divmod(day0.month - 1 + i, 12)
        bars.append(DailyBar(day=date(day0.year + y, m + 1, 4), close=px))
    return bars


monthly_rets = st.lists(st.floats(min_value=-0.45, max_value=0.6, allow_nan=False), min_size=14, max_size=70)


@SETTINGS
@given(monthly_rets)
def test_sin_look_ahead_el_veredicto_de_un_mes_no_cambia_con_meses_posteriores(rets):
    bars = _bars_from_monthly(rets)
    full = {v.period: v for v in evaluate_series(bars, month_complete=True)}
    for cut in range(DEFAULT_PARAMS.min_months, len(bars) + 1, 7):
        part = evaluate_series(bars[:cut], month_complete=True)
        if not part:
            continue
        last = part[-1]
        ref = full[last.period]
        assert last.level == ref.level
        assert last.level_prices == ref.level_prices
        assert last.metrics["vol"] == ref.metrics["vol"]


@SETTINGS
@given(monthly_rets, st.sampled_from([0.125, 0.25, 0.5, 2.0, 4.0, 8.0, 32.0]))
def test_niveles_invariantes_a_la_escala_split_y_cierre_ajustado(rets, factor):
    # Factores potencia de 2: el reescalado es exacto en coma flotante, asi que
    # cualquier diferencia de nivel seria de la formula y no de redondeo en un
    # empate exacto con el umbral 0,0 de 2X.
    bars = _bars_from_monthly(rets)
    scaled = [DailyBar(day=b.day, close=b.close * factor) for b in bars]
    a = [v.level for v in evaluate_series(bars, month_complete=True)]
    b = [v.level for v in evaluate_series(scaled, month_complete=True)]
    assert a == b


@SETTINGS
@given(monthly_rets)
def test_zonas_validas_y_regla_combined(rets):
    bars = _bars_from_monthly(rets)
    for v in evaluate_series(bars, month_complete=True):
        assert v.level in VALID_LEVELS
        m = v.metrics
        hist = m["months_of_history"]
        if v.level >= 1:
            expected = max(m["level_drawdown"], m["level_sma_gap"] or 1)
            if DEFAULT_PARAMS.cap4_before_months and hist < DEFAULT_PARAMS.cap4_before_months:
                expected = min(expected, 3)
            assert v.level == expected
        else:
            # Recorte solo desde 1X: ninguna familia de compra activa.
            assert max(m["level_drawdown"], m["level_sma_gap"] or 1) == 1
            assert m["trim_sma_gap"] is not None and m["trim_sma_gap"] >= DEFAULT_PARAMS.trim_light_gap
            if v.level == LEVEL_STRONG_TRIM:
                assert m["trim_sma_gap"] >= DEFAULT_PARAMS.trim_strong_gap
                assert (m["rsi"] or 0.0) >= DEFAULT_PARAMS.trim_rsi_strong
        if m["drawdown"] >= DEFAULT_PARAMS.dd_thresholds[2]:
            assert v.level == (4 if hist >= (DEFAULT_PARAMS.cap4_before_months or 0) else 3)


@SETTINGS
@given(monthly_rets)
def test_precios_de_nivel_ordenados_y_positivos(rets):
    for v in evaluate_series(_bars_from_monthly(rets), month_complete=True):
        prices = [v.level_prices.get(k) for k in ("2x", "3x", "4x")]
        known = [p for p in prices if p is not None]
        assert all(p > 0 for p in known)
        assert known == sorted(known, reverse=True)
        assert all(p <= v.metrics["high"] + 1e-6 for p in known)


def test_serie_plana_nunca_da_3x_4x_ni_recorte():
    """Precio congelado: la vol no es fiable y no se fabrica 3X/4X.

    El umbral 2X de ``sma_gap`` es 0,0 (cierre EN o bajo la SMA larga), asi que
    una serie exactamente plana queda en 2X: es la regla escrita (``>=``).
    """
    bars = _bars_from_monthly([0.0] * 60)
    assert {v.level for v in evaluate_series(bars, month_complete=True)} <= {1, 2}


def test_mes_sin_precio_no_inventa_veredicto():
    bars = _bars_from_monthly([0.01] * 30)
    hole = bars[20].day
    gapped = [b for b in bars if (b.day.year, b.day.month) != (hole.year, hole.month)]
    periods = {v.period for v in evaluate_series(gapped, month_complete=True)}
    assert f"{hole.year:04d}-{hole.month:02d}" not in periods
    assert len(periods) == len(gapped) - DEFAULT_PARAMS.min_months + 1


def test_cierres_no_validos_se_ignoran_sin_romper():
    bars = _bars_from_monthly([0.02] * 30)
    bad = [
        *bars[:10],
        DailyBar(day=bars[10].day + timedelta(days=1), close=float("nan")),
        DailyBar(day=bars[11].day + timedelta(days=1), close=0.0),
        DailyBar(day=bars[12].day + timedelta(days=1), close=-5.0),
        *bars[10:],
    ]
    a = [(v.period, v.level) for v in evaluate_series(bars, month_complete=True)]
    b = [(v.period, v.level) for v in evaluate_series(bad, month_complete=True)]
    assert a == b


def test_split_con_cierre_ajustado_no_es_desplome():
    """Un split 4:1 en el cierre bruto con ``adj_close`` presente no crea una zona de compra."""
    rows = []
    d = date(2015, 1, 5)
    for i in range(48):
        raw = 100.0 * (1.01**i)
        if i >= 30:
            raw /= 4.0  # el bruto cae a la cuarta parte el dia del split
        rows.append(PriceRow(day=d + timedelta(days=30 * i), close=raw, adj_close=100.0 * (1.01**i) / 4.0))
    bars, _factor = build_bars(rows)
    levels = {v.level for v in evaluate_series(bars, month_complete=True)}
    assert levels <= {1, LEVEL_LIGHT_TRIM, LEVEL_STRONG_TRIM}


def test_fila_suelta_sin_ajuste_no_pasa_la_serie_a_brutos():
    d = date(2015, 1, 5)
    rows = [PriceRow(day=d + timedelta(days=30 * i), close=400.0, adj_close=100.0) for i in range(30)]
    rows.insert(15, PriceRow(day=d + timedelta(days=30 * 15 + 1), close=400.0, adj_close=None))
    bars, factor = build_bars(rows)
    assert all(abs(b.close - 100.0) < 1e-9 for b in bars)
    assert abs(factor - 4.0) < 1e-9


# --- Avisos -----------------------------------------------------------------

levels = st.sampled_from(sorted(VALID_LEVELS))


@given(levels, levels)
def test_direccion_de_aviso(level, prev):
    d = alert_direction(level, prev)
    if level == prev:
        assert d is None
    elif level >= 1 and prev >= 1:
        assert d == ("up" if level > prev else "down")
    elif level < 0 and prev < 0:
        assert d == ("up" if level < prev else "down")
    else:
        assert d in ("up", "down")


@given(levels, st.integers(min_value=0, max_value=4), st.booleans())
def test_primera_evaluacion_nunca_avisa(level, min_level, trims):
    assert not should_alert(level=level, previous_level=None, min_level=min_level, trims_enabled=trims)


@given(levels, levels, st.integers(min_value=0, max_value=4))
def test_recortes_solo_avisan_con_dca_alert_trims(level, prev, min_level):
    if level < 0 or (prev < 0 and level == 1):
        assert not should_alert(level=level, previous_level=prev, min_level=min_level, trims_enabled=False)
        assert not should_alert(
            level=level,
            previous_level=prev,
            min_level=min_level,
            trims_enabled=False,
            up_min_level=3,
            down_max_level=1,
        )


@given(levels, levels, st.booleans())
def test_minimo_cero_apaga_los_avisos_de_compra(level, prev, trims):
    if level >= 1 and prev >= 1:
        assert not should_alert(level=level, previous_level=prev, min_level=0, trims_enabled=trims)


# --- Importes del plan --------------------------------------------------------

cand = st.builds(
    SplitCandidate,
    ticker=st.text(alphabet="ABCDEFGHIJ", min_size=1, max_size=4),
    base_weight=st.decimals(min_value=0, max_value=100, places=2, allow_nan=False, allow_infinity=False),
    dca_level=st.one_of(st.none(), levels),
    dca_vol=st.one_of(st.none(), st.floats(min_value=0, max_value=2), st.just(float("nan"))),
    dca_stale=st.booleans(),
    concentration_capped=st.booleans(),
)


@SETTINGS
@given(
    st.decimals(min_value=0, max_value=100000, places=2),
    st.lists(cand, min_size=1, max_size=12, unique_by=lambda c: c.ticker),
)
def test_reparto_cuadra_al_centimo_y_nunca_negativo(amount, cands):
    out = split_contribution(amount, cands)
    amounts = [Decimal(str(a["amount"])) for a in out["allocations"]]
    assert all(a >= 0 for a in amounts)
    assert sum(amounts) + Decimal(str(out["unallocated"])) == amount
    if out["status"] == "ok":
        assert sum(amounts) == amount
    for a, c in zip(out["allocations"], cands, strict=True):
        if c.dca_level is not None and DCA_MULTIPLIER[c.dca_level] == 0:
            assert a["amount"] == 0  # recorte: sin dinero nuevo
        assert a["multiplier"] in (0, 1, 4, 9, 16)


@SETTINGS
@given(st.lists(cand, min_size=2, max_size=8, unique_by=lambda c: c.ticker))
def test_pesos_nivel_cuadrado_poco_volatil_y_sin_nivel(cands):
    out = split_contribution(Decimal("1000"), cands)
    for a, c in zip(out["allocations"], cands, strict=True):
        if c.dca_level is None:
            assert a["multiplier"] == 1
        elif (
            c.dca_level >= 2
            and c.dca_vol is not None
            and math.isfinite(c.dca_vol)
            and 0 < c.dca_vol < LOW_VOLATILITY_THRESHOLD
        ):
            assert a["multiplier"] == 1 and a["low_volatility"]
        else:
            assert a["multiplier"] == DCA_MULTIPLIER[c.dca_level]


@SETTINGS
@given(st.lists(cand, min_size=1, max_size=8, unique_by=lambda c: c.ticker))
def test_el_tope_nunca_deja_el_mes_sin_destino(cands):
    out = split_contribution(Decimal("500"), cands)
    uncapped = split_contribution(
        Decimal("500"), [c.__class__(**{**c.__dict__, "concentration_capped": False}) for c in cands]
    )
    if uncapped["status"] == "ok":
        assert out["status"] == "ok"


@SETTINGS
@given(st.lists(cand, min_size=2, max_size=6, unique_by=lambda c: c.ticker), levels)
def test_subir_de_nivel_no_reduce_el_importe(cands, new_level):
    base = [c.__class__(**{**c.__dict__, "concentration_capped": False, "dca_vol": None}) for c in cands]
    first = base[0]
    if first.dca_level is None or new_level is None:
        return
    lo, hi = sorted([first.dca_level, new_level], key=lambda x: DCA_MULTIPLIER[x])
    a = split_contribution(
        Decimal("1000"), [first.__class__(**{**first.__dict__, "dca_level": lo}), *base[1:]]
    )
    b = split_contribution(
        Decimal("1000"), [first.__class__(**{**first.__dict__, "dca_level": hi}), *base[1:]]
    )
    assert b["allocations"][0]["amount"] >= a["allocations"][0]["amount"] - 0.01


def test_todo_en_recorte_queda_en_liquidez():
    cands = [
        SplitCandidate(ticker="A", base_weight=Decimal(1), dca_level=-1),
        SplitCandidate(ticker="B", base_weight=Decimal(1), dca_level=-2),
    ]
    out = split_contribution(Decimal("300"), cands)
    assert out["status"] == "all_trim" and out["unallocated"] == 300.0


def test_nivel_caducado_pesa_1x():
    cands = [
        SplitCandidate(
            ticker="A", base_weight=Decimal(1), dca_level=None, dca_stale=True, dca_period="2026-01"
        ),
        SplitCandidate(ticker="B", base_weight=Decimal(1), dca_level=4, dca_vol=0.5),
    ]
    out = split_contribution(Decimal("170"), cands)
    assert [a["amount"] for a in out["allocations"]] == [10.0, 160.0]
    assert "caducado" in out["allocations"][0]["reason"]
