"""Mediana de la misma cohorte una vez: equivalencia exacta, sin reloj."""
import random
from datetime import date, timedelta
from statistics import median
from unittest.mock import Mock

from app.services import analyst_history_service as history


def _reference(rows):
    out = []
    for row in rows:
        peers = [other["abs"] for other in rows
                 if abs((other["date"] - row["date"]).days) <= history.PEER_WINDOW_DAYS
                 and other["firm"] != row["firm"]]
        out.append(row["abs"] - median(peers) if len(peers) >= history.MIN_PEERS else None)
    return out


def test_same_cohort_median_reused_not_peer_values_or_own_error(monkeypatch):
    rows = [{"date": date(2024, 1, 1), "firm": f"firm{i % 10}", "abs": i / 1000}
            for i in range(1000)]
    expected = _reference(rows)
    counted = Mock(side_effect=median)
    monkeypatch.setattr(history, "median", counted)
    history._add_relative(rows)
    assert [row["rel"] for row in rows] == expected
    assert counted.call_count == 10  # antes1000; misma cohorte/firma, distinto error propio
    assert sum(len(call.args[0]) for call in counted.call_args_list) == 9000  # antes900.000elementos a median


def test_random_windows_match_naive_reference_and_boundaries():
    rng = random.Random(2026)
    rows = [{"date": date(2024, 1, 1) + timedelta(days=rng.randrange(200)),
             "firm": f"firm{rng.randrange(5)}", "abs": rng.random()} for _ in range(300)]
    rows += [{"date": date(2024, 1, 1) + timedelta(days=d), "firm": "boundary", "abs": 0}
             for d in [0, 45, 46]]
    rows.sort(key=lambda r: r["date"])
    expected = _reference(rows)
    history._add_relative(rows)
    assert [row["rel"] for row in rows] == expected


def test_no_peers_and_fresh_call_do_not_share_cache():
    rows = [{"date": date(2024, 1, 1), "firm": "alone", "abs": 1}] * 5
    history._add_relative(rows)
    assert all(row["rel"] is None for row in rows)
    second = [{"date": date(2024, 1, 1), "firm": str(i), "abs": i} for i in range(10)]
    expected = _reference(second)
    history._add_relative(second)
    assert [row["rel"] for row in second] == expected
