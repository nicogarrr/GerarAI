"""La cache JSON de la SEC guarda los payloads grandes comprimidos y acotados."""
from __future__ import annotations

import time

import pytest

from app.services.connectors import sec


def _big(seed: int, concepts: int = 120, entries: int = 60) -> dict:
    return {
        "cik": seed,
        "facts": {
            "us-gaap": {
                f"C{c}": {
                    "label": f"Etiqueta {c} ñ",
                    "units": {"USD": [{"end": "2020-12-31", "val": seed * 1000 + e + 0.5, "form": "10-K"} for e in range(entries)]},
                }
                for c in range(concepts)
            }
        },
    }


@pytest.fixture(autouse=True)
def _clean():
    sec.reset_sec_client_state()
    yield
    sec.reset_sec_client_state()


URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"


def test_big_payload_round_trips_identically_and_is_packed():
    payload = _big(1)
    sec._cache_put(URL.format(1), payload, 900.0)
    assert isinstance(sec._json_cache[URL.format(1)][1], sec._Packed)
    got = sec._cache_get(URL.format(1))
    assert got == payload


def test_get_returns_independent_copy():
    sec._cache_put(URL.format(2), _big(2), 900.0)
    first = sec._cache_get(URL.format(2))
    first["facts"]["us-gaap"].clear()
    assert sec._cache_get(URL.format(2)) == _big(2)


def test_small_payload_and_ticker_map_stay_as_dict():
    sec._cache_put("https://data.sec.gov/submissions/CIK0000000001.json", {"a": 1}, 900.0)
    assert not isinstance(sec._json_cache["https://data.sec.gov/submissions/CIK0000000001.json"][1], sec._Packed)
    huge_map = {str(i): {"cik_str": i, "ticker": f"T{i}", "title": "x" * 50} for i in range(8000)}
    sec._cache_put(sec.SECClient.ticker_map_url, huge_map, 900.0)
    entry = sec._cache_entry(sec.SECClient.ticker_map_url)
    assert entry is not None and entry[1] == huge_map


def test_packed_budget_evicts_oldest(monkeypatch):
    one = _big(3)
    sec._cache_put(URL.format(3), one, 900.0)
    size = len(sec._json_cache[URL.format(3)][1].blob)
    monkeypatch.setattr(sec, "_CACHE_MAX_PACKED_BYTES", int(size * 2.5))
    for i in (4, 5, 6):
        sec._cache_put(URL.format(i), _big(i), 900.0)
    assert sec._cache_get(URL.format(3)) is None
    assert sec._cache_get(URL.format(6)) == _big(6)
    assert sec._packed_total() <= int(size * 2.5)


def test_entry_bigger_than_budget_is_not_cached(monkeypatch):
    monkeypatch.setattr(sec, "_CACHE_MAX_PACKED_BYTES", 100)
    sec._cache_put(URL.format(7), _big(7), 900.0)
    assert sec._cache_get(URL.format(7)) is None


def test_expired_entries_are_purged_on_put(monkeypatch):
    sec._cache_put("https://data.sec.gov/submissions/CIK1.json", {"a": 1}, 0.01)
    time.sleep(0.05)
    sec._cache_put("https://data.sec.gov/submissions/CIK2.json", {"b": 2}, 900.0)
    assert "https://data.sec.gov/submissions/CIK1.json" not in sec._json_cache
