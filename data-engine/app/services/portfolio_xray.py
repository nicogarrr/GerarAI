"""Portfolio "X-ray": plain pass/warn rules over concentration and exposures.

Idea taken from Ghostfolio's X-ray report (open-source portfolio tracker): instead of only
showing weights, say when one position, currency, sector or country carries too much of the
portfolio. Pure function over figures the intelligence service already computed; no I/O.
Thresholds are diversification heuristics, not advice: one position above 20 %, or one
currency (other than the base currency), sector or country above 50 %.
"""
from __future__ import annotations

from typing import Any

POSITION_LIMIT = 0.20
CLUSTER_LIMIT = 0.50
# Buckets that mean "no data", never a real sector/country/currency.
_UNKNOWN = {"", "unknown", "none", "n/a", "nd", "n/d"}


def _largest(weights: dict[Any, float] | None, *, skip: set[str] | None = None) -> tuple[str | None, float]:
    best_key: str | None = None
    best = 0.0
    for key, weight in (weights or {}).items():
        name = str(key or "").strip()
        if name.lower() in _UNKNOWN or (skip and name.upper() in skip):
            continue
        if weight > best:
            best_key, best = name, float(weight)
    return best_key, best


def _rule(rule_id: str, subject: str | None, value: float | None, threshold: float) -> dict[str, Any]:
    if value is None:
        status = "sin_datos"
    else:
        status = "aviso" if value > threshold else "ok"
    return {"id": rule_id, "status": status, "subject": subject, "value": value, "threshold": threshold}


def portfolio_xray(
    concentration: dict[str, Any] | None,
    exposures: dict[str, dict[str, float]] | None,
    base_currency: str | None,
) -> list[dict[str, Any]]:
    """Return one rule result per check: id, status (ok/aviso/sin_datos), subject, value, threshold."""
    weights = (concentration or {}).get("weights") or {}
    exposures = exposures or {}
    if not weights:
        return [_rule(rule_id, None, None, limit) for rule_id, limit in (
            ("posicion_unica", POSITION_LIMIT),
            ("divisa_unica", CLUSTER_LIMIT),
            ("sector_unico", CLUSTER_LIMIT),
            ("pais_unico", CLUSTER_LIMIT),
        )]
    top_ticker, top_weight = _largest(weights)
    base = {base_currency.upper()} if base_currency else set()
    # The base currency carries no FX risk for the owner, so it never trips the currency rule.
    currency, currency_weight = _largest(exposures.get("currencies"), skip=base)
    sector, sector_weight = _largest(exposures.get("sectors"))
    country, country_weight = _largest(exposures.get("countries"))
    return [
        _rule("posicion_unica", top_ticker, top_weight, POSITION_LIMIT),
        _rule("divisa_unica", currency, currency_weight if exposures.get("currencies") else None, CLUSTER_LIMIT),
        _rule("sector_unico", sector, sector_weight if sector else None, CLUSTER_LIMIT),
        _rule("pais_unico", country, country_weight if country else None, CLUSTER_LIMIT),
    ]
