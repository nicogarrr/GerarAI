"""Dimensional algebra and metadata for fundamental operating drivers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import FinancialFact


@dataclass(frozen=True)
class Dimension:
    """A small immutable unit vector used to validate formula products."""

    powers: tuple[tuple[str, int], ...] = ()

    @classmethod
    def of(cls, **powers: int) -> Dimension:
        return cls(tuple(sorted((key, value) for key, value in powers.items() if value)))

    def multiply(self, other: Dimension) -> Dimension:
        result = dict(self.powers)
        for key, value in other.powers:
            result[key] = result.get(key, 0) + value
            if result[key] == 0:
                del result[key]
        return Dimension(tuple(sorted(result.items())))

    def render(self) -> str:
        positive: list[str] = []
        negative: list[str] = []
        for key, power in self.powers:
            target = positive if power > 0 else negative
            count = abs(power)
            target.append(key if count == 1 else f"{key}^{count}")
        numerator = "*".join(positive) or "1"
        return numerator if not negative else f"{numerator}/{'*'.join(negative)}"


DIMENSIONLESS = Dimension()
ANNUAL_CURRENCY = Dimension.of(currency=1, year=-1)
MONTHS_PER_YEAR = Dimension.of(month=1, year=-1)


DRIVER_DIMENSIONS: dict[str, Dimension] = {
    # Dimensionless rates.
    "penetration": DIMENSIONLESS,
    "revenue_share": DIMENSIONLESS,
    "utilization": DIMENSIONLESS,
    "take_rate": DIMENSIONLESS,
    "churn": DIMENSIONLESS,
    "retention": DIMENSIONLESS,
    "cash_yield": Dimension.of(year=-1),
    "occupancy": DIMENSIONLESS,
    "royalty_rate": DIMENSIONLESS,
    "combined_ratio": DIMENSIONLESS,
    "organic_growth": DIMENSIONLESS,
    # Operating quantities and prices.
    "addressable_subscribers": Dimension.of(entity=1),
    "subscribers": Dimension.of(entity=1),
    "active_accounts": Dimension.of(entity=1),
    "customers": Dimension.of(entity=1),
    "seats": Dimension.of(entity=1),
    "monthly_arpu": Dimension.of(currency=1, entity=-1, month=-1),
    "arpu": Dimension.of(currency=1, entity=-1, year=-1),
    "satellites": Dimension.of(satellite=1),
    "capacity_per_satellite": Dimension.of(data=1, satellite=-1, year=-1),
    "price_per_gb": Dimension.of(currency=1, data=-1),
    "launches": Dimension.of(launch=1, year=-1),
    "price_per_launch": Dimension.of(currency=1, launch=-1),
    "backlog": Dimension.of(currency=1),
    "backlog_conversion": Dimension.of(year=-1),
    "tpv": ANNUAL_CURRENCY,
    "arr": ANNUAL_CURRENCY,
    "capacity_units": Dimension.of(unit=1, year=-1),
    "price_per_unit": Dimension.of(currency=1, unit=-1),
    "aum": Dimension.of(currency=1),
    "fee_rate": Dimension.of(year=-1),
    "tangible_book_value": Dimension.of(currency=1),
    "return_on_tangible_equity": Dimension.of(year=-1),
    "earned_premiums": ANNUAL_CURRENCY,
    "net_operating_income": ANNUAL_CURRENCY,
    "production_volume": Dimension.of(volume=1, year=-1),
    "realized_price": Dimension.of(currency=1, volume=-1),
    "revenue": ANNUAL_CURRENCY,
}


# Every tuple is a multiplicative term. Terms in the same formula must reduce to
# the declared annual currency output before min/addition can be evaluated.
FORMULA_TERMS: dict[str, tuple[tuple[str | Dimension, ...], ...]] = {
    "space_network": (
        (
            "addressable_subscribers",
            "penetration",
            "monthly_arpu",
            MONTHS_PER_YEAR,
            "revenue_share",
        ),
        ("satellites", "capacity_per_satellite", "utilization", "price_per_gb"),
    ),
    "space_defense": (
        ("launches", "price_per_launch"),
        ("backlog", "backlog_conversion"),
    ),
    "platform": (("tpv", "take_rate"),),
    "subscriber": (("subscribers", "monthly_arpu", MONTHS_PER_YEAR),),
    "software_ai": (("arr",),),
    "capacity_infrastructure": (("capacity_units", "utilization", "price_per_unit"),),
    "holding_asset_manager": (("aum", "fee_rate"),),
    "bank": (("tangible_book_value", "return_on_tangible_equity"),),
    "insurer": (("earned_premiums",),),
    "reit": (("net_operating_income",),),
    "commodity": (("production_volume", "realized_price"),),
    "biotech_pre_fcf": (("revenue",),),
    "advertising_platform": (("revenue",),),
    "generic_fcf": (("revenue",),),
}


TOKEN_ALIASES = {
    "usd": "currency",
    "eur": "currency",
    "gbp": "currency",
    "cad": "currency",
    "aud": "currency",
    "jpy": "currency",
    "gb": "data",
    "tb": "data",
    "subscriber": "entity",
    "subscribers": "entity",
    "customer": "entity",
    "customers": "entity",
    "account": "entity",
    "accounts": "entity",
    "seat": "entity",
    "seats": "entity",
    "satellites": "satellite",
    "launches": "launch",
    "units": "unit",
    "barrel": "volume",
    "barrels": "volume",
    "yr": "year",
    "years": "year",
    "mo": "month",
    "months": "month",
}


def _parse_explicit_unit(raw_unit: str) -> Dimension | None:
    normalized = raw_unit.strip().lower().replace("_per_", "/").replace(" per ", "/")
    if normalized in {"decimal", "ratio", "percent", "%"}:
        return DIMENSIONLESS
    # Legacy placeholders carry no safe dimensional information.
    if normalized in {"", "unknown", "unit", "units", "count", "number", "shares"}:
        return None
    tokens = normalized.replace("*", "/").split("/")
    powers: dict[str, int] = {}
    for index, token in enumerate(tokens):
        token = token.strip().rstrip("s") if token.strip() not in {"usd", "gbp"} else token.strip()
        canonical = TOKEN_ALIASES.get(token, token)
        if not canonical or not canonical.replace("_", "").isalpha():
            return None
        exponent = 1 if index == 0 else -1
        powers[canonical] = powers.get(canonical, 0) + exponent
    return Dimension.of(**powers)


CURRENCY_CODES = {"usd", "eur", "gbp", "cad", "aud", "jpy"}
DATA_UNIT_CODES = {"gb", "tb"}
PERCENT_UNITS = {"percent", "%"}


def _unit_tokens(raw_unit: str) -> list[str]:
    normalized = raw_unit.strip().lower().replace("_per_", "/").replace(" per ", "/")
    return [t.strip() for t in normalized.replace("*", "/").split("/") if t.strip()]


class DriverDimensionValidator:
    def validate(
        self,
        formula_key: str,
        fact_cache: dict[str, list[FinancialFact]],
    ) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        drivers: dict[str, dict[str, Any]] = {}
        terms = FORMULA_TERMS[formula_key]
        keys = {item for term in terms for item in term if isinstance(item, str)}
        currencies: dict[str, set[str]] = {}
        data_units: dict[str, set[str]] = {}
        for key in sorted(keys):
            expected = DRIVER_DIMENSIONS[key]
            facts = fact_cache.get(key) or []
            raw_unit = facts[-1].unit if facts else "unknown"
            explicit = _parse_explicit_unit(raw_unit)
            history_units = sorted(
                {(fact.unit or "unknown").strip().lower() for fact in facts}
            )
            if len(history_units) > 1:
                # Validar solo el ultimo hecho oculta cambios de unidad en la serie.
                errors.append(
                    {
                        "driver": key,
                        "error": "unit_changes_across_history",
                        "units": history_units,
                    }
                )
            validation = "inferred_from_driver_semantics"
            tokens = _unit_tokens(raw_unit)
            for token in tokens:
                if token in CURRENCY_CODES:
                    currencies.setdefault(token, set()).add(key)
                if token in DATA_UNIT_CODES:
                    data_units.setdefault(token, set()).add(key)
            if tokens and tokens[0] in PERCENT_UNITS:
                # Decimal contract: 5 percent must arrive as 0.05, never as 5.
                errors.append(
                    {
                        "driver": key,
                        "unit": raw_unit,
                        "error": "percent_unit_requires_decimal_normalization",
                    }
                )
            if explicit is not None:
                validation = "explicit_unit_verified"
                # Annual facts commonly store a currency as USD rather than
                # USD/year; the fiscal period supplies the omitted time basis.
                compatible = explicit == expected
                if explicit == Dimension.of(currency=1) and expected == ANNUAL_CURRENCY:
                    compatible = True
                    validation = "explicit_currency_plus_annual_period"
                if not compatible:
                    errors.append(
                        {
                            "driver": key,
                            "unit": raw_unit,
                            "expected_dimension": expected.render(),
                            "actual_dimension": explicit.render(),
                        }
                    )
            drivers[key] = {
                "unit": raw_unit,
                "dimension": expected.render(),
                "validation": validation,
            }

        if len(currencies) > 1:
            errors.append(
                {
                    "formula": formula_key,
                    "error": "mixed_currencies_without_fx",
                    "currencies": {code: sorted(keys_) for code, keys_ in sorted(currencies.items())},
                }
            )
        if len(data_units) > 1:
            errors.append(
                {
                    "formula": formula_key,
                    "error": "mixed_data_units_without_scale",
                    "units": {code: sorted(keys_) for code, keys_ in sorted(data_units.items())},
                }
            )

        term_dimensions: list[str] = []
        for term in terms:
            dimension = DIMENSIONLESS
            for item in term:
                dimension = dimension.multiply(
                    item if isinstance(item, Dimension) else DRIVER_DIMENSIONS[item]
                )
            term_dimensions.append(dimension.render())
            if dimension != ANNUAL_CURRENCY:
                errors.append(
                    {
                        "formula": formula_key,
                        "term": [item.render() if isinstance(item, Dimension) else item for item in term],
                        "expected_dimension": ANNUAL_CURRENCY.render(),
                        "actual_dimension": dimension.render(),
                    }
                )
        return {
            "valid": not errors,
            "output_dimension": ANNUAL_CURRENCY.render(),
            "term_dimensions": term_dimensions,
            "drivers": drivers,
            "errors": errors,
        }


def driver_metadata(
    key: str,
    *,
    raw_unit: str,
    company_currency: str,
    period: str | None,
    source_type: str | None,
) -> dict[str, str]:
    dimension = DRIVER_DIMENSIONS.get(key)
    powers = dict(dimension.powers) if dimension else {}
    time_basis = "per_year" if powers.get("year") == -1 else (
        "per_month" if powers.get("month") == -1 else "point_in_time"
    )
    return {
        "unit": raw_unit or "unknown",
        "currency": company_currency if powers.get("currency") else "N/A",
        "time_basis": time_basis,
        "geography": "global",
        "segment": "consolidated",
        "period": period or "unknown",
        "source": source_type or "financial_fact",
        "dimension": dimension.render() if dimension else "unknown",
    }
