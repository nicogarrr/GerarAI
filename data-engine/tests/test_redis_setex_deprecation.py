"""Auditoría externa (punto D): redis-py deprecó `setex` en favor de `set(..., ex=ttl)`.

Con redis-py 8.x, `client.setex(...)` emite
``DeprecationWarning: Call to deprecated setex. (Use 'set' instead.)``.
Había dos llamadas vivas: la escritura del decorador `cached` (app/core/cache.py)
y la caché macro de GDELT (app/workers/dramatiq_app.py). Estos tests fijan que
la escritura usa `set(..., ex=ttl)` y que no queda ningún `.setex(` en app/.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class _RecordingRedis:
    """Redis en memoria que graba las escrituras y revienta si se usa setex."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, int | None]] = []

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.set_calls.append((key, ex))
        self.store[key] = value
        return True

    def setex(self, key, ttl, value):  # noqa: ARG002 - guardia de API deprecada
        raise AssertionError("setex está deprecado en redis-py: usa set(..., ex=ttl)")


def test_cached_escribe_con_set_ex_no_setex():
    from app.core import cache as cache_module

    fake = _RecordingRedis()
    cache_module._redis_state["client"] = fake
    cache_module._redis_state["down_until"] = 0.0
    try:
        calls = {"n": 0}

        @cache_module.cached(prefix="probe", ttl=123, category="market_data")
        def compute(x):
            calls["n"] += 1
            return {"v": x}

        assert compute(1) == {"v": 1}
        assert compute(1) == {"v": 1}  # hit: no reejecuta
        assert calls["n"] == 1
        assert len(fake.set_calls) == 1
        _, ex = fake.set_calls[0]
        assert ex == 123
    finally:
        cache_module._redis_state["client"] = None
        cache_module._redis_state["down_until"] = 0.0


def test_gdelt_macro_cache_set_usa_set_ex():
    from app.workers import dramatiq_app

    fake = _RecordingRedis()
    result = SimpleNamespace(source="gdelt", errors=[], metadata={}, items=[])
    dramatiq_app._gdelt_macro_cache_set(fake, "macro", result)
    assert fake.set_calls == [
        (
            dramatiq_app._gdelt_macro_cache_key("macro"),
            dramatiq_app._GDELT_MACRO_CACHE_TTL_SECONDS,
        )
    ]


def test_no_quedan_llamadas_a_setex_en_app():
    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        str(path.relative_to(app_root))
        for path in app_root.rglob("*.py")
        if ".setex(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
