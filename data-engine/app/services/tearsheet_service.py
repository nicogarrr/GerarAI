"""Tearsheet de metricas del portfolio sobre la serie de retornos existente.

Idea originada en ``quantstats`` (ranaroussi/quantstats, licencia permisiva
Apache-2.0) y ``pyfolio`` (quantopian/pyfolio, Apache-2.0): un "tearsheet" es
una hoja resumida con las estadisticas de una serie de retornos (Sharpe,
Sortino, max drawdown, win rate, exposicion). Diseno inspirado en ellos,
implementacion propia.

Decision de motor: se probo el paquete ``quantstats`` vendorizado en
``data-engine/quantstats/`` contra una serie sintetica. ``sharpe`` y
``sortino`` funcionan, pero ``max_drawdown`` exige precios con
``DatetimeIndex`` (falla con ``RangeIndex``) y el vendored arrastra
fragilidad de dependencias. Por hermeticidad y cero dependencias nuevas, las
5 metricas se implementan aqui en numpy/pandas puro con formulas
estandar (media/volatilidad anualizada a 252 dias, curva de riqueza para el
drawdown). No se anade ninguna dependencia a ``requirements.txt``.

La serie de retornos se lee de ``PortfolioDailySnapshot.daily_return``,
que ``PortfolioSnapshotService`` persiste tras cada import IBKR o
``market_refresh`` (ver ``app/services/ibkr_import_service.py`` y
``app/services/portfolio_snapshot_service.py``). La exposicion se deriva
del ultimo snapshot: posiciones (``PositionDailySnapshot``) frente a caja.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import PortfolioDailySnapshot, PositionDailySnapshot

TRADING_DAYS = 252


def _safe_float(value: Any) -> float | None:
    """Convierte a float JSON-serializable; None si no es finito."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def compute_metrics(
    returns: Sequence[float | Decimal | None] | pd.Series,
    *,
    periods: int = TRADING_DAYS,
    risk_free: float = 0.0,
) -> dict[str, Any]:
    """Calcula Sharpe, Sortino, max drawdown y win rate sobre retornos periodicos.

    ``periods`` anualiza (252 = dias de mercado). ``risk_free`` es el retorno
    libre de riesgo por periodo en las mismas unidades que ``returns``.
    Los Nones/NaN se descartan. Devuelve ``status`` = ``"ok"`` o
    ``"insufficient_data"`` (menos de 2 observaciones validas); en ese caso
    las metricas son None en lugar de fallar.
    """
    if isinstance(returns, pd.Series):
        series = pd.to_numeric(returns, errors="coerce").dropna()
    else:
        cleaned = [_safe_float(r) for r in returns]
        series = pd.Series([r for r in cleaned if r is not None], dtype=float)
    n = int(series.size)
    if n < 2:
        return {
            "status": "insufficient_data",
            "n_observations": n,
            "cumulative_return": None,
            "sharpe": None,
            "sortino": None,
            "max_drawdown": None,
            "win_rate": None,
            "best_day": None,
            "worst_day": None,
            "periods_per_year": periods,
        }

    values = series.to_numpy(dtype=float)
    excess = values - risk_free
    mean = float(np.mean(excess))
    volatility = float(np.std(excess, ddof=1))

    # Umbral absoluto: con retornos identicos, el redondeo deja una
    # desviacion ~1e-19 en lugar de 0 y el Sharpe divergeria.
    sharpe = mean / volatility * np.sqrt(periods) if volatility > 1e-12 else None

    # Sortino & Price (1994): desviacion a la baja respecto al objetivo
    # (aqui risk_free) sobre TODAS las observaciones:
    #   DD = sqrt( sum(min(r_i - T, 0)^2) / N )
    # No es la desviacion tipica (ddof=1, centrada en su media) de solo los
    # periodos negativos: eso infraestima/sobreestima el riesgo y daba None
    # con un unico periodo negativo o con perdidas iguales.
    shortfall = np.minimum(excess, 0.0)
    downside_vol = float(np.sqrt(np.mean(shortfall**2)))
    # Sin periodos por debajo del objetivo no hay riesgo a la baja medible.
    sortino = mean / downside_vol * np.sqrt(periods) if downside_vol > 1e-12 else None

    wealth = np.cumprod(1.0 + values)
    # F367: el patrimonio inicial (1.0) cuenta como pico; sin él una caída en
    # el primer periodo no se registraba como drawdown.
    wealth_path = np.concatenate(([1.0], wealth))
    peak = np.maximum.accumulate(wealth_path)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = np.where(peak > 0, (wealth_path - peak) / peak, 0.0)
    max_drawdown = float(np.min(drawdown))

    return {
        "status": "ok",
        "n_observations": n,
        "cumulative_return": _safe_float(float(wealth[-1] - 1.0)),
        "sharpe": _safe_float(sharpe),
        "sortino": _safe_float(sortino),
        "max_drawdown": _safe_float(max_drawdown),
        "win_rate": _safe_float(float(np.mean(values > 0))),
        "best_day": _safe_float(float(np.max(values))),
        "worst_day": _safe_float(float(np.min(values))),
        "periods_per_year": periods,
    }


