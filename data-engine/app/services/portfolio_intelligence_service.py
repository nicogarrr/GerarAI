"""Portfolio performance, risk, exposure and return attribution."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from operator import mul
from statistics import fmean, mean, pstdev
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models import CashBalance, Company, FinancialFact, MarketPrice, Position, Transaction
from app.services.async_bridge import run_from_any_context
from app.services.portfolio_fx_service import PortfolioFXService, currency_key
from app.services.portfolio_ledger_service import BUY_ACTIONS, SELL_ACTIONS
from app.services.portfolio_reconstruction_service import PortfolioReconstructionService
from app.services.portfolio_snapshot_service import PortfolioSnapshotService
from app.services.portfolio_xray import portfolio_xray
from app.services.tax_report_service import (
    cash_amount,
    cash_quantity_is_canonical,
    is_cash_action,
    withholding_cost,
)
from app.valuation.currency import normalize_currency

# Exchange -> listing-market country. Best-effort fallback only: the owning
# fact is issuer domicile, and positions without a known exchange are grouped
# under "Unknown" rather than guessed.
EXCHANGE_COUNTRY = {
    "NASDAQ": "United States",
    "NYSE": "United States",
    "AMEX": "United States",
    "NYSEARCA": "United States",
    "LSE": "United Kingdom",
    "XETRA": "Germany",
    "FWB": "Germany",
    "BME": "Spain",
    "EPA": "France",
    "EURONEXT": "Netherlands",
    "BIT": "Italy",
    "SIX": "Switzerland",
    "STO": "Sweden",
    "TSX": "Canada",
    "TSXV": "Canada",
    "TSE": "Japan",
    "HKEX": "Hong Kong",
    "ASX": "Australia",
    "B3": "Brazil",
    "NSE": "India",
    "KRX": "South Korea",
}


# Tolerancia de frescura de las patas del retorno FX del periodo:
# cubre fin de semana y festivo corto; un dato mas viejo no se reutiliza.
_FX_LEG_TOLERANCE = timedelta(days=7)


def _fx_rate_with_date(
    fx_table: dict[tuple[str, str], list[tuple[date, Decimal]]],
    *,
    quote_currency: str,
    base_currency: str,
    as_of: date,
) -> tuple[date, Decimal] | None:
    """Ultimo tipo <= as_of CON su fecha: la frescura se exige, no se asume.

    Misma resolucion que ``PortfolioFXService.rate_from_table`` (directa o
    inversa) pero devolviendo la fecha del dato usado, imprescindible para
    no comparar un spot historico contra un corte posterior.
    """
    from bisect import bisect_right

    quote = quote_currency.upper()
    base = base_currency.upper()
    if quote == base:
        return (as_of, Decimal("1"))
    series = fx_table.get((base, quote))
    if series:
        idx = bisect_right(series, (as_of, Decimal("Infinity"))) - 1
        if idx >= 0:
            return series[idx]
    inverse = fx_table.get((quote, base))
    if inverse:
        idx = bisect_right(inverse, (as_of, Decimal("Infinity"))) - 1
        if idx >= 0 and inverse[idx][1]:
            return (inverse[idx][0], Decimal("1") / inverse[idx][1])
    return None


def _live_benchmark_prices(cutoff: date) -> list[Any] | None:
    """SPY ajustado desde Yahoo (gratis, ya usado en Estrés histórico), sin filas en el master.

    Una empresa SPY global se colaría en listas, ingestas y jobs de todas las
    cuentas. Si Yahoo falla devuelve None y la comparativa queda honestamente sin datos.
    """
    from app.services.historical_stress_service import load_history

    try:
        history = run_from_any_context(load_history("SPY"), timeout=45)
    except Exception:
        return None
    rows = [
        SimpleNamespace(date=day, adj_close=Decimal(str(value)))
        for day, value in sorted(history["prices"].items())
        if day >= cutoff
    ]
    return rows or None


def _benchmark_prices(db: Session, cutoff: date) -> list[Any] | None:
    """Serie SPY: la del master si existe con precios; si no, la de Yahoo."""
    benchmark = db.scalar(select(Company).where(Company.ticker == "SPY"))
    if benchmark is not None:
        stored = list(
            db.scalars(
                select(MarketPrice)
                .where(MarketPrice.company_id == benchmark.id, MarketPrice.date >= cutoff)
                .order_by(MarketPrice.date)
            ).all()
        )
        if stored:
            return stored
    live = _live_benchmark_prices(cutoff)
    if live is None and benchmark is not None:
        return []
    return live


#: Tipo de CashTransaction de IBKR Flex para aportaciones y retiradas externas
#: (el importador las guarda como ``cash_misc`` con el atributo crudo ``type``).
_EXTERNAL_TRANSFER_TOKENS = ("deposit", "withdraw")


def _is_external_transfer(transaction: Any) -> bool:
    """True si la fila es una aportación o retirada EXTERNA de la cuenta."""
    action = (transaction.action or "").lower()
    if action in {"deposit", "withdrawal"}:
        return True
    if action != "cash_misc":
        return False
    payload = transaction.raw_payload or {}
    kind = str(payload.get("type") or payload.get("transactionType") or "").lower()
    return any(token in kind for token in _EXTERNAL_TRANSFER_TOKENS)


def _external_flow(transaction: Any) -> float:
    """Flujo para el INVERSOR: una aportación es salida (-), una retirada entrada (+).

    ``deposit``/``withdrawal`` guardan el importe como quantity × price (igual
    que ``PortfolioSnapshotService._external_flows``); ``cash_misc`` de IBKR
    lo guarda con signo en ``price`` (aportación positiva).
    """
    action = (transaction.action or "").lower()
    if action in {"deposit", "withdrawal"}:
        # nosemgrep: gerarai-money-none-to-zero -- quantity/price de Transaction son NOT NULL (default 0); el `or` es defensivo
        amount = abs(float(transaction.quantity or 0) * float(transaction.price or 0))
        return -amount if action == "deposit" else amount
    return -float(cash_amount(transaction))


# Sesiones minimas para anualizar la rentabilidad (mismo umbral que la reconstruccion).
MIN_ANNUALIZATION_SESSIONS = 60


class PortfolioIntelligenceService:
    def build(self, db: Session, *, years: int = 5) -> dict[str, Any]:
        years = max(1, min(years, 20))
        # «Hoy» del usuario (Europe/Madrid), no el día UTC del servidor.
        cutoff = local_today() - timedelta(days=365 * years)
        fx = PortfolioFXService()
        base_currency = fx.base_currency(db)
        rows = list(
            db.execute(select(Position, Company).join(Company, Position.company_id == Company.id)).all()
        )
        # Honest valuation: a position without a base-currency value is excluded
        # from totals/weights and reported, never silently counted as zero.
        base_values: dict[int, float] = {}
        missing_fx: list[dict[str, Any]] = []
        for position, company in rows:
            value_base = position.market_value_base
            if (
                value_base is None
                and position.currency == base_currency
                and (position.market_value_native or position.market_value) > 0
            ):
                value_base = position.market_value_native or position.market_value
            if value_base is None:
                missing_fx.append(
                    {
                        "kind": "position",
                        "ticker": company.ticker,
                        "quote_currency": position.currency,
                        "base_currency": base_currency,
                        "as_of": position.as_of.isoformat() if position.as_of else None,
                    }
                )
                continue
            base_values[position.id] = float(value_base)
        total_value = sum(base_values.values())
        weights = {
            company.id: (base_values[position.id] / total_value if total_value > 0 else 0)
            for position, company in rows
            if position.id in base_values
        }
        price_series: dict[int, list[Any]] = {company.id: [] for _, company in rows}
        if rows:
            # Lote: 1 query para todas las series (anti N+1 por posición).
            # Solo las columnas que se usan (filas ligeras con .date, .close,
            # .adj_close y .source): ~25.000 entidades ORM completas costaban
            # mas que todo el calculo.
            all_prices = list(
                db.execute(
                    select(
                        MarketPrice.company_id,
                        MarketPrice.date,
                        MarketPrice.close,
                        MarketPrice.adj_close,
                        MarketPrice.source,
                    )
                    .where(
                        MarketPrice.company_id.in_([company.id for _, company in rows]),
                        MarketPrice.date >= cutoff,
                    )
                    .order_by(MarketPrice.company_id, MarketPrice.date)
                ).all()
            )
            for price in all_prices:
                price_series.setdefault(price.company_id, []).append(price)
            price_series = {
                company_id: self._fill_trailing_spot(series) for company_id, series in price_series.items()
            }
        returns = {company_id: self._returns(series) for company_id, series in price_series.items()}
        indicative_returns = self._portfolio_returns(returns, weights)
        # Ventana COMPLETA (5 anos por defecto): con la paginacion del
        # endpoint llegaban solo las 20 sesiones mas antiguas y el TWR de la
        # ventana era el de un mes, marcado ademas como exacto.
        snapshots = PortfolioSnapshotService().history(db, start=cutoff, page_size=None)
        snapshot_returns = {
            snapshot.snapshot_date: float(snapshot.daily_return)
            for snapshot in snapshots
            if snapshot.daily_return is not None
        }
        snapshot_exact = self._snapshot_history_is_exact(snapshots)
        reconstruction = PortfolioReconstructionService().build(db, start=cutoff, rows=rows)
        use_reconstruction = not snapshot_exact and reconstruction.usable
        if snapshot_exact:
            portfolio_returns = snapshot_returns
        elif use_reconstruction:
            portfolio_returns = reconstruction.returns
        else:
            portfolio_returns = indicative_returns
        partial_day = self._partial_trading_day(price_series, snapshots, datetime.now(UTC))
        twr = self._compound(list(portfolio_returns.values()))
        # Una ventana corta no se anualiza, venga de snapshots, reconstruccion o
        # pesos actuales: extrapolar 1 dia (+0,99 %) a un ano daba 1097 %.
        short_annualization_window = bool(portfolio_returns) and (
            len(portfolio_returns) < MIN_ANNUALIZATION_SESSIONS
        )
        annualized_return = (
            (1 + twr) ** (252 / len(portfolio_returns)) - 1
            if portfolio_returns and twr > -1 and not short_annualization_window
            else None
        )
        volatility = (
            pstdev(portfolio_returns.values()) * math.sqrt(252) if len(portfolio_returns) >= 2 else None
        )
        # Sortino: el denominador es la DESVIACION DOWNSIDE sobre la muestra
        # completa, sqrt(mean(min(0, r - T)^2)), no la desviacion del subconjunto
        # de retornos negativos. Con la formula anterior, dos carteras con los
        # mismos 252 dias daban Sharpe y Sortino distintos segun cuantos
        # negativos hubiera (252 con -12% y 52 con -2% daban -12,08 y -5,82 para
        # la misma serie). Es la definicion de quantstats/stats.py.
        n_returns = len(portfolio_returns)
        downside_deviation = (
            math.sqrt(sum(min(value, 0.0) ** 2 for value in portfolio_returns.values()) / n_returns)
            * math.sqrt(252)
            if n_returns >= 2
            else None
        )
        # Sharpe: el numerador es la media aritmetica de los retornos (exceso
        # sobre el tipo sin riesgo, que aqui es 0 por no declararse), no el CAGR
        # geométrico de un unico camino realizado. El CAGR de una sola
        # realización es una muestra ruidosa de la deriva, asi que el ratio no
        # es comparable entre periodos. Es la definicion de quantstats.
        mean_return = fmean(portfolio_returns.values()) * 252 if n_returns >= 2 else None
        sharpe = mean_return / volatility if mean_return is not None and volatility not in {None, 0} else None
        sortino = (
            mean_return / downside_deviation
            if mean_return is not None and downside_deviation not in {None, 0}
            else None
        )
        drawdown = self._drawdown(portfolio_returns)
        var_95, cvar_95 = self._historical_var(portfolio_returns)
        calmar = (
            annualized_return / abs(drawdown["max_drawdown"])
            if annualized_return is not None and drawdown["max_drawdown"] not in {None, 0}
            else None
        )
        xirr, xirr_trace = self._xirr(db, rows)
        correlations, correlation_observations = self._correlations(returns, rows)
        beta, beta_trace = self._beta(db, portfolio_returns, cutoff)
        benchmark = self._benchmark_comparison(db, portfolio_returns, cutoff)
        exposures = self._exposures(rows, total_value, base_values)
        attribution = self._attribution(db, rows, weights, price_series, cutoff)
        ledger_contribution = self._ledger_contribution(db, rows, cutoff)
        complete_price_series = sum(len(series) >= 2 for series in price_series.values())
        today_ = local_today()
        horizon_coverages = {
            company.id: self._horizon_coverage(price_series.get(company.id, []), cutoff, today_)
            for _, company in rows
        }
        positions_with_full_horizon = sum(1 for _, full in horizon_coverages.values() if full)
        mean_horizon_coverage = (
            round(100 * fmean(share for share, _ in horizon_coverages.values()), 1) if rows else 100.0
        )
        return {
            "as_of": today_,
            "base_currency": base_currency,
            "missing_fx": missing_fx,
            "horizon_years": years,
            "performance": {
                "twr": twr if portfolio_returns else None,
                "xirr": xirr,
                "annualized_return": annualized_return,
                "trace": xirr_trace,
                "twr_method": (
                    "daily_portfolio_snapshots"
                    if snapshot_exact
                    else (
                        "ledger_reconstruction_positions_only"
                        if use_reconstruction
                        else "static_current_weight_estimate"
                    )
                ),
                "twr_is_exact": snapshot_exact,
                "twr_period": (
                    {
                        "start": reconstruction.series[0]["date"],
                        "end": reconstruction.series[-1]["date"],
                        "sessions": len(reconstruction.returns),
                    }
                    if use_reconstruction
                    else None
                ),
                "reconstruction": reconstruction.as_dict(),
                "valuation_history": reconstruction.series if use_reconstruction else [],
            },
            "risk": {
                "max_drawdown": drawdown["max_drawdown"],
                "drawdown_series": drawdown["series"],
                "volatility": volatility,
                "sharpe": sharpe,
                "sortino": sortino,
                "var_95": var_95,
                "cvar_95": cvar_95,
                "calmar": calmar,
                "beta": beta,
                "beta_trace": beta_trace,
                "correlations": correlations,
                "correlation_observations": correlation_observations,
                "correlation_min_observations": PortfolioIntelligenceService.MIN_CORRELATION_OBSERVATIONS,
            },
            "concentration": {
                "top_1": max(weights.values(), default=0),
                "top_5": sum(sorted(weights.values(), reverse=True)[:5]),
                "herfindahl": sum(weight**2 for weight in weights.values()),
                "weights": {
                    company.ticker: weights[company.id] for _, company in rows if company.id in weights
                },
            },
            "exposures": exposures,
            "xray": portfolio_xray(
                {"weights": {company.ticker: weights[company.id] for _, company in rows if company.id in weights}},
                exposures,
                base_currency,
            ),
            "attribution": attribution,
            "ledger_contribution": ledger_contribution,
            "benchmark": benchmark,
            "coverage": {
                "positions": len(rows),
                "positions_with_price_history": complete_price_series,
                "positions_with_full_horizon": positions_with_full_horizon,
                "price_history_window_percent": mean_horizon_coverage,
                "price_history_percent": (round(100 * complete_price_series / len(rows), 1) if rows else 100),
                "portfolio_snapshots": len(snapshots),
                "partial_trading_day": partial_day,
                "spot_tail_positions": sorted(
                    company.ticker
                    for _, company in rows
                    if any(isinstance(row, SimpleNamespace) for row in price_series.get(company.id, []))
                ),
                "snapshot_returns": len(snapshot_returns),
                "snapshot_pricing_complete": sum(
                    snapshot.pricing_coverage == Decimal("1") for snapshot in snapshots
                ),
                "limitations": (
                    []
                    if snapshot_exact
                    else [
                        "TWR uses static current weights until complete daily position and cash snapshots exist.",
                    ]
                )
                + ["Attribution is an evidence-aware decomposition, not transaction-lot Brinson attribution."]
                + (
                    [
                        "Price/snapshot series may include the current trading day before the 22:00 UTC close cutoff (possible partial bar; conservative approximation, not a confirmed close): daily metrics (TWR, volatility, drawdown, VaR) use it as-is."
                    ]
                    if partial_day
                    else []
                )
                + (
                    [
                        f"Annualized return not shown: only {len(portfolio_returns)} daily return(s) available (minimum {MIN_ANNUALIZATION_SESSIONS}); extrapolating a short window to a year would be misleading."
                    ]
                    if short_annualization_window
                    else []
                )
                + (
                    [
                        f"Benchmark annualized return and alpha not shown: only {benchmark['observations']} overlapping daily observation(s) (minimum {MIN_ANNUALIZATION_SESSIONS}); benchmark TWR and tracking error are unaffected."
                    ]
                    if benchmark.get("status") == "calculated"
                    and benchmark["observations"] < MIN_ANNUALIZATION_SESSIONS
                    else []
                )
                + (
                    [
                        f"{len(missing_fx)} position(s) excluded from totals, weights and exposures: no base-currency value (missing FX)."
                    ]
                    if missing_fx
                    else []
                ),
            },
        }

    @staticmethod
    def _partial_trading_day(
        price_series: dict[int, list[Any]], snapshots: list[Any], now_utc: datetime
    ) -> bool:
        """True si alguna serie incluye la barra del dia en curso (parcial).

        refresh_portfolio_prices_intraday escribe MarketPrice del dia antes
        del cierre, y el snapshot diario tambien puede ser de hoy: un retorno
        diario contra una barra abierta distorsiona TWR, volatilidad,
        drawdown y VaR de ese dia. No se excluye (es el mejor dato
        disponible) pero la cobertura lo MARCA.

        Zona y cierre: no hay calendario de mercado por instrumento en el
        backend, asi que se usa una aproximacion honesta documentada: fecha
        UTC de ``now_utc`` y corte a las 22:00 UTC. Antes del corte, una
        barra con fecha de hoy puede seguir abierta (los cierres US son
        20:00-21:00 UTC y los europeos 15:30-17:30 UTC); a partir del corte
        la barra del dia se da por completa y no se marca.
        """
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)
        cutoff = now_utc.replace(hour=22, minute=0, second=0, microsecond=0)
        if now_utc >= cutoff:
            return False
        today = now_utc.date()
        if any(series and series[-1].date >= today for series in price_series.values()):
            return True
        return any(snapshot.snapshot_date >= today for snapshot in snapshots)

    @staticmethod
    def _snapshot_history_is_exact(snapshots: list[Any]) -> bool:
        if len(snapshots) < 2:
            return False
        for previous, current in zip(snapshots, snapshots[1:]):
            if current.daily_return is None or current.pricing_coverage != Decimal("1"):
                return False
            if (current.snapshot_date - previous.snapshot_date).days > 3:
                return False
            if (current.metadata_ or {}).get("ambiguous_external_flows"):
                return False
        return snapshots[0].pricing_coverage == Decimal("1")

    @staticmethod
    def _fill_trailing_spot(series: list[Any]) -> list[Any]:
        """Las filas finales sin adj_close (precio spot de Finnhub / Yahoo intradia)
        usan `close`: tras el ultimo cierre ajustado no hay ajuste posterior que
        aplicar. Solo se rellena la COLA; un hueco interior sigue sin valor (no se
        inventa un precio ajustado entre dos cierres ajustados). Sin esto, con
        14 filas spot al final, total_return, atribucion y retornos diarios
        salian None en las 8 posiciones."""
        last_valid = -1
        for index, row in enumerate(series):
            if row.adj_close and row.adj_close > 0:
                last_valid = index
        if last_valid < 0 or last_valid == len(series) - 1:
            return series
        filled = list(series[: last_valid + 1])
        for row in series[last_valid + 1 :]:
            if row.close and row.close > 0:
                filled.append(
                    SimpleNamespace(date=row.date, close=row.close, adj_close=row.close, source=row.source)
                )
            else:
                filled.append(row)
        return filled

    # Tolerancia de anclaje al inicio/fin del horizonte: fines de semana y
    # festivos cortos no deben marcar una serie como "sin cubrir el horizonte".
    _HORIZON_ANCHOR_TOLERANCE = timedelta(days=10)

    @classmethod
    def _horizon_coverage(cls, series: list[Any], cutoff: date, today: date) -> tuple[float, bool]:
        """(fraccion del horizonte cubierta, cubre_todo_el_horizonte).

        `len(series) >= 2` solo dice "hay algo"; una serie de 15 sesiones en
        un horizonte de 5 anos contaba como cobertura completa. Aqui se mide
        la ventana real: tramo [primera, ultima] dentro de [cutoff, today]
        sobre la longitud del horizonte, y cobertura completa cuando la serie
        arranca a lo sumo _HORIZON_ANCHOR_TOLERANCE despues del cutoff y
        llega hasta hoy con la misma tolerancia.
        """
        horizon_days = max((today - cutoff).days, 1)
        if not series:
            return 0.0, False
        first = max(series[0].date, cutoff)
        last = min(series[-1].date, today)
        covered_days = max((last - first).days, 0)
        share = min(covered_days / horizon_days, 1.0)
        full = (
            series[0].date <= cutoff + cls._HORIZON_ANCHOR_TOLERANCE
            and series[-1].date >= today - cls._HORIZON_ANCHOR_TOLERANCE
        )
        return round(share, 4), full

    @staticmethod
    def _returns(series: list[MarketPrice]) -> dict[date, float]:
        """Retornos diarios simples, descartando los pares con precio no valido.

        `adj_close` tiene default=0 en el modelo, no NULL, asi que cualquier
        ingesta que rellene `close` pero no `adj_close` deja ceros interiores.
        Con la comprobacion solo sobre `previous`, un cero en `current`
        producia `0/prev - 1` = -1,0: un dia de -100% que se colaba en todas las
        metricas. Con 500 observaciones, un solo cero llevaba la TWR a -100%, la
        volatilizada anualizada de ~16% a ~73%, y max_drawdown y CVaR a valores
        sin sentido. Ahora se exige que AMBOS lados sean validos, y el par se
        descarta en lugar de fabricar un retorno.
        """
        result = {}
        for previous, current in zip(series, series[1:]):
            prev_close = previous.adj_close
            curr_close = current.adj_close
            if prev_close and curr_close and prev_close > 0 and curr_close > 0:
                result[current.date] = float(curr_close / prev_close - 1)
        return result

    @staticmethod
    def _portfolio_returns(
        returns: dict[int, dict[date, float]], weights: dict[int, float]
    ) -> dict[date, float]:
        by_date: dict[date, list[tuple[float, float]]] = defaultdict(list)
        for company_id, series in returns.items():
            for day, value in series.items():
                by_date[day].append((weights.get(company_id, 0), value))
        result = {}
        for day, values in sorted(by_date.items()):
            active_weight = sum(weight for weight, _ in values)
            if active_weight > 0:
                result[day] = sum(weight * value for weight, value in values) / active_weight
        return result

    @staticmethod
    def _compound(returns: list[float]) -> float:
        value = 1.0
        for item in returns:
            value *= 1 + item
        return value - 1

    def _drawdown(self, returns: dict[date, float]) -> dict[str, Any]:
        cumulative = 1.0
        peak = 1.0
        minimum = 0.0
        series = []
        for day, value in returns.items():
            cumulative *= 1 + value
            peak = max(peak, cumulative)
            drawdown = cumulative / peak - 1
            minimum = min(minimum, drawdown)
            series.append({"date": day, "drawdown": drawdown})
        return {"max_drawdown": minimum if returns else None, "series": series}

    @staticmethod
    def _historical_var(
        returns: dict[date, float], confidence: float = 0.95
    ) -> tuple[float | None, float | None]:
        """Historical-simulation VaR/CVaR on the portfolio daily return series.

        VaR is the return at the (1 - confidence) quantile of observed daily
        returns; CVaR (expected shortfall) is the mean of returns at or below
        that quantile. Both are negative numbers for losses. Requires enough
        observations to be meaningful; otherwise (None, None).
        """
        values = sorted(returns.values())
        if len(values) < 20:
            return None, None
        index = max(0, min(len(values) - 1, int(len(values) * (1 - confidence))))
        var = values[index]
        tail = values[: index + 1]
        cvar = mean(tail) if tail else None
        return var, cvar

    def _xirr(
        self, db: Session, positions: list[tuple[Position, Company]]
    ) -> tuple[float | None, dict[str, Any]]:
        """Rentabilidad ponderada por dinero (XIRR) con UNA sola perspectiva.

        Mezclar perspectivas contaba la caja dos veces: flujos de operación
        (compras, ventas, dividendos) más un valor final con la caja del
        bróker, que ya contiene el producto de esas ventas y dividendos
        (compra -1.000, venta +1.100, caja 1.100 -> ~120 % en vez de 10 %).
        Referencia: CFA Institute, Level I, "Money-weighted and time-weighted
        rates of return"; GIPS 2020, glosario "External cash flow".

        - ``account`` (hay depósitos/retiradas registrados): flujos = SOLO
          aportaciones y retiradas externas; valor final = posiciones + caja.
          Compras, ventas, dividendos, comisiones y retenciones son
          movimientos internos y ya están dentro del valor final.
        - ``investment`` (sin depósitos registrados, p. ej. solo operaciones
          o importación ``trades_only``): flujos = compras, ventas, dividendos,
          comisiones y retenciones; valor final = SOLO posiciones (la caja no
          entra, porque sale de esos mismos flujos). ``cash_misc`` no
          identificado como depósito no entra: es un movimiento de caja
          interno o desconocido, no una inversión.
        """
        fx = PortfolioFXService()
        base = fx.base_currency(db)
        cashflows: list[tuple[date, float]] = []
        ambiguous_cash_excluded = 0
        missing_fx: list[dict[str, Any]] = []
        all_transactions = list(db.scalars(select(Transaction).order_by(Transaction.trade_date)).all())
        external = {id(t) for t in all_transactions if _is_external_transfer(t)}
        perspective = "account" if external else "investment"
        # Lote FX: 1 query para todos los flujos (anti N+1 por transacción).
        flow_table = (
            fx.fx_table(
                db,
                currencies={transaction.currency for transaction in all_transactions},
                base_currency=base,
                as_of_max=max((t.trade_date for t in all_transactions), default=None) or date.today(),
            )
            if all_transactions
            else {}
        )
        for transaction in all_transactions:
            action = (transaction.action or "").lower()
            # Only included flows need FX. Internal account movements and
            # unidentified investment cash cannot make this return incomplete.
            if perspective == "account" and id(transaction) not in external:
                continue
            if perspective == "investment" and action == "cash_misc":
                continue
            rate = PortfolioFXService.rate_from_table(
                flow_table,
                quote_currency=transaction.currency,
                base_currency=base,
                as_of=transaction.trade_date,
            )
            if rate is None:
                missing_fx.append(
                    {
                        "kind": "cashflow",
                        "transaction_id": transaction.id,
                        "currency": transaction.currency,
                        "as_of": transaction.trade_date.isoformat(),
                    }
                )
                continue
            # Sign convention: a buy is an outflow, a sell an inflow, a
            # dividend/interest an inflow, and a fee or a withholding tax an
            # OUTFLOW. Fees used to be added to the proceeds of a sale and
            # fee/cash_misc rows were signed as inflows, so a EUR 50 commission
            # turned a 20,00% money-weighted return into 25,00% with status
            # "calculated". Costs must reduce the return they are charged on.
            action = (transaction.action or "").lower()
            if perspective == "account":
                if id(transaction) not in external:
                    # Movimiento interno de la cuenta: ya está en el valor final.
                    continue
                if action == "cash_misc" and not cash_quantity_is_canonical(transaction):
                    ambiguous_cash_excluded += 1
                    continue
                cashflows.append((transaction.trade_date, _external_flow(transaction) * float(rate)))
                continue
            if action == "cash_misc":
                # Perspectiva de inversión: un movimiento de caja sin
                # identificar no es una compra ni una venta.
                continue
            # Buy/sell are share-denominated (quantity x price); cash rows
            # carry the amount in `price` with quantity 0 or 1, so they go
            # through the shared helper: multiplying them by a 0/1 quantity
            # made every quantity-0 dividend invisible to XIRR while the tax
            # report declared it.
            # cash_amount devuelve Decimal: sin float() el net*float(rate) de
            # mas abajo era Decimal*float -> TypeError y GET /intelligence
            # entera caia con cualquier fila cash con FX.
            # Fila cash historica no canonica (quantity distinta de 0/1):
            # cash_amount daria price*quantity como dato cierto mientras el
            # informe fiscal la bloquea. Se excluye del XIRR y se declara la
            # cobertura; incluirla mediría una cifra inventada.
            if is_cash_action(action) and not cash_quantity_is_canonical(transaction):
                ambiguous_cash_excluded += 1
                continue
            gross = (
                float(cash_amount(transaction))
                if is_cash_action(action)
                else float(transaction.quantity) * float(transaction.price)
            )
            fees = float(transaction.fees or 0)
            if action in BUY_ACTIONS:
                net, sign = gross + fees, -1
            elif action in SELL_ACTIONS:
                net, sign = gross - fees, 1
            elif action in {"dividend", "interest"}:
                net, sign = gross, 1
            elif action == "withholding":
                # Retencion con signo segun su origen (``withholding_cost``):
                # IBKR la publica en negativo y su REVERSION en positivo; la
                # entrada manual, en positivo. Un abs() convertia la reversion
                # en otra salida (-15, +15, -15 pesaba -45 en vez de -15).
                net, sign = float(withholding_cost(transaction)), -1
            elif action == "fee":
                # IBKR Flex informa comisiones con importe NEGATIVO y la entrada
                # manual en positivo: el coste siempre es una SALIDA.
                net, sign = abs(gross), -1
            elif action == "cash_misc":
                net, sign = gross, -1
            else:
                net, sign = gross, 1
            amount = net * float(rate)
            cashflows.append((transaction.trade_date, sign * amount))
        if ambiguous_cash_excluded:
            # Un XIRR que excluye un flujo de importe desconocido NO es la
            # rentabilidad completa: publicarlo como "calculated" mediria con
            # una cifra que el informe fiscal bloquea. None + estado explicito.
            return None, {
                "status": "incomplete_ambiguous_cash",
                "cashflows": len(cashflows),
                "ambiguous_cash_excluded": ambiguous_cash_excluded,
                "perspective": perspective,
                "external_flows": len(external),
            }
        ending_value = 0.0
        for position, company in positions:
            value = position.market_value_base
            if value is None and position.market_value > 0:
                # Misma divisa principal pero quizá subunidad: con una posición
                # en GBp market_value está en peniques, y upper() lo daba por
                # libras (x100 en el valor final del XIRR con base GBP).
                pos_major, pos_divisor = normalize_currency(position.currency)
                if pos_major == base:
                    value = position.market_value / pos_divisor
            if value is None:
                missing_fx.append(
                    {
                        "kind": "position",
                        "ticker": company.ticker,
                        "currency": position.currency,
                    }
                )
            else:
                ending_value += float(value)
        # La caja solo entra en el valor final de la perspectiva de CUENTA.
        cash_rows = list(db.scalars(select(CashBalance)).all()) if perspective == "account" else []
        # Lote FX: 1 query para todas las cajas (anti N+1).
        ending_rates = fx.rates_for(
            db,
            quote_currencies={cash.currency for cash in cash_rows},
            base_currency=base,
            as_of=local_today(),
        )
        if perspective == "account" and not cash_rows:
            # Con depositos registrados el valor final DEBE incluir la caja. Sin
            # ninguna fila de caja (p. ej. extracto sin CashReport) la caja
            # desaparece y el XIRR sale sesgado (deposito 1.000, compra 500,
            # posicion 550: -45 % en vez de +5 %). No se inventa la caja: se
            # declara el hueco y no se publica cifra.
            return None, {
                "status": "incomplete_missing_cash_balance",
                "cashflows": len(cashflows),
                "perspective": perspective,
                "external_flows": len(external),
            }
        for cash in cash_rows:
            rate = ending_rates.get(currency_key(cash.currency))
            if rate is not None:
                ending_value += float(cash.balance * rate)
            elif cash.balance:
                missing_fx.append({"kind": "ending_cash", "currency": cash.currency})
        if missing_fx:
            return None, {
                "status": "incomplete_missing_fx",
                "missing_fx": missing_fx,
                "cashflows": len(cashflows),
                "perspective": perspective,
                "external_flows": len(external),
            }
        if ending_value:
            # El valor final va fechado hoy en Madrid: una compra de hoy (fecha
            # de Madrid) no puede quedar después del final del XIRR.
            cashflows.append((local_today(), ending_value))
        if len(cashflows) < 2 or not any(value < 0 for _, value in cashflows):
            return None, {
                "status": "insufficient_cashflows",
                "cashflows": len(cashflows),
                "ambiguous_cash_excluded": ambiguous_cash_excluded,
                "perspective": perspective,
                "external_flows": len(external),
            }
        origin = min(day for day, _ in cashflows)

        def npv(rate: float) -> float:
            return sum(value / ((1 + rate) ** ((day - origin).days / 365.0)) for day, value in cashflows)

        low, high = -0.9999, 10.0
        if npv(low) * npv(high) > 0:
            return None, {
                "status": "no_xirr_root",
                "cashflows": len(cashflows),
                "ambiguous_cash_excluded": ambiguous_cash_excluded,
                "perspective": perspective,
                "external_flows": len(external),
            }
        for _ in range(200):
            middle = (low + high) / 2
            if abs(npv(middle)) < 1e-8:
                break
            if npv(low) * npv(middle) <= 0:
                high = middle
            else:
                low = middle
        return middle, {
            "status": "calculated",
            "method": "bisection_xirr",
            "cashflows": len(cashflows),
            "ambiguous_cash_excluded": ambiguous_cash_excluded,
            "perspective": perspective,
            "external_flows": len(external),
        }

    # Pearson con muy pocas sesiones compartidas es ruido con aspecto de
    # medida (con n~14 salen -0,5 por azar). Se exige un minimo de
    # observaciones solapadas, alineado con el de _beta, y el conteo se
    # publica para que la UI pueda explicar cada N/D.
    MIN_CORRELATION_OBSERVATIONS = 20

    @classmethod
    def _correlations(
        cls, returns: dict[int, dict[date, float]], rows: list[tuple[Position, Company]]
    ) -> tuple[dict[str, dict[str, float | None]], dict[str, dict[str, int]]]:
        result: dict[str, dict[str, float | None]] = {}
        observations: dict[str, dict[str, int]] = {}
        # La matriz es simetrica (corr(a, b) == corr(b, a) bit a bit: mismos
        # productos y mismas sumas en el mismo orden), asi que cada par se
        # calcula una vez. La media de cada serie sobre unas fechas dadas se
        # reutiliza entre pares: statistics.mean es exacta pero cara, y antes
        # se recalculaba 2 veces por par (684 medias con 19 posiciones).
        # Igual para las desviaciones y su suma de cuadrados: dependen solo de
        # (serie, fechas), no del par. Mismas operaciones en el mismo orden que
        # antes, asi que el coeficiente sale identico bit a bit; solo se dejan
        # de repetir 2 de las 3 sumas por par (30 posiciones = 435 pares).
        # Fechas de cada serie ordenadas UNA vez: antes la interseccion se
        # ordenaba por par (O(P^2) sorts de ~D fechas; con 500 posiciones,
        # ~125.000 sorts de ~1.400 fechas, la mitad del tiempo del endpoint).
        sorted_dates: dict[int, tuple[date, ...]] = {
            company.id: tuple(sorted(returns.get(company.id, ()))) for _, company in rows
        }
        # Clases de calendario: series con exactamente las mismas fechas (lo
        # habitual: mismo calendario bursatil) comparten UN objeto canonico,
        # asi la interseccion dentro de la clase es una comprobacion de
        # identidad O(1) por par en vez de un barrido O(D).
        _by_hash: dict[int, list[tuple[date, ...]]] = {}
        for cid, dates in sorted_dates.items():
            bucket = _by_hash.setdefault(hash(dates), [])
            for existing in bucket:
                if existing == dates:
                    sorted_dates[cid] = existing
                    break
            else:
                bucket.append(dates)
        # Tuplas de fechas canonicas por CONTENIDO (un hash O(D) por par, no
        # dos por desviacion): todos los pares con el mismo calendario comun
        # comparten objeto, asi las desviaciones se calculan una vez por
        # (serie, calendario) aunque la interseccion salga de pares distintos.
        canon: dict[tuple[date, ...], tuple[date, ...]] = {dates: dates for dates in sorted_dates.values()}
        # Desviaciones por (serie, id de tupla canonica): hash O(1) por par.
        # La tupla determina el calculo, y tuplas con el mismo contenido
        # producen desviaciones identicas.
        deviations: dict[tuple[int, int], tuple[list[float], float]] = {}

        def _cached_deviations(
            company_id: int, series: dict[date, float], dates: tuple[date, ...]
        ) -> tuple[list[float], float]:
            key = (company_id, id(dates))
            cached = deviations.get(key)
            if cached is None:
                values = [series[day] for day in dates]
                centre = mean(values)
                deltas = [value - centre for value in values]
                cached = (deltas, sum(delta**2 for delta in deltas))
                deviations[key] = cached
            return cached

        def _common_dates(
            left_id: int, left: dict[date, float], right_id: int, right: dict[date, float]
        ) -> tuple[date, ...]:
            """Interseccion ordenada de fechas, bit a bit igual que
            tuple(sorted(left.keys() & right.keys())) pero sin re-ordenar:
            si una serie contiene a la otra se reutiliza su tupla ya ordenada.
            """
            left_dates = sorted_dates[left_id]
            right_dates = sorted_dates[right_id]
            if left_dates is right_dates:
                return left_dates
            if len(left_dates) <= len(right_dates):
                small_dates, big, big_dates = left_dates, right, right_dates
            else:
                small_dates, big, big_dates = right_dates, left, left_dates
            common = 0
            for day in small_dates:
                if day in big:
                    common += 1
            if common == len(small_dates):
                candidate = small_dates
            elif common == len(big_dates):
                candidate = big_dates
            else:
                candidate = tuple(day for day in small_dates if day in big)
            return canon.setdefault(candidate, candidate)

        computed: dict[tuple[int, int], tuple[float | None, int]] = {}
        for _, left_company in rows:
            result[left_company.ticker] = {}
            observations[left_company.ticker] = {}
            for _, right_company in rows:
                mirrored = computed.get((right_company.id, left_company.id))
                if mirrored is not None:
                    correlation, count = mirrored
                    observations[left_company.ticker][right_company.ticker] = count
                    result[left_company.ticker][right_company.ticker] = correlation
                    continue
                left = returns.get(left_company.id, {})
                right = returns.get(right_company.id, {})
                dates = _common_dates(left_company.id, left, right_company.id, right)
                observations[left_company.ticker][right_company.ticker] = len(dates)
                if left_company.id == right_company.id and dates:
                    correlation: float | None = 1.0
                elif len(dates) < cls.MIN_CORRELATION_OBSERVATIONS:
                    # Historico insuficiente: N/D, no un coeficiente de ruido.
                    correlation = None
                else:
                    x_dev, x_ss = _cached_deviations(left_company.id, left, dates)
                    y_dev, y_ss = _cached_deviations(right_company.id, right, dates)
                    # sum(map(mul, ...)) suma los mismos productos en el mismo
                    # orden que el generador con zip: identico bit a bit, ~2x
                    # mas rapido al ejecutar la multiplicacion en C.
                    numerator = sum(map(mul, x_dev, y_dev))
                    denominator = math.sqrt(x_ss * y_ss)
                    correlation = numerator / denominator if denominator else None
                computed[(left_company.id, right_company.id)] = (correlation, len(dates))
                result[left_company.ticker][right_company.ticker] = correlation
        return result, observations

    @staticmethod
    def _beta(
        db: Session, portfolio_returns: dict[date, float], cutoff: date
    ) -> tuple[float | None, dict[str, Any]]:
        prices = _benchmark_prices(db, cutoff)
        if prices is None:
            return None, {"status": "missing_benchmark", "benchmark": "SPY"}
        benchmark_returns = PortfolioIntelligenceService._returns(prices)
        dates = sorted(portfolio_returns.keys() & benchmark_returns.keys())
        if len(dates) < 20:
            return None, {"status": "insufficient_overlap", "observations": len(dates)}
        portfolio = [portfolio_returns[day] for day in dates]
        market = [benchmark_returns[day] for day in dates]
        market_mean = mean(market)
        # La media de la cartera se calcula UNA vez: dentro del generador se
        # recalculaba por cada observacion (O(n^2); ~1.250 medias exactas de
        # ~1.250 valores con 5 años de historia).
        portfolio_mean = mean(portfolio)
        variance = sum((value - market_mean) ** 2 for value in market)
        covariance = sum(
            (left - portfolio_mean) * (right - market_mean) for left, right in zip(portfolio, market)
        )
        return (
            covariance / variance if variance else None,
            {"status": "calculated", "benchmark": "SPY", "observations": len(dates)},
        )

    def _ledger_contribution(
        self, db: Session, rows: list[tuple[Position, Company]], cutoff: date
    ) -> dict[str, Any]:
        """Per-position P&L contribution over the horizon from the full ledger.

        For each held company: contribution = end value - start value
        - net invested + income, where start value reconstructs the quantity
        held at the horizon cutoff from every prior transaction (the ledger
        is split-adjusted through corporate actions) priced at the last
        close before the cutoff, and net invested sums buys minus sells
        inside the horizon. All flows convert to base currency with
        point-in-time FX; rows without a pre-cutoff price or FX rate get a
        null contribution with an explicit reason instead of an estimate.
        """
        fx = PortfolioFXService()
        base = fx.base_currency(db)
        company_ids = [company.id for _, company in rows]
        empty = {
            "positions": [],
            "total_pnl": None,
            "coverage": {"positions": len(rows), "with_contribution": 0, "reasons": {}},
            "methodology": "ledger_reconstruction_v1",
        }
        if not company_ids:
            return empty

        transactions = list(
            db.scalars(
                select(Transaction)
                .where(Transaction.company_id.in_(company_ids))
                .order_by(Transaction.trade_date)
            ).all()
        )
        by_company: dict[int, list[Transaction]] = defaultdict(list)
        for transaction in transactions:
            if transaction.company_id is not None:
                by_company[transaction.company_id].append(transaction)

        flow_table = fx.fx_table(
            db,
            currencies={t.currency for t in transactions} | {p.currency for p, _ in rows},
            base_currency=base,
            as_of_max=date.today(),
        )

        # Last close strictly before the cutoff per company, bounded in SQL:
        # row_number() OVER (PARTITION BY company ORDER BY date DESC, id DESC)
        # = 1 returns EXACTLY one row per company, deterministic even for
        # same-date ties (the model forbids them with
        # uq_market_price_company_date since migration 0001; the window makes
        # the selection deterministic by construction, and MAX(date)+join
        # would return every tied row and pick one by undefined order). Only
        # the used columns are projected (company_id, date, adj_close); the
        # full pre-cutoff history was loaded as ORM rows before.
        ranked_prior = (
            select(
                MarketPrice.id.label("id"),
                func.row_number()
                .over(
                    partition_by=MarketPrice.company_id,
                    order_by=(MarketPrice.date.desc(), MarketPrice.id.desc()),
                )
                .label("rn"),
            )
            .where(MarketPrice.company_id.in_(company_ids), MarketPrice.date < cutoff)
            .subquery("bounded_prior_prices")
        )
        prior_prices: dict[int, Any] = {}
        for price in db.execute(
            select(MarketPrice.company_id, MarketPrice.date, MarketPrice.adj_close)
            .join(ranked_prior, ranked_prior.c.id == MarketPrice.id)
            .where(ranked_prior.c.rn == 1)
        ).all():
            prior_prices[price.company_id] = price

        positions_out = []
        reasons: dict[str, int] = defaultdict(int)
        total_pnl = 0.0
        with_contribution = 0
        for position, company in rows:
            ledger = by_company.get(company.id, [])
            # Reconciliación: los legs buy/sell deben reconstruir la cantidad
            # actual. Sin legs (solo dividendos) o con ledger parcial (compra
            # de 1 acción sobre una posición de 10), la fórmula contribution =
            # end_value - start - buys + sells + income pinta el valor íntegro
            # de la posición como ganancia inventada. Nulo honesto.
            buy_legs = sum(float(t.quantity) for t in ledger if t.action == "buy")
            sell_legs = sum(float(t.quantity) for t in ledger if t.action == "sell")
            current_qty = float(position.quantity)
            reconciliation: str | None = None
            if buy_legs == 0 and sell_legs == 0:
                reconciliation = "missing_ledger"
            elif abs((buy_legs - sell_legs) - current_qty) > max(1e-6, abs(current_qty) * 1e-6):
                reconciliation = "incomplete_ledger"
            if reconciliation is not None:
                reasons[reconciliation] += 1
                positions_out.append(
                    {
                        "ticker": company.ticker,
                        "contribution_pnl": None,
                        "end_value": (
                            float(position.market_value_base)
                            if position.market_value_base is not None
                            else None
                        ),
                        "start_value": None,
                        "net_invested": None,
                        "income": None,
                        "reason": reconciliation,
                    }
                )
                continue
            qty_at_cutoff = 0.0
            buys = 0.0
            sells = 0.0
            income = 0.0
            fx_missing = False
            for transaction in ledger:
                rate = PortfolioFXService.rate_from_table(
                    flow_table,
                    quote_currency=transaction.currency,
                    base_currency=base,
                    as_of=transaction.trade_date,
                )
                if rate is None:
                    fx_missing = True
                    continue
                amount = float(transaction.quantity * transaction.price) * float(rate)
                fees = float(transaction.fees or 0) * float(rate)
                if transaction.trade_date < cutoff:
                    if transaction.action == "buy":
                        qty_at_cutoff += float(transaction.quantity)
                    elif transaction.action == "sell":
                        qty_at_cutoff -= float(transaction.quantity)
                else:
                    if transaction.action == "buy":
                        buys += amount + fees
                    elif transaction.action == "sell":
                        sells += amount - fees
                    elif transaction.action in {"dividend", "interest"}:
                        income += amount
            start_price_row = prior_prices.get(company.id)
            start_rate = (
                PortfolioFXService.rate_from_table(
                    flow_table,
                    quote_currency=position.currency,
                    base_currency=base,
                    as_of=start_price_row.date,
                )
                if start_price_row is not None
                else None
            )
            end_value = float(position.market_value_base) if position.market_value_base is not None else None
            reason = None
            contribution = None
            if end_value is None:
                reason = "missing_end_value"
            elif fx_missing:
                reason = "missing_fx"
            elif qty_at_cutoff > 0 and (start_price_row is None or not start_price_row.adj_close):
                reason = "missing_start_price"
            elif qty_at_cutoff > 0 and start_rate is None:
                reason = "missing_start_fx"
            start_value: float | None = None
            if reason is None:
                start_value = (
                    qty_at_cutoff * float(start_price_row.adj_close) * float(start_rate)
                    if qty_at_cutoff > 0 and start_price_row is not None and start_rate is not None
                    else 0.0
                )
                contribution = end_value - start_value - buys + sells + income
                total_pnl += contribution
                with_contribution += 1
            else:
                reasons[reason] += 1
            positions_out.append(
                {
                    "ticker": company.ticker,
                    "contribution_pnl": contribution,
                    "end_value": end_value,
                    "start_value": start_value,
                    "net_invested": buys - sells,
                    "income": income,
                    "reason": reason,
                }
            )
        for entry in positions_out:
            entry["contribution_share"] = (
                entry["contribution_pnl"] / total_pnl
                if entry["contribution_pnl"] is not None and total_pnl != 0
                else None
            )
        return {
            "positions": positions_out,
            "total_pnl": total_pnl if with_contribution else None,
            "coverage": {
                "positions": len(rows),
                "with_contribution": with_contribution,
                "reasons": dict(reasons),
            },
            "methodology": "ledger_reconstruction_v1",
            "base_currency": base,
        }

    def _benchmark_comparison(
        self, db: Session, portfolio_returns: dict[date, float], cutoff: date
    ) -> dict[str, Any]:
        """Portfolio vs SPY over the horizon: returns, alpha, tracking error.

        Honest states: missing_benchmark (SPY not ingested) and
        insufficient_overlap (<20 shared trading days) surface as status
        with null metrics instead of fabricated numbers.
        """
        base: dict[str, Any] = {
            "symbol": "SPY",
            "benchmark_twr": None,
            "benchmark_annualized": None,
            "portfolio_annualized": None,
            "alpha_annualized": None,
            "tracking_error": None,
            "information_ratio": None,
            "observations": 0,
        }
        prices = _benchmark_prices(db, cutoff)
        if prices is None:
            return {**base, "status": "missing_benchmark"}
        benchmark_returns = self._returns(prices)
        dates = sorted(portfolio_returns.keys() & benchmark_returns.keys())
        if len(dates) < 20:
            return {**base, "status": "insufficient_overlap", "observations": len(dates)}
        port = [portfolio_returns[day] for day in dates]
        bench = [benchmark_returns[day] for day in dates]
        bench_twr = self._compound(bench)
        # Las cifras anualizadas del benchmark se guian por SUS observaciones
        # solapadas (no por las del portfolio global): con menos de 60 sesiones
        # compartidas, extrapolar a un ano no es informativo.
        annualize = len(dates) >= MIN_ANNUALIZATION_SESSIONS
        bench_annualized = (1 + bench_twr) ** (252 / len(bench)) - 1 if annualize and bench_twr > -1 else None
        port_twr = self._compound(port)
        port_annualized = (1 + port_twr) ** (252 / len(port)) - 1 if annualize and port_twr > -1 else None
        active = [p - b for p, b in zip(port, bench)]
        tracking_error = pstdev(active) * math.sqrt(252) if len(active) >= 2 else None
        alpha = (
            port_annualized - bench_annualized
            if port_annualized is not None and bench_annualized is not None
            else None
        )
        information_ratio = (
            alpha / tracking_error
            # A near-zero tracking error would turn rounding noise into an
            # absurd ratio; treat it as undefined instead.
            if alpha is not None and tracking_error is not None and tracking_error > 1e-6
            else None
        )
        return {
            **base,
            "status": "calculated",
            "benchmark_twr": bench_twr,
            "benchmark_annualized": bench_annualized,
            "portfolio_annualized": port_annualized,
            "alpha_annualized": alpha,
            "tracking_error": tracking_error,
            "information_ratio": information_ratio,
            "observations": len(dates),
        }

    @staticmethod
    def _exposures(
        rows: list[tuple[Position, Company]],
        total_value: float,
        base_values: dict[int, float] | None = None,
    ) -> dict[str, dict[str, float]]:
        exposures: dict[str, dict[str, float]] = {
            "sectors": defaultdict(float),
            "countries": defaultdict(float),
            "currencies": defaultdict(float),
            "factors": defaultdict(float),
        }
        for position, company in rows:
            if base_values is None:
                # nosemgrep: gerarai-money-none-to-zero -- rama muerta: la unica llamada (linea 321) pasa siempre base_values
                value = float(position.market_value_base or 0)
            else:
                value = base_values.get(position.id)
                if value is None:
                    # No honest base-currency value: reported in missing_fx,
                    # never silently counted as zero exposure.
                    continue
            weight = value / total_value if total_value else 0
            exposures["sectors"][company.sector] += weight
            country = company.domicile_country or EXCHANGE_COUNTRY.get(company.exchange.upper(), "Unknown")
            exposures["countries"][country] += weight
            exposures["currencies"][position.currency] += weight
            for factor in company.factor_tags:
                exposures["factors"][factor] += weight
        return {key: dict(value) for key, value in exposures.items()}

    @staticmethod
    def _period_fx_return(
        fx_table: dict[tuple[str, str], list[tuple[date, Decimal]]],
        position: Position,
        base_currency: str,
        period_start: date,
        period_end: date,
    ) -> float | None:
        """Retorno FX del periodo de la divisa de cotizacion, no su nivel.

        ``Position.fx_rate`` es el tipo de cambio SPOT a fecha ``as_of``: un
        nivel, nunca una variacion. Restarle 1 fabricaba una contribucion
        permanente (fx_rate 0,92 -> -8% de FX para siempre) y esa misma
        cifra inventada se restaba del residuo ``multiple``. El componente
        correcto es el retorno del periodo ``fx_fin / fx_en_corte - 1``.

        Ambas patas se anclan al periodo REAL de la serie de precios:
        inicio en ``period_start`` (primera barra, no un cutoff generico que
        puede quedar meses antes) y fin en ``period_end`` (ultima barra).
        Anclar el inicio al cutoff cuando la primera barra es posterior
        mediria un tramo de FX fuera del periodo atribuido. El spot de
        ``Position.fx_rate`` solo sirve como pata final si su ``as_of`` no
        es anterior al inicio del periodo.

        Frescura exigida en AMBAS patas (tolerancia de fin de semana /
        festivo corto): una tasa demasiado vieja respecto a su ancla deja
        el componente en None; nunca se publica un retorno medido con
        fechas cambiadas ni un cero fabricado reutilizando una sola tasa.
        """
        currency = position.currency or ""
        if not currency:
            return None
        start = _fx_rate_with_date(
            fx_table,
            quote_currency=currency,
            base_currency=base_currency,
            as_of=period_start,
        )
        end = _fx_rate_with_date(
            fx_table,
            quote_currency=currency,
            base_currency=base_currency,
            as_of=period_end,
        )
        if end is None and position.fx_rate is not None and position.as_of is not None:
            if position.as_of >= period_start:
                end = (position.as_of, Decimal(str(position.fx_rate)))
        if start is None or end is None:
            return None
        (start_date, start_rate), (end_date, end_rate) = start, end
        # Tolerancia explicita de frescura en AMBAS patas respecto a su
        # ancla del periodo: sin ella, con una sola tasa del 1/ene y barra
        # final en junio la MISMA fila servia de pata inicial y final y
        # publicaba 0,0% medido (cero fabricado con fx_known=True), y un FX
        # inicial de 2020 con cutoff 2026 publicaba la variacion de anos
        # como retorno del periodo. Un hueco mayor que la tolerancia (fin
        # de semana / festivo corto) deja el componente en None.
        if end_date < period_end - _FX_LEG_TOLERANCE:
            return None
        if start_date < period_start - _FX_LEG_TOLERANCE:
            return None
        if end_date < period_start or end_date < start_date or not start_rate or not end_rate:
            return None
        return float(end_rate / start_rate - 1)

    # Una posicion medida en una ventana mucho menor que la del panel
    # (p.ej. 3 semanas de precios bajo un encabezado de 1 ano) se marca
    # como historial parcial y se excluye de los totales agregados: sumar
    # retornos de horizontes distintos publicaba un total sin sentido.
    PARTIAL_WINDOW_RATIO = 0.5

    def _attribution(
        self,
        db: Session,
        rows: list[tuple[Position, Company]],
        weights: dict[int, float],
        price_series: dict[int, list[MarketPrice]],
        cutoff: date,
    ) -> dict[str, Any]:
        positions = []
        # Totales null-propagantes: un componente desconocido en cualquier
        # posicion deja el agregado en None (incompletitud declarada); sumar
        # None como 0 publicaba parciales con pinta de totales.
        totals: dict[str, float | None] = {}
        company_ids = [company.id for _, company in rows]
        fx = PortfolioFXService()
        base_currency = fx.base_currency(db)
        # Lote FX: una tabla para todo el horizonte (anti N+1), resuelta en
        # memoria igual que _ledger_contribution.
        fx_table = (
            fx.fx_table(
                db,
                currencies={position.currency for position, _ in rows if position.currency} | {base_currency},
                base_currency=base_currency,
                as_of_max=date.today(),
            )
            if rows
            else {}
        )
        # Lote: 1 query de facts + 1 de dividendos para todas las posiciones
        # (anti N+1 por compañía en attribution).
        all_facts: dict[int, dict[str, list[FinancialFact]]] = defaultdict(lambda: defaultdict(list))
        if company_ids:
            for fact in db.scalars(
                select(FinancialFact)
                .where(
                    FinancialFact.company_id.in_(company_ids),
                    FinancialFact.metric.in_(["eps_diluted", "eps", "shares_diluted"]),
                )
                .order_by(FinancialFact.company_id, FinancialFact.fiscal_year)
            ).all():
                all_facts[fact.company_id][fact.metric].append(fact)
        all_dividends: dict[int, float] = defaultdict(float)
        ambiguous_dividends: set[int] = set()
        companies_with_dividend_rows: set[int] = set()
        if company_ids:
            for dividend in db.scalars(
                select(Transaction).where(
                    Transaction.company_id.in_(company_ids),
                    Transaction.action == "dividend",
                )
            ).all():
                if dividend.company_id is None:
                    continue
                if not cash_quantity_is_canonical(dividend):
                    # Fila historica no canonica: el importe derivado de
                    # price es candidato (revision fiscal), no dato cierto.
                    # El componente de dividendos de la compania queda
                    # desconocido y la incompletitud se propaga al total.
                    ambiguous_dividends.add(dividend.company_id)
                    continue
                all_dividends[dividend.company_id] += float(cash_amount(dividend))
                companies_with_dividend_rows.add(dividend.company_id)
        for position, company in rows:
            prices = price_series.get(company.id, [])
            # El ratio exige AMBOS extremos ajustados: con historica ajustada
            # al inicio y una fila spot (adj_close NULL) al final, dividir
            # lanzaba TypeError al abrir /portfolio/intelligence. Los huecos
            # intermedios no afectan: el ratio solo usa los extremos.
            total_return = (
                float(prices[-1].adj_close / prices[0].adj_close - 1)
                if len(prices) >= 2 and prices[0].adj_close and prices[-1].adj_close
                else None
            )
            # Los componentes fundamentales se miden en el MISMO horizonte que el
            # retorno de precio. Antes usaban toda la historia de facts (ASTS:
            # acciones x3 desde el inicio) frente a un retorno de 5 anos, y la
            # atribucion salia con dilucion de -212 % o multiplos absurdos.
            window_start = (prices[0].date if prices else cutoff).year
            window_end = (prices[-1].date if prices else date.today()).year
            by_metric = {
                metric: self._window_facts(rows_, window_start, window_end)
                for metric, rows_ in all_facts.get(company.id, {}).items()
            }
            # eps_diluted is the ingested key; eps is a legacy alias (F376).
            fundamental_growth = self._series_change(by_metric.get("eps_diluted") or by_metric.get("eps", []))
            share_change = self._series_change(by_metric.get("shares_diluted", []))
            # Sin cifras de acciones en el horizonte no hay recompras ni
            # dilucion que medir: N/D, no un 0,0 % que parece medido.
            dilution = max(share_change, 0) if share_change is not None else None
            buybacks = max(-share_change, 0) if share_change is not None else None
            # Sin ningun dividendo en el registro no se distingue "no paga"
            # de "no esta registrado": N/D en vez de 0,0 %.
            dividends_known = (
                company.id not in ambiguous_dividends and company.id in companies_with_dividend_rows
            )
            dividends = all_dividends.get(company.id, 0.0)
            dividend_return = (
                dividends / float(position.cost_basis_native)
                if dividends_known and position.cost_basis_native and position.cost_basis_native > 0
                else None
            )
            period_start = prices[0].date if prices else cutoff
            period_end = prices[-1].date if prices else cutoff
            fx_component = self._period_fx_return(fx_table, position, base_currency, period_start, period_end)
            # El residuo se queda en None cuando el retorno total o el de FX
            # son desconocidos: restar un componente no medido (o medir uno
            # con un nivel) daria una cifra con apariencia de cierre.
            multiple = (
                total_return
                - (fundamental_growth or 0)
                - dividend_return
                - (buybacks or 0)
                + (dilution or 0)
                - fx_component
                if total_return is not None and fx_component is not None and dividend_return is not None
                else None
            )
            components = {
                "fundamental_growth": fundamental_growth,
                "multiple": multiple,
                "dividends": dividend_return,
                "buybacks": buybacks,
                "dilution": -dilution if dilution is not None else None,
                "fx": fx_component,
                "sizing": (total_return * weights.get(company.id, 0) if total_return is not None else None),
            }
            positions.append(
                {
                    "ticker": company.ticker,
                    "weight": weights.get(company.id, 0),
                    "total_return": total_return,
                    "period_start": period_start.isoformat() if prices else None,
                    "period_end": period_end.isoformat() if prices else None,
                    "period_days": (period_end - period_start).days if prices else None,
                    "fx_known": fx_component is not None,
                    "dividends_known": dividends_known,
                    "components": components,
                }
            )
        starts = [p["period_start"] for p in positions if p["period_start"]]
        ends = [p["period_end"] for p in positions if p["period_end"]]
        window_start = min(starts) if starts else None
        window_end = max(ends) if ends else None
        window_days = (
            (date.fromisoformat(window_end) - date.fromisoformat(window_start)).days
            if window_start and window_end
            else 0
        )
        # Marca de historial parcial y exclusion de los totales: la ventana
        # medida de la posicion cubre menos de PARTIAL_WINDOW_RATIO de la
        # ventana del panel. La fila se muestra con su fecha real; solo sale
        # del agregado.
        partial_tickers: list[str] = []
        for row_ in positions:
            partial = bool(
                window_days > 0
                and row_["period_days"] is not None
                and row_["period_days"] < self.PARTIAL_WINDOW_RATIO * window_days
            )
            row_["partial_history"] = partial
            if partial:
                partial_tickers.append(row_["ticker"])
                continue
            for key, value in row_["components"].items():
                if key not in totals:
                    totals[key] = value
                elif totals[key] is not None and value is not None:
                    totals[key] += value
                else:
                    totals[key] = None
        return {
            "basis": "adjusted_price_return",
            "period_start": window_start,
            "period_end": window_end,
            "portfolio_components": dict(totals),
            "incomplete_components": sorted(key for key, value in totals.items() if value is None),
            "excluded_partial_histories": sorted(partial_tickers),
            "positions": positions,
        }

    @staticmethod
    def _window_facts(series: list[FinancialFact], start_year: int, end_year: int) -> list[FinancialFact]:
        """Facts anuales cuyo ano fiscal cae dentro del horizonte del retorno de precio."""
        return [
            row for row in series if row.fiscal_year is not None and start_year <= row.fiscal_year <= end_year
        ]

    @staticmethod
    def _series_change(series: list[FinancialFact]) -> float | None:
        # Homogeneous annual series only (F376 audit): quarterly rows (Q1-Q4)
        # must not be compared with full-year values; one value per fiscal year.
        by_year: dict[int, FinancialFact] = {}
        for row in sorted(series, key=lambda r: r.fiscal_year if r.fiscal_year is not None else 0):
            if row.fiscal_year is None or (row.fiscal_quarter or "").upper().startswith("Q"):
                continue
            by_year.setdefault(row.fiscal_year, row)
        annual = [by_year[y] for y in sorted(by_year)]
        if len(annual) < 2 or not annual[0].value:
            return None
        return float(annual[-1].value / annual[0].value - 1)
