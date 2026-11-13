"""Unknown purchase amounts cannot become a complete cluster total."""
import math

import pytest

from app.services.insider_service import detect_signals


def buy(name, amount, *, title=None):
    return {"ticker": "EXAMPLE", "insider": name, "insider_cik": name,
            "role": "officer" if title else "director", "officer_title": title,
            "type": "P", "acquired_disposed": "A", "date": "2026-11-13", "value": amount}


def cluster(values):
    signals = detect_signals([buy(str(i), amount) for i, amount in enumerate(values)])
    return next(signal for signal in signals if signal["signal"] == "cluster_buy")


def test_all_missing_values_are_unknown_not_zero():
    result = cluster([None, None, None])
    assert result["total_value"] is None
    assert result["known_total_value"] is None
    assert result["window_value_missing"] == 3
    assert "sin importe" in result["detail"]
    assert "$0" not in result["detail"]


def test_partial_known_subtotal_is_not_the_total():
    result = cluster([100_000, "not-a-number", None])
    assert result["total_value"] is None
    assert result["known_total_value"] == 100_000
    assert result["window_value_missing"] == 2
    assert "mínimo" in result["detail"]


def test_complete_values_preserve_the_total():
    result = cluster([100_000, 50_000, "25000"])
    assert result["total_value"] == 175_000
    assert result["known_total_value"] == 175_000
    assert result["window_value_missing"] == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, False, -1, [], {}])
def test_invalid_values_are_missing_and_do_not_generate_big_buy(bad):
    result = cluster([100_000, bad, None])
    assert result["total_value"] is None
    assert result["known_total_value"] == 100_000
    assert result["window_value_missing"] == 2
    assert not any(signal["signal"] == "big_buy" for signal in detect_signals([buy("a", bad)]))


def test_overflowing_cluster_total_is_unavailable():
    result = cluster([1e308, 1e308, 1e308])
    assert result["total_value"] is None
    assert result["known_total_value"] is None
    assert "sin importe" in result["detail"]


def test_officer_and_large_buy_signals_remain_independent():
    signals = detect_signals([buy("ceo", 2_000_000, title="Chief Executive Officer"),
                              buy("cfo", None, title="Chief Financial Officer")])
    assert [signal["signal"] for signal in signals] == ["big_buy", "c_suite_buy", "c_suite_buy"]
    assert all(signal.get("value") is None or math.isfinite(signal["value"]) for signal in signals)