def exposure_from_snapshot(
    snapshot: PortfolioDailySnapshot,
    position_rows: Sequence[PositionDailySnapshot],
) -> dict[str, Any]:
    """Exposicion renta-variable/caja y concentracion del ultimo snapshot.

    top_1_weight/top_5_weight conservan su contrato sobre NAV neto, con caja.
    Los nuevos top_*_gross_positions_weight usan suma de valores absolutos y
    permiten comparar concentracion sin confundirla con apalancamiento.
    No se modifica PositionDailySnapshot.weight ni ningun snapshot persistido.
    """
    total = _safe_float(snapshot.total_value_base) or 0.0
    positions_value = _safe_float(snapshot.positions_value_base) or 0.0
    cash_value = _safe_float(snapshot.cash_value_base) or 0.0
    weights: list[float] = []
    gross_values: list[float] = []
    gross_complete = True
    for row in position_rows:
        value = _safe_float(row.market_value_base)
        if value is None:
            gross_complete = False
            continue
        if total > 0:
            weights.append(value / total)
        gross_values.append(abs(value))
    weights.sort(reverse=True)
    gross_value = sum(gross_values) if gross_complete and gross_values else None
    gross_weights = sorted((value / gross_value for value in gross_values), reverse=True) if gross_value else []
    equity_weight = positions_value / total if total > 0 else None
    return {
        "snapshot_date": snapshot.snapshot_date.isoformat(),
        "base_currency": snapshot.base_currency,
        "total_value_base": _safe_float(snapshot.total_value_base),
        "equity_weight": _safe_float(equity_weight),
        "cash_weight": _safe_float(cash_value / total) if total > 0 else None,
        # Recuento de posiciones en cartera: las filas del snapshot, no las
        # que cupieron en el vector de pesos (con NAV <= 0 - margen por encima
        # del valor - los pesos son None pero las posiciones SIGUEN ahi).
        "n_positions": len(position_rows),
        "top_1_weight": _safe_float(weights[0]) if weights else None,
        "top_5_weight": _safe_float(sum(weights[:5])) if weights else None,
        # Auditoria A: caja/margen aparte con su signo, y el significado de
        # cada peso explicito. equity_weight es posiciones/NAV: con margen
        # supera 1 y es APALANCAMIENTO, no distribucion; los pesos de
        # concentracion comparables con la vista de Cartera son los *_gross_*.
        "positions_value_base": _safe_float(snapshot.positions_value_base),
        "cash_value_base": _safe_float(snapshot.cash_value_base),
        "net_leverage": _safe_float(equity_weight),
        "gross_leverage": _safe_float(gross_value / total) if gross_value and total > 0 else None,
        "weight_bases": {
            "top_1_weight": "nav_with_cash",
            "top_5_weight": "nav_with_cash",
            "equity_weight": "leverage_positions_over_nav",
            "cash_weight": "signed_cash_over_nav",
            "top_1_gross_positions_weight": "gross_positions_abs",
            "top_5_gross_positions_weight": "gross_positions_abs",
        },
        # Additive, explicit denominator. Existing NAV fields stay unchanged.
        "gross_positions_value_base": _safe_float(gross_value),
        "top_1_gross_positions_weight": _safe_float(gross_weights[0]) if gross_weights else None,
        "top_5_gross_positions_weight": _safe_float(sum(gross_weights[:5])) if gross_weights else None,
    }


