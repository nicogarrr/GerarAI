"""VIX context from dated FRED closes, never a trading instruction."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any

VIX_SOURCE_URL = "https://fred.stlouisfed.org/series/VIXCLS"
# Operational freshness tolerance, not an investment parameter or backtest result.
MAX_AGE_DAYS = 5


def vix_context(metric: Any, now: datetime) -> dict:
    """Classify only trusted, positive, finite closes known by the request time."""
    unavailable = {"status": "unavailable", "reason": "missing", "method": "vix-context-v1"}
    if not isinstance(metric, dict) or not metric:
        return unavailable
    try:
        value = metric["value"]
        day = date.fromisoformat(metric["date"])
        fetched = datetime.fromisoformat(metric["fetched_at"].replace("Z", "+00:00"))
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            or metric.get("source") != "FRED"
            or metric.get("source_url") != VIX_SOURCE_URL
            or metric.get("unit") != "índice"
            or fetched.tzinfo is None
            or now.tzinfo is None
            or fetched > now
            or day > fetched.astimezone(UTC).date()
            or day > now.astimezone(UTC).date()
        ):
            return {**unavailable, "reason": "invalid"}
    except (KeyError, TypeError, ValueError, AttributeError):
        return {**unavailable, "reason": "invalid"}
    metadata = {
        "value": value,
        "date": day.isoformat(),
        "fetched_at": fetched.isoformat(),
        "source": "FRED / Cboe",
        "source_url": VIX_SOURCE_URL,
        "frequency": "daily_close",
        "method": "vix-context-v1",
        "thresholds": {"low_below": 15, "high_above": 30},
    }
    if (now.astimezone(UTC).date() - day).days > MAX_AGE_DAYS:
        return {**metadata, "status": "unavailable", "reason": "stale"}
    return {
        **metadata,
        "status": "available",
        "band": "high" if value > 30 else "low" if value < 15 else "middle",
    }
