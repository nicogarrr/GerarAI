"""Cliente Redis perezoso con backoff compartido (app.core.redis_client).

core/cache.py y services/movers_cache.py llevaban la conexion copiada; ahora
ambos llaman a redis_client_with_backoff con SU estado y SUS parametros.
Este test fija el comportamiento del helper y que no vuelven las copias.
"""

from pathlib import Path

from app.core.redis_client import redis_client_with_backoff, redis_down


def _state():
    return {"client": None, "down_until": 0.0}


def test_en_backoff_devuelve_none_sin_tocar_redis(monkeypatch):
    state = {"client": None, "down_until": 1e18}
    assert redis_client_with_backoff(state, connect_timeout=0.5, socket_timeout=0.5) is None


def test_cliente_vivo_se_reusa(monkeypatch):
    sentinel = object()
    state = {"client": sentinel, "down_until": 0.0}
    assert redis_client_with_backoff(state, connect_timeout=0.5, socket_timeout=0.5) is sentinel


def test_sin_url_devuelve_none(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "redis_url", None, raising=False)
    state = _state()
    assert redis_client_with_backoff(state, connect_timeout=0.5, socket_timeout=0.5) is None
    assert state["client"] is None


def test_fallo_de_conexion_marca_backoff_y_opcionalmente_log(monkeypatch):
    # from_url es perezoso: solo el ping inicial (verify_ping) fuerza la conexion.
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "redis_url", "redis://localhost:1/0", raising=False)
    state = _state()
    antes = state["down_until"]
    assert redis_client_with_backoff(
        state, connect_timeout=0.05, socket_timeout=0.05, verify_ping=True, unavailable_log="Redis unavailable for caching"
    ) is None
    assert state["client"] is None
    assert state["down_until"] > antes


def test_redis_down_resetea_estado():
    state = {"client": object(), "down_until": 0.0}
    redis_down(state)
    assert state["client"] is None
    assert state["down_until"] > 0.0


def test_cache_y_movers_usan_el_helper_sin_copias():
    root = Path(__file__).resolve().parents[1]
    cache_src = (root / "app" / "core" / "cache.py").read_text(encoding="utf-8")
    movers_src = (root / "app" / "services" / "movers_cache.py").read_text(encoding="utf-8")
    for nombre, src in (("cache.py", cache_src), ("movers_cache.py", movers_src)):
        assert "redis_client_with_backoff(" in src, nombre
        assert "redis_down(" in src, nombre
        assert "from_url(" not in src, nombre
        assert "REDIS_BACKOFF_S" not in src, nombre
    # Y el helper conserva el retry=no_retry() que exige test_redis_no_retry_guard.
    helper_src = (root / "app" / "core" / "redis_client.py").read_text(encoding="utf-8")
    assert "retry=no_retry()" in helper_src


def test_el_warning_sale_con_el_logger_del_llamante(monkeypatch, caplog):
    import logging

    from app.core import config

    monkeypatch.setattr(config.get_settings(), "redis_url", "redis://localhost:1/0", raising=False)
    caller_logger = logging.getLogger("app.core.cache")
    state = _state()
    with caplog.at_level(logging.WARNING, logger="app.core.cache"):
        assert (
            redis_client_with_backoff(
                state,
                connect_timeout=0.05,
                socket_timeout=0.05,
                verify_ping=True,
                unavailable_log="Redis unavailable for caching",
                log_logger=caller_logger,
            )
            is None
        )
    assert any(r.name == "app.core.cache" and "Redis unavailable for caching" in r.message for r in caplog.records)
