"""POST /cache/stats/reset (app/api/routes/cache.py): handler y su gate global."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import cache as routes


def test_reset_stats_devuelve_ok():
    assert routes.reset_stats() == {"status": "ok", "message": "Cache statistics reset"}


def test_reset_stats_404_con_el_gate_cerrado(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(cache_global_invalidation_allowed=False),
    )
    with pytest.raises(HTTPException) as excinfo:
        routes.reset_stats()
    assert excinfo.value.status_code == 404
