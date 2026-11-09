"""A nonfinite ECB CSV observation is unavailable, never a rate or an exception."""

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.connectors import ecb_history as ecb

DAY = date(2026, 11, 9)


def csv(value):
    return "CURRENCY,TIME_PERIOD,OBS_VALUE\nUSD,2026-11-09," + value + "\n"


@pytest.mark.parametrize("value", ["NaN", "sNaN", "-NaN", "-sNaN", "Infinity", "+Infinity", "-Infinity"])
def test_nonfinite_observation_is_discarded_without_raising(value):
    assert ecb.parse_ecb_csv(csv(value)) == []


def test_invalid_observation_does_not_discard_valid_rows():
    text = csv("NaN") + "GBP,2026-11-09,0.8\nUSD,2026-11-09,Infinity\n"
    assert ecb.parse_ecb_csv(text) == [(DAY, "GBP", Decimal("0.8"))]


@pytest.mark.parametrize("value,expected", [("1.25", Decimal("1.25")), ("1E-20", Decimal("1E-20"))])
def test_positive_finite_observations_remain_supported(value, expected):
    assert ecb.parse_ecb_csv(csv(value)) == [(DAY, "USD", expected)]


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity"])
def test_nonfinite_observation_is_reported_unpublished_and_never_written(monkeypatch, value):
    fetch = AsyncMock(return_value=csv(value))
    upsert = Mock(side_effect=AssertionError("must not write nonfinite FX"))
    monkeypatch.setattr(ecb.PortfolioFXService, "upsert_rate", upsert)
    db = Mock()
    result = asyncio.run(ecb.backfill_ecb_rates(db, currencies={"USD"}, start=DAY, end=DAY, fetcher=fetch))
    assert result == {"source": "ECB", "written": {}, "not_published": ["USD"]}
    fetch.assert_awaited_once_with(["USD"], DAY, DAY)
    upsert.assert_not_called()
