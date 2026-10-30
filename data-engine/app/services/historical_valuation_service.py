"""Historical per-share fundamentals and valuation multiples for charting."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice
from app.services.price_units import price_in_currency
from app.valuation.currency import fact_currency, listing_currency, normalize_currency
from app.valuation.engines.base import ADR_TAG_PREFIX, adr_ratio
from app.valuation.period_bounds import parse_period_bounds, to_date

# Retraso conservador entre el cierre de un periodo y la publicacion de su
# filing cuando la fila no trae `filed` (filas previas a la migracion 0082,
# fuentes no SEC, derivadas sin entradas fechadas). Plazos SEC del 10-K: 60/75/90
# dias segun tipo de emisor, +15 con prorroga (NT 10-K, Rule 12b-25) = 105 dias
# como maximo ordinario. 120 dias cubre ese maximo con margen: en la duda la
# cifra llega tarde a la reconstruccion, nunca antes de ser publica.
UNFILED_PUBLICATION_LAG_DAYS = 120


class HistoricalValuationService:
    METRICS = {
        "eps",
        "eps_diluted",
        "free_cash_flow",
        "revenue",
        "shares_diluted",
        "total_debt",
        "cash_and_equivalents",
    }

    def build(
        self, db: Session, company: Company, *, years: int = 10, as_of: date | None = None
    ) -> dict[str, Any]:
        """Build per-year multiples using only data known on or before ``as_of``.

        ``as_of`` defaults to today. Prices dated after ``as_of`` and facts that
        were not yet public on ``as_of`` are left OUT of the series (they do not
        raise): a replay of a past date sees what was knowable on that date.

        "Knowable" for a fact (``_known_on``): its filing date ``filed`` when
        stored; otherwise the period end + ``UNFILED_PUBLICATION_LAG_DAYS``,
        capped by the date the row was stored (a stored row is public by then).
        A fact whose period cannot be placed in time is excluded from a past
        replay. Only the latest (possibly restated) value of each period is
        stored: when it was filed after ``as_of`` the period is reported as
        missing, never back-filled with the restated figure.
        """
        as_of = as_of or date.today()
        minimum_year = as_of.year - max(1, min(years, 20)) + 1
        prices = list(
            db.scalars(
                select(MarketPrice)
                .where(
                    MarketPrice.company_id == company.id,
                    MarketPrice.date >= date(minimum_year, 1, 1),
                    MarketPrice.date <= as_of,
                )
                .order_by(MarketPrice.date)
            ).all()
        )
        facts = list(
            db.scalars(
                select(FinancialFact)
                .where(
                    FinancialFact.company_id == company.id,
                    FinancialFact.metric.in_(self.METRICS),
                    FinancialFact.fiscal_year >= minimum_year,
                    FinancialFact.fiscal_year <= as_of.year,
                )
                .order_by(
                    FinancialFact.fiscal_year,
                    FinancialFact.metric,
                    desc(FinancialFact.id),
                )
            ).all()
        )
        annual_prices: dict[int, MarketPrice] = {}
        for row in prices:
            annual_prices[row.date.year] = row
        annual_facts: dict[int, dict[str, FinancialFact]] = {}
        excluded_not_public: list[dict[str, Any]] = []
        for row in facts:
            if row.fiscal_year is None or (row.fiscal_quarter or "").upper().startswith("Q"):
                continue
            known_on = self._known_on(row)
            if known_on is None or known_on > as_of:
                excluded_not_public.append(
                    {
                        "metric": row.metric,
                        "fiscal_year": row.fiscal_year,
                        "known_on": known_on.isoformat() if known_on else None,
                        "filed_known": row.filed is not None,
                    }
                )
                continue
            annual_facts.setdefault(row.fiscal_year, {}).setdefault(row.metric, row)

        currency = normalize_currency(company.currency)[0] or listing_currency(
            company.ticker, company.currency
        )
        # Los hechos (EPS, FCF, acciones) son por accion ORDINARIA y el precio
        # de un ADR es por ADR (N ordinarias): los multiplos usan el precio por
        # ordinaria (precio / N), como los motores. Sin eso un ADR 2:1 salia
        # con PER y EV dobles. Marcado ADR sin ratio valido: sin multiplos.
        ratio = adr_ratio(company)
        tagged_adr = any(
            str(tag).strip().lower() == "adr" or str(tag).strip().lower().startswith(ADR_TAG_PREFIX)
            for tag in (company.factor_tags or [])
        )
        series = []
        for year in sorted(annual_prices.keys() | annual_facts.keys()):
            price_row = annual_prices.get(year)
            year_facts = annual_facts.get(year, {})
            price = (
                price_in_currency(
                    price_row.close,
                    quote_currency=price_row.quote_currency,
                    target_currency=currency,
                    company=company,
                )
                if price_row
                else None
            )
            shares = self._value(year_facts, "shares_diluted")
            # Ingestion writes eps_diluted; "eps" is only a legacy alias (F376).
            eps = self._monetary_value(year_facts, "eps_diluted", currency)
            if eps is None:
                eps = self._monetary_value(year_facts, "eps", currency)
            fcf = self._monetary_value(year_facts, "free_cash_flow", currency)
            revenue = self._monetary_value(year_facts, "revenue", currency)
            # A missing debt/cash fact is unknown, not zero: only a reported
            # value (including a reported 0) may enter enterprise value.
            debt = self._monetary_value(year_facts, "total_debt", currency)
            cash = self._monetary_value(year_facts, "cash_and_equivalents", currency)
            if price is None or (ratio is None and tagged_adr):
                comparable_price = None
            else:
                comparable_price = price / Decimal(str(ratio)) if ratio else price
            market_cap = (
                comparable_price * shares if comparable_price is not None and shares is not None else None
            )
            enterprise_value = (
                market_cap + debt - cash
                if market_cap is not None and debt is not None and cash is not None
                else None
            )
            series.append(
                {
                    "year": year,
                    "price": price,
                    "eps": eps,
                    "fcf_per_share": self._divide(fcf, shares),
                    "revenue_per_share": self._divide(revenue, shares),
                    "pe": self._multiple(comparable_price, eps),
                    "ev_to_fcf": self._multiple(enterprise_value, fcf),
                    "ev_to_revenue": self._multiple(enterprise_value, revenue),
                    "source_ids": {
                        "market_price": price_row.id if price_row else None,
                        **{key: row.id for key, row in year_facts.items()},
                    },
                }
            )

        multiple_keys = ("pe", "ev_to_fcf", "ev_to_revenue")
        statistics = {
            key: self._statistics([point[key] for point in series if point[key] is not None])
            for key in multiple_keys
        }
        missing = {
            metric: [point["year"] for point in series if point[metric] is None]
            for metric in (
                "price",
                "eps",
                "fcf_per_share",
                "revenue_per_share",
                *multiple_keys,
            )
        }
        return {
            "ticker": company.ticker,
            "currency": currency,
            "adr_ratio": ratio,
            "years_requested": years,
            "series": series,
            "statistics": statistics,
            "coverage": {
                "points": len(series),
                "complete_valuation_points": sum(
                    all(point[key] is not None for key in multiple_keys) for point in series
                ),
                "missing_by_metric": missing,
            },
            "point_in_time": {
                "as_of": as_of.isoformat(),
                "price_rule": "close dated on or before as_of",
                "fact_rule": (
                    "filed <= as_of; without filed: period end + "
                    f"{UNFILED_PUBLICATION_LAG_DAYS} days (capped by storage date) <= as_of"
                ),
                "restatements": (
                    "only the latest filed value per period is stored; if it was filed "
                    "after as_of the period is missing, not the restated figure"
                ),
                "excluded_not_public": excluded_not_public,
            },
            "definitions": {
                "price": "Last stored close on or before as_of in each calendar year",
                "fcf_per_share": "Annual free cash flow / diluted shares",
                "revenue_per_share": "Annual revenue / diluted shares",
                "pe": "Price / EPS",
                "ev_to_fcf": "(price * diluted shares + debt - cash) / FCF",
                "ev_to_revenue": "(price * diluted shares + debt - cash) / revenue",
            },
        }

    @staticmethod
    def _known_on(row: FinancialFact) -> date | None:
        """Earliest date the stored figure can be proven or safely assumed public."""
        filed = to_date(row.filed)
        if filed is not None:
            return filed
        bounds = parse_period_bounds(
            period=row.period, fiscal_year=row.fiscal_year, fiscal_quarter=row.fiscal_quarter
        )
        if bounds.end_date is None:
            return None
        assumed = bounds.end_date + timedelta(days=UNFILED_PUBLICATION_LAG_DAYS)
        stored = to_date(row.created_at)
        return min(assumed, stored) if stored is not None else assumed

    @staticmethod
    def _value(rows: dict[str, FinancialFact], metric: str) -> Decimal | None:
        row = rows.get(metric)
        return row.value if row else None

    @staticmethod
    def _monetary_value(rows: dict[str, FinancialFact], metric: str, currency: str) -> Decimal | None:
        row = rows.get(metric)
        # No FX or guessed reporting currency in historical multiples.
        if row is None or fact_currency(row.unit) != currency:
            return None
        _, divisor = normalize_currency(row.unit.split("/", 1)[0].strip())
        return row.value / Decimal(divisor)

    @staticmethod
    def _divide(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator

    @classmethod
    def _multiple(cls, numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
        """Múltiplo de valoración: con beneficio, FCF o EV <= 0 es N/D (None),
        como en relative_multiples. Un P/E negativo no es «barato» y metido en
        la mediana y los percentiles los desplaza hacia abajo."""
        if numerator is None or denominator is None or numerator <= 0 or denominator <= 0:
            return None
        return cls._divide(numerator, denominator)

    def _statistics(self, values: list[Decimal]) -> dict[str, Decimal | None]:
        ordered = sorted(values)
        if not ordered:
            return {
                "median": None,
                "percentile_10": None,
                "percentile_25": None,
                "percentile_75": None,
                "percentile_90": None,
            }
        return {
            "median": self._percentile(ordered, Decimal("0.5")),
            "percentile_10": self._percentile(ordered, Decimal("0.1")),
            "percentile_25": self._percentile(ordered, Decimal("0.25")),
            "percentile_75": self._percentile(ordered, Decimal("0.75")),
            "percentile_90": self._percentile(ordered, Decimal("0.9")),
        }

    @staticmethod
    def _percentile(values: list[Decimal], quantile: Decimal) -> Decimal:
        if len(values) == 1:
            return values[0]
        position = quantile * Decimal(len(values) - 1)
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        weight = position - lower
        return values[lower] * (1 - weight) + values[upper] * weight