def latest_continuous_returns(
    history: Sequence[PortfolioDailySnapshot],
) -> tuple[list[float], dict[str, Any]]:
    """Retornos del ultimo tramo continuo de la serie (Auditoria A).

    Un ``daily_return=None`` despues de la base es un hueco: falta valoracion,
    hay flujos ambiguos o la foto no cubre toda la cartera. Antes se
    descartaban los None y se encadenaban los tramos de ambos lados como si
    fueran dias consecutivos. Ahora las metricas usan solo el tramo continuo
    mas reciente (la misma regla que ``verifiedPortfolioHistory`` en el
    frontend) y ``qualification`` dice si la serie tenia huecos.
    ``start_date`` es la foto base del tramo (la anterior a su primer retorno).
    """
    ordered = sorted(history, key=lambda row: row.snapshot_date)
    segments: list[tuple[int, int]] = []  # [inicio, fin] de indices con retorno
    start: int | None = None
    breaks = 0
    seen_return = False
    for index, row in enumerate(ordered):
        if row.daily_return is not None:
            seen_return = True
            if start is None:
                start = index
            continue
        if start is not None:
            segments.append((start, index - 1))
            start = None
        if seen_return:
            breaks += 1
    if start is not None:
        segments.append((start, len(ordered) - 1))
    total_returns = sum(last - first + 1 for first, last in segments)
    if not segments:
        return [], {
            "continuous": True,
            "series_breaks": breaks,
            "excluded_returns": 0,
            "start_date": None,
            "end_date": None,
        }
    first, last = segments[-1]
    returns = [float(row.daily_return) for row in ordered[first : last + 1]]  # type: ignore[arg-type]
    base_index = first - 1 if first > 0 else first
    return returns, {
        "continuous": breaks == 0,
        "series_breaks": breaks,
        "excluded_returns": total_returns - len(returns),
        "start_date": ordered[base_index].snapshot_date.isoformat(),
        "end_date": ordered[last].snapshot_date.isoformat(),
    }


class TearsheetService:
    """Construye el tearsheet desde los snapshots persistidos del portfolio."""

    def build(
        self,
        db: Session,
        *,
        periods: int = TRADING_DAYS,
        risk_free: float = 0.0,
    ) -> dict[str, Any]:
        """Lee ``daily_return`` del historico y exposicion del ultimo snapshot."""
        from app.services.portfolio_fx_service import PortfolioFXService

        portfolio = PortfolioFXService().portfolio(db)
        if portfolio is None:
            return {
                "status": "no_portfolio",
                "metrics": None,
                "qualification": None,
                "exposure": None,
                "trace": {"method": "tearsheet_numpy_pandas_v1"},
            }
        history = list(
            db.scalars(
                select(PortfolioDailySnapshot)
                .where(PortfolioDailySnapshot.portfolio_id == portfolio.id)
                .order_by(PortfolioDailySnapshot.snapshot_date)
            ).all()
        )
        returns, qualification = latest_continuous_returns(history)
        metrics = compute_metrics(returns, periods=periods, risk_free=risk_free)
        exposure: dict[str, Any] | None = None
        if history:
            latest = max(history, key=lambda row: row.snapshot_date)
            position_rows = list(
                db.scalars(
                    select(PositionDailySnapshot)
                    .where(
                        PositionDailySnapshot.portfolio_snapshot_id == latest.id
                    )
                    .order_by(desc(PositionDailySnapshot.market_value_base))
                ).all()
            )
            exposure = exposure_from_snapshot(latest, position_rows)
        return {
            "status": metrics["status"],
            "metrics": metrics,
            "qualification": qualification,
            "exposure": exposure,
            "trace": {
                "method": "tearsheet_numpy_pandas_v1",
                "n_snapshots": len(history),
                "n_returns": len(returns),
            },
        }
