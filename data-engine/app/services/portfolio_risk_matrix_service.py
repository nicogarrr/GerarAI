"""Panel de riesgo de cartera: covarianza Ledoit-Wolf y contribucion por posicion.

Delta sobre GET /portfolio/intelligence (que ya publica correlaciones
Pearson por pares y concentracion): aqui la covarianza es UN objeto
consistente (muestral encogida hacia mu*I, Ledoit-Wolf 2004, implementado
en app/valuation/risk_matrix.py y verificado contra sklearn), y de ella se
derivan la correlacion mostrada y la contribucion al riesgo por posicion
con los pesos actuales. Sin optimizador ni recomendaciones de compra.

Reglas de honestidad (mismo patron que intelligence):
- Inclusion en la matriz exige >= MIN_MATRIX_SESSIONS retornos en las
  fechas comunes; quien no llega queda en `excluded` con motivo y conteo.
- Las posiciones en otra divisa se convierten a divisa base con el
  historico FX diario (quote x rate = base); los retornos sin tasa
  disponible al inicio del historico FX se recortan y se declaran. Si el
  recorte deja la serie bajo el minimo, la posicion se excluye declarada:
  nunca se mezcla divisa de cotizacion con divisa base sin avisar
  (warning `fx_conversion` para la UI).
- Si las fechas comunes no llegan al minimo, las matrices son null y la
  correlacion cae al Pearson por pares de intelligence (>= 20 solapadas),
  con `correlation.source` declarandolo.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, FXRate, MarketPrice, Position
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from app.services.provenance import Coverage, SourceKind, provenance
from app.valuation.currency import normalize_currency
from app.valuation.risk_matrix import (
    ANNUALIZATION_FACTOR,
    correlation_from_covariance,
    ledoit_wolf_covariance,
    risk_contributions,
)

# 60 sesiones comunes: la misma convencion que MIN_ANNUALIZATION_SESSIONS
# de intelligence para anualizar; menos que eso anualiza ruido.
MIN_MATRIX_SESSIONS = 60
# 400 dias naturales cubren ~252 sesiones con margen para festivos.
WINDOW_DAYS = 400

STATUS_OK = "ok"
STATUS_NO_POSITIONS = "no_positions"
STATUS_INSUFFICIENT = "insufficient_history"


def _fx_series_by_pair(
    db: Session, *, base_currency: str, quote_currencies: set[str], since: date
) -> dict[str, tuple[list[date], list[float], str]]:
    """Series FX diarias por divisa de cotizacion: (fechas, tasas, direccion).

    quote x rate = base. Directa (base=B, quote=C) preferida; si no hay
    filas directas, la inversa (base=C, quote=B) invertida. Una sola query
    para todas las divisas (anti N+1), como el lote de precios de
    intelligence.
    """
    if not quote_currencies:
        return {}
    base, base_divisor = normalize_currency(base_currency)
    base = base or base_currency
    normalized: dict[str, tuple[str, float]] = {}
    for raw in quote_currencies:
        quote, quote_divisor = normalize_currency(raw)
        # factor divisor: misma correccion que rate_with_provenance
        # (GBp vs GBP); con divisores 1 es 1.0.
        normalized[raw] = (quote or raw, float(base_divisor) / float(quote_divisor))
    quotes = {quote for quote, _ in normalized.values()}
    rows = list(
        db.execute(
            select(FXRate.base_currency, FXRate.quote_currency, FXRate.rate_date, FXRate.rate)
            .where(
                FXRate.rate_date <= date.today(),
                FXRate.rate_date >= since - timedelta(days=31),
                (
                    ((FXRate.base_currency == base) & FXRate.quote_currency.in_(quotes))
                    | ((FXRate.quote_currency == base) & FXRate.base_currency.in_(quotes))
                ),
            )
            .order_by(FXRate.rate_date)
        ).all()
    )
    direct: dict[str, list[tuple[date, float]]] = {}
    inverse: dict[str, list[tuple[date, float]]] = {}
    for row_base, row_quote, rate_date, rate in rows:
        if not rate or float(rate) <= 0:
            continue
        if row_base == base:
            direct.setdefault(row_quote, []).append((rate_date, float(rate)))
        else:
            inverse.setdefault(row_base, []).append((rate_date, 1.0 / float(rate)))
    result: dict[str, tuple[list[date], list[float], str]] = {}
    for raw, (quote, factor) in normalized.items():
        chosen = direct.get(quote)
        direction = "direct"
        if not chosen:
            chosen = inverse.get(quote)
            direction = "inverse"
        if not chosen:
            continue
        dates = [day for day, _ in chosen]
        rates = [rate * factor for _, rate in chosen]
        result[raw] = (dates, rates, direction)
    return result


def _convert_returns_to_base(
    returns: dict[date, float], fx: tuple[list[date], list[float], str]
) -> tuple[dict[date, float], int]:
    """r_base(d) = (1 + r_quote(d)) * fx(d)/fx(d_prev) - 1.

    fx(d) es la ultima tasa con rate_date <= d (carry-forward: fines de
    semana y festivos usan la ultima tasa conocida, misma politica que
    rate_with_provenance). d_prev es la fecha del retorno anterior de la
    serie de precios. Los retornos anteriores a la primera tasa FX no
    tienen conversion posible: se recortan y se cuentan (declarado), no
    se fabrican.
    """
    fx_dates, fx_rates, _ = fx
    ordered_dates = sorted(returns)
    converted: dict[date, float] = {}
    dropped = 0

    def rate_at(day: date) -> float | None:
        index = bisect_right(fx_dates, day) - 1
        return fx_rates[index] if index >= 0 else None

    for previous, current in zip(ordered_dates, ordered_dates[1:] + [None]):
        if current is None:
            break
        rate_current = rate_at(current)
        rate_previous = rate_at(previous)
        if rate_current is None or rate_previous is None or rate_previous == 0:
            dropped += 1
            continue
        converted[current] = (1.0 + returns[current]) * (rate_current / rate_previous) - 1.0
    return converted, dropped


class PortfolioRiskMatrixService:
    def build(self, db: Session) -> dict[str, Any]:
        today = date.today()
        cutoff = today - timedelta(days=WINDOW_DAYS)
        fx = PortfolioFXService()
        base_currency = fx.base_currency(db)
        rows = list(
            db.execute(select(Position, Company).join(Company, Position.company_id == Company.id)).all()
        )
        if not rows:
            return self._empty(today, base_currency)

        # Pesos por valor de mercado en divisa base: la misma valoracion
        # honesta que intelligence (sin valor base -> excluido declarado).
        base_values: dict[int, float] = {}
        excluded: list[dict[str, Any]] = []
        for position, company in rows:
            value_base = position.market_value_base
            if (
                value_base is None
                and position.currency == base_currency
                and (position.market_value_native or position.market_value) > 0
            ):
                value_base = position.market_value_native or position.market_value
            if value_base is None or float(value_base) <= 0:
                excluded.append(
                    {
                        "ticker": company.ticker,
                        "reason": "no_valuation",
                        "sessions": 0,
                    }
                )
                continue
            base_values[position.id] = float(value_base)
        total_value = sum(base_values.values())
        weights = {
            company.id: (base_values[position.id] / total_value if total_value > 0 else 0.0)
            for position, company in rows
            if position.id in base_values
        }
        weight_by_ticker = {
            company.ticker: weights[company.id] for _, company in rows if company.id in weights
        }
        concentration = {
            "top_1": max(weights.values(), default=0.0),
            "top_5": sum(sorted(weights.values(), reverse=True)[:5]),
            "herfindahl": sum(weight**2 for weight in weights.values()),
            "effective_positions": (
                1.0 / sum(weight**2 for weight in weights.values()) if weights else None
            ),
            "weights": weight_by_ticker,
        }

        # Series de precios en lote (misma forma que intelligence: columnas
        # ligeras, una query) y retornos por posicion.
        price_series: dict[int, list[Any]] = {company.id: [] for _, company in rows}
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
            company_id: PortfolioIntelligenceService._fill_trailing_spot(series)
            for company_id, series in price_series.items()
        }
        raw_returns = {
            company_id: PortfolioIntelligenceService._returns(series)
            for company_id, series in price_series.items()
        }

        # Conversion a divisa base de las posiciones en otra divisa.
        position_currency = {
            company.id: (position.currency or base_currency) for position, company in rows
        }
        fx_currencies = {
            currency
            for company_id, currency in position_currency.items()
            if currency != base_currency and company_id in weights
        }
        fx_series = _fx_series_by_pair(
            db, base_currency=base_currency, quote_currencies=fx_currencies, since=cutoff
        )
        returns_base: dict[int, dict[date, float]] = {}
        fx_detail: dict[int, dict[str, Any]] = {}
        for _, company in rows:
            if company.id not in weights:
                continue
            currency = position_currency[company.id]
            series = raw_returns.get(company.id, {})
            if currency == base_currency:
                returns_base[company.id] = series
                continue
            fx = fx_series.get(currency)
            if fx is None:
                returns_base[company.id] = {}
                fx_detail[company.id] = {
                    "currency": currency,
                    "mode": "unavailable",
                    "dropped_returns": len(series),
                }
                continue
            converted, dropped = _convert_returns_to_base(series, fx)
            returns_base[company.id] = converted
            fx_detail[company.id] = {
                "currency": currency,
                "mode": "converted",
                "fx_direction": fx[2],
                "dropped_returns": dropped,
            }

        # Inclusion: >= MIN_MATRIX_SESSIONS retornos propios.
        candidates: dict[int, dict[date, float]] = {}
        for _, company in rows:
            if company.id not in weights:
                continue
            series = returns_base.get(company.id, {})
            if len(series) < MIN_MATRIX_SESSIONS:
                reason = (
                    "fx_history_insufficient"
                    if fx_detail.get(company.id, {}).get("mode") == "unavailable"
                    or (
                        fx_detail.get(company.id, {}).get("dropped_returns", 0) > 0
                        and len(raw_returns.get(company.id, {})) >= MIN_MATRIX_SESSIONS
                    )
                    else "insufficient_history"
                )
                excluded.append(
                    {
                        "ticker": company.ticker,
                        "reason": reason,
                        "sessions": len(series),
                    }
                )
                continue
            candidates[company.id] = series

        # Alineacion a fechas comunes. Una serie con calendario raro
        # arrastraria la interseccion a casi vacio: se expulsa la que menos
        # aporta a las fechas comunes hasta llegar al minimo o no mejorar.
        dropped_alignment: list[dict[str, Any]] = []
        ticker_of = {company.id: company.ticker for _, company in rows}
        while len(candidates) > 1:
            common: set[date] | None = None
            for series in candidates.values():
                common = set(series) if common is None else (common & set(series))
            common = common or set()
            if len(common) >= MIN_MATRIX_SESSIONS:
                break
            worst = min(candidates, key=lambda cid: len(set(candidates[cid]) & common))
            if len(set(candidates[worst]) & common) == len(common):
                break
            dropped_alignment.append(
                {
                    "ticker": ticker_of[worst],
                    "reason": "calendar_misaligned",
                    "sessions": len(candidates[worst]),
                }
            )
            del candidates[worst]

        common_dates: tuple[date, ...] = ()
        if candidates:
            common_set: set[date] | None = None
            for series in candidates.values():
                common_set = set(series) if common_set is None else (common_set & set(series))
            common_dates = tuple(sorted(common_set or ()))
        excluded.extend(dropped_alignment)

        matrix_ok = len(candidates) >= 1 and len(common_dates) >= MIN_MATRIX_SESSIONS
        covariance_out: dict[str, Any] | None = None
        correlation_out: dict[str, Any] | None = None
        portfolio_out: dict[str, Any] | None = None
        estimator_out: dict[str, Any] | None = None
        contribution_by_company: dict[int, dict[str, float | None]] = {}

        if matrix_ok:
            tickers = [ticker_of[cid] for cid in candidates]
            ordered_ids = list(candidates)
            matrix = np.array(
                [[candidates[cid][day] for day in common_dates] for cid in ordered_ids],
                dtype=float,
            ).T
            cov_daily, shrinkage = ledoit_wolf_covariance(matrix)
            cov_annual = cov_daily * ANNUALIZATION_FACTOR
            included_weights = np.array([weights[cid] for cid in ordered_ids], dtype=float)
            included_weights = included_weights / included_weights.sum()
            shares, marginal, vol_daily = risk_contributions(included_weights, cov_daily)
            vol_annual = vol_daily * math.sqrt(ANNUALIZATION_FACTOR)
            corr = correlation_from_covariance(cov_daily)
            covariance_out = {
                "tickers": tickers,
                "matrix": [
                    [round(float(value), 8) for value in row] for row in cov_annual.tolist()
                ],
            }
            correlation_out = {
                "tickers": tickers,
                "matrix": [
                    [round(float(value), 6) for value in row] for row in corr.tolist()
                ],
                "source": "shrunk_covariance",
            }
            portfolio_out = {
                "vol_annualized": round(vol_annual, 6),
                "variance_annualized": round(vol_annual**2, 8),
            }
            estimator_out = {
                "name": "ledoit_wolf_identity",
                "shrinkage": round(shrinkage, 6),
                "annualization": ANNUALIZATION_FACTOR,
            }
            for index, cid in enumerate(ordered_ids):
                contribution_by_company[cid] = {
                    "weight_included": round(float(included_weights[index]), 6),
                    "vol_annualized": round(float(math.sqrt(cov_annual[index][index])), 6),
                    "risk_contribution": round(float(shares[index]), 6),
                    "marginal_contribution": round(
                        float(marginal[index]) * math.sqrt(ANNUALIZATION_FACTOR), 6
                    ),
                }
        else:
            # Respaldo honesto: correlacion Pearson por pares (la de
            # intelligence, minimo 20 solapadas), declarada como tal.
            pairwise, observations = PortfolioIntelligenceService._correlations(
                returns_base,
                [(p, c) for p, c in rows if c.id in weights],
            )
            correlation_out = {
                "tickers": sorted(pairwise),
                "matrix": [
                    [
                        (round(value, 6) if value is not None else None)
                        for value in (pairwise[left].get(right) for right in sorted(pairwise))
                    ]
                    for left in sorted(pairwise)
                ],
                "source": "pearson_pairwise_min_20",
            }

        positions_out: list[dict[str, Any]] = []
        for position, company in rows:
            if company.id not in weights:
                continue
            contribution = contribution_by_company.get(company.id)
            fx_info = fx_detail.get(company.id)
            entry: dict[str, Any] = {
                "ticker": company.ticker,
                "weight": round(weights[company.id], 6),
                "included": contribution is not None,
                "sessions": len(returns_base.get(company.id, {})),
                "sessions_common": len(common_dates) if contribution is not None else 0,
                "fx_mode": fx_info["mode"] if fx_info else "none",
            }
            if fx_info and fx_info.get("dropped_returns"):
                entry["fx_dropped_returns"] = fx_info["dropped_returns"]
            if contribution is not None:
                entry.update(contribution)
            else:
                entry["excluded_reason"] = next(
                    (item["reason"] for item in excluded if item["ticker"] == company.ticker),
                    "insufficient_history" if not matrix_ok else "calendar_misaligned",
                )
            positions_out.append(entry)

        warnings: list[dict[str, str]] = []
        converted_currencies = sorted(
            {info["currency"] for info in fx_detail.values() if info.get("mode") == "converted"}
        )
        if converted_currencies:
            warnings.append(
                {
                    "code": "fx_conversion",
                    "message": (
                        "Retornos de posiciones en "
                        + ", ".join(converted_currencies)
                        + " convertidos a "
                        + base_currency
                        + " con el historico FX diario; fines de semana y festivos usan la ultima tasa conocida."
                    ),
                }
            )
        if not matrix_ok and correlation_out is not None and correlation_out["tickers"]:
            warnings.append(
                {
                    "code": "pairwise_fallback",
                    "message": (
                        "Sin "
                        + str(MIN_MATRIX_SESSIONS)
                        + " sesiones comunes: la matriz y las contribuciones son N/D y la correlacion es Pearson por pares (minimo 20 sesiones solapadas)."
                    ),
                }
            )

        status = STATUS_OK if matrix_ok else STATUS_INSUFFICIENT
        if not weights:
            status = STATUS_NO_POSITIONS
        return {
            "as_of": today.isoformat(),
            "base_currency": base_currency,
            "status": status,
            "window": {
                "requested_days": WINDOW_DAYS,
                "sessions_common": len(common_dates),
                "min_sessions": MIN_MATRIX_SESSIONS,
                "start": common_dates[0].isoformat() if common_dates else None,
                "end": common_dates[-1].isoformat() if common_dates else None,
            },
            "estimator": estimator_out,
            "covariance_annualized": covariance_out,
            "correlation": correlation_out,
            "portfolio": portfolio_out,
            "positions": positions_out,
            "excluded": excluded,
            "concentration": concentration,
            "warnings": warnings,
            "trace": {
                "method": "ledoit_wolf_2004_identity_target",
                "weights": "current_market_value_base_currency",
                "weights_renormalized_over_included": True,
                "returns": "daily_simple_adj_close_base_currency",
                "fx_policy": "quote_returns_converted_with_daily_fx_carry_forward",
                "shrinkage_verified_against": "sklearn.covariance.ledoit_wolf",
            },
            "provenance": provenance(
                "Base de datos de GerarAI",
                SourceKind.INTERNAL,
                coverage=Coverage.PARTIAL if excluded else Coverage.OK,
                note="Calculado desde posiciones, MarketPrice.adj_close y fx_rates persistidos; cada fila upstream lleva su propia procedencia.",
            ),
        }

    def _empty(self, today: date, base_currency: str) -> dict[str, Any]:
        return {
            "as_of": today.isoformat(),
            "base_currency": base_currency,
            "status": STATUS_NO_POSITIONS,
            "window": {
                "requested_days": WINDOW_DAYS,
                "sessions_common": 0,
                "min_sessions": MIN_MATRIX_SESSIONS,
                "start": None,
                "end": None,
            },
            "estimator": None,
            "covariance_annualized": None,
            "correlation": None,
            "portfolio": None,
            "positions": [],
            "excluded": [],
            "concentration": {
                "top_1": 0.0,
                "top_5": 0.0,
                "herfindahl": 0.0,
                "effective_positions": None,
                "weights": {},
            },
            "warnings": [],
            "trace": {"method": "ledoit_wolf_2004_identity_target"},
            "provenance": provenance(
                "Base de datos de GerarAI",
                SourceKind.INTERNAL,
                coverage=Coverage.OK,
                note="Sin posiciones.",
            ),
        }
