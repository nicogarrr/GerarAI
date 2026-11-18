"""CNMV NOD v3: cobertura del connector a 100% de lo nuevo (auditor 18-nov).

Cubre lo que v2 dejo sin ejecutar: _cnmv_redis_client (3 ramas), _get con
error no reintentable o Retry-After no numerico, CNMVNODFetch.__bool__,
cliente propio (close), fetch_latest, y todas las ramas de _parse_block
(anchor no-NIF, sin NIF, negrita no-declarante, sin verdoc, verdoc sin
dos puntos, sin fecha, fecha invalida, sin emisor ni NIF).
"""

import sys
from unittest.mock import Mock

from app.services.connectors import cnmv_pacer

# ---- cnmv_pacer._cnmv_redis_client ----


def test_redis_client_none_without_url(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: Mock(redis_url="")
    )
    assert cnmv_pacer._cnmv_redis_client() is None


def test_redis_client_none_on_internal_error(monkeypatch):
    def boom():
        raise RuntimeError("settings rotos")

    monkeypatch.setattr("app.core.config.get_settings", boom)
    assert cnmv_pacer._cnmv_redis_client() is None


def test_redis_client_builds_from_url(monkeypatch):
    sentinel = object()
    fake_redis = Mock(from_url=Mock(return_value=sentinel))
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: Mock(redis_url="redis://localhost:6379/0")
    )
    assert cnmv_pacer._cnmv_redis_client() is sentinel
    assert fake_redis.from_url.call_args[0][0] == "redis://localhost:6379/0"
