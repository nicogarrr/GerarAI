"""GET /api/settings/llm/usage: cadena de plataforma, cuota real de Go y
contadores propios estimados para las patas sin API publica."""
import asyncio
from datetime import date
from decimal import Decimal

from app.api.routes import settings as settings_route
from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.models.entities import BudgetUsage


def _settings(**over) -> Settings:
    base = dict(
        llm_enabled=True,
        opencode_go_api_key="sk-sintetica",
        gemini_api_key="gm-sintetica",
        gemini_free_plan_confirmed=True,
    )
    base.update(over)
    return Settings(_env_file=None, **base)  # pyright: ignore[reportCallIssue]


def _run(coro):
    return asyncio.run(coro)


def _seed_usage() -> None:
    init_db()
    with SessionLocal() as db:
        db.add_all([
            BudgetUsage(usage_date=date.today(), model="deepseek-v4.1-flash",
                        workflow="chat", cost_eur=Decimal("0"), token_count=120),
            BudgetUsage(usage_date=date.today(), model="deepseek-v4.1-flash-free",
                        workflow="chat", cost_eur=Decimal("0"), token_count=80),
            BudgetUsage(usage_date=date.today(), model="gemini-3.5-flash-lite",
                        workflow="chat", cost_eur=Decimal("0"), token_count=50),
        ])
        db.commit()


def test_platform_usage_go_real_quota_and_estimated_legs(monkeypatch):
    _seed_usage()
    monkeypatch.setattr(settings_route, "get_settings", lambda: _settings())

    async def fake_fetch(base_url, api_key, *, session=None, timeout=5.0):
        assert base_url == "https://opencode.ai/zen/go/v1"
        return {"usage": {"rolling": {"percent": 0},
                          "weekly": {"status": "rate-limited", "percent": 100,
                                     "resetsAt": "2026-11-02T00:00:00.000Z"},
                          "monthly": {"percent": 59}}}

    monkeypatch.setattr(settings_route, "fetch_go_usage", fake_fetch)
    with SessionLocal() as db:
        body = _run(settings_route.get_llm_usage(db))
    assert body["source"] == "platform"
    legs = {leg["id"]: leg for leg in body["legs"]}
    assert list(legs) == ["opencode-go", "opencode-free", "gemini"]

    go = legs["opencode-go"]
    assert go["active"] is True and go["estimated"] is False
    assert go["state"] == "limited"  # weekly rate-limited segun la API real
    assert go["quota"]["weekly"]["percent"] == 100
    assert go["today"] == {"date": date.today().isoformat(), "calls": 1, "tokens": 120}

    free = legs["opencode-free"]
    assert free["active"] is True and free["estimated"] is True
    assert free["model"] == "deepseek-v4.1-flash-free"
    assert free["today"]["tokens"] == 80

    gemini = legs["gemini"]
    assert gemini["estimated"] is True and gemini["today"]["tokens"] == 50
    assert gemini["published_limits"]["gemini-3.8-flash"]["rpd"] == 20


def test_platform_usage_degrades_when_go_usage_api_fails(monkeypatch):
    init_db()
    monkeypatch.setattr(settings_route, "get_settings", lambda: _settings())

    async def failing(*args, **kwargs):
        return None

    monkeypatch.setattr(settings_route, "fetch_go_usage", failing)
    with SessionLocal() as db:
        body = _run(settings_route.get_llm_usage(db))
    go = next(leg for leg in body["legs"] if leg["id"] == "opencode-go")
    assert go["state"] == "ok" and go["quota"] is None  # sin inventar cifras


def test_tenant_byok_gets_no_platform_legs(monkeypatch):
    init_db()
    monkeypatch.setattr(settings_route, "get_settings", lambda: _settings())
    monkeypatch.setattr(settings_route, "current_tenant_llm_config", lambda: object())
    with SessionLocal() as db:
        body = _run(settings_route.get_llm_usage(db))
    assert body["source"] == "tenant"
    assert body["legs"] == []
    assert body["message"] == "tenant_byok"


def test_breaker_abierto_marca_la_pata_como_limited(monkeypatch):
    init_db()
    monkeypatch.setattr(settings_route, "get_settings", lambda: _settings())

    async def ok_fetch(*args, **kwargs):
        return {"usage": {"weekly": {"status": "ok", "percent": 3}}}

    monkeypatch.setattr(settings_route, "fetch_go_usage", ok_fetch)
    import time as _time

    from app.llm import base
    base._interactive_quota_breaker[("opencode-free", "deepseek-v4.1-flash-free")] = _time.monotonic() + 600
    base._interactive_quota_breaker_until[("opencode-free", "deepseek-v4.1-flash-free")] = _time.time() + 600
    with SessionLocal() as db:
        body = _run(settings_route.get_llm_usage(db))
    free = next(leg for leg in body["legs"] if leg["id"] == "opencode-free")
    assert free["state"] == "limited" and free["limited_until"] is not None
