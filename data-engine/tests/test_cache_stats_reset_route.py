"""POST /cache/stats/reset (app/api/routes/cache.py): handler y su gate global."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import cache as routes
from app.core import cache as core_cache


def test_reset_stats_devuelve_ok_y_pone_los_contadores_a_cero():
    core_cache._cache_stats["market_data"] = {"hits": 5, "misses": 3}
    assert routes.reset_stats() == {"status": "ok", "message": "Cache statistics reset"}
    for counts in core_cache.get_cache_stats().values():
        assert counts["hits"] == 0
        assert counts["misses"] == 0


def test_reset_stats_404_con_el_gate_cerrado(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(cache_global_invalidation_allowed=False),
    )
    with pytest.raises(HTTPException) as excinfo:
        routes.reset_stats()
    assert excinfo.value.status_code == 404
