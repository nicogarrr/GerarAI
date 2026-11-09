"""Private cache never reads/writes an unscoped Redis key."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import cache
from app.services import cached_dca_schedule as dca
from app.services import cached_portfolio_valuation as portfolio


class RedisProbe:
    def __init__(self):
        self.values = {}
        self.reads = []
        self.writes = []

    def get(self, key):
        self.reads.append(key)
        return self.values.get(key)

    def set(self, key, value, *, ex):
        self.writes.append((key, ex))
        self.values[key] = value


@pytest.fixture
def redis(monkeypatch):
    probe = RedisProbe()
    monkeypatch.setattr(cache, "_redis_client", lambda: probe)
    monkeypatch.setattr(cache, "_cache_stats", deepcopy(cache._cache_stats))
    return probe


@pytest.mark.parametrize(
    "helper,category",
    [
        (portfolio._extract_tenant_from_db, "portfolio_valuation"),
        (dca._extract_tenant_from_db, "dca_schedule"),
    ],
)
@pytest.mark.parametrize("tenant", [None, "", "   ", 0, -1, False])
def test_private_method_bypasses_seeded_legacy_unscoped_key(redis, helper, category, tenant):
    prefix = category + ":probe"
    calls = []

    class Service:
        @cache.cached(prefix=prefix, ttl=30, category=category, extract_tenant=helper)
        def read(self, db):
            calls.append(db)
            return {"value": "fresh"}

    # This is the exact legacy key for a method with self/Session removed.
    legacy_key = cache._make_cache_key(prefix, None)
    redis.values[legacy_key] = json.dumps({"value": "legacy_shared"})
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as db:
            if tenant is not None:
                db.info["tenant_id"] = tenant
            service = Service()
            assert service.read(db) == {"value": "fresh"}
            assert service.read(db) == {"value": "fresh"}
            assert calls == [db, db]
        assert redis.reads == [] and redis.writes == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("keyword", [False, True])
def test_known_tenants_have_distinct_keys_and_reuse_own_result(redis, keyword):
    calls = []

    class Service:
        @cache.cached(
            prefix="portfolio_valuation:probe",
            ttl=37,
            category="portfolio_valuation",
            extract_tenant=portfolio._extract_tenant_from_db,
        )
        def read(self, db):
            calls.append(db.info["tenant_id"])
            return {"tenant": db.info["tenant_id"]}

    engine = create_engine("sqlite://")
    try:
        service = Service()
        with Session(engine) as first, Session(engine) as second:
            first.info["tenant_id"] = "first"
            second.info["tenant_id"] = "second"
            invoke = (lambda db: service.read(db=db)) if keyword else (lambda db: service.read(db))
            assert invoke(first) == invoke(first) == {"tenant": "first"}
            assert invoke(second) == invoke(second) == {"tenant": "second"}
        assert calls == ["first", "second"]
        assert len(redis.writes) == 2 and {ttl for _, ttl in redis.writes} == {37}
        assert any(":tenant:first:" in key for key in redis.values)
        assert any(":tenant:second:" in key for key in redis.values)
        assert all(":unscoped:" not in key for key in redis.reads)
    finally:
        engine.dispose()


def test_module_private_cache_and_broken_extractor_fail_closed(redis):
    calls = []

    def broken(*args):
        raise AttributeError("bad extractor")

    @cache.cached(prefix="private:probe", ttl=30, category="portfolio_valuation", extract_tenant=broken)
    def read(db):
        calls.append(db)
        return {"fresh": True}

    engine = create_engine("sqlite://")
    try:
        with Session(engine) as db:
            assert read(db) == read(db) == {"fresh": True}
            assert calls == [db, db]
        assert redis.reads == redis.writes == []
    finally:
        engine.dispose()


def test_public_market_cache_can_still_reuse_unscoped_result(redis):
    calls = []

    @cache.cached(prefix="market_data:probe", ttl=17, category="market_data")
    def read(symbol):
        calls.append(symbol)
        return {"symbol": symbol}

    assert read("TEST") == read("TEST") == {"symbol": "TEST"}
    assert calls == ["TEST"] and len(redis.writes) == 1
    assert ":unscoped:" in redis.writes[0][0]


def test_helpers_accept_keyword_session_and_missing_tenant_without_exceptions():
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as db:
            for helper in (portfolio._extract_tenant_from_db, dca._extract_tenant_from_db):
                assert helper((object(), db), {}) is None
                assert helper((object(),), {"db": db}) is None
                db.info["tenant_id"] = 7
                assert helper((object(),), {"db": db}) == 7
                db.info.clear()
    finally:
        engine.dispose()


@pytest.mark.parametrize("category", ["portfolio_valuation", "dca_schedule"])
def test_private_category_without_extractor_still_bypasses_cache(redis, category):
    calls = []

    @cache.cached(prefix=category + ":plain", ttl=30, category=category)
    def read():
        calls.append(True)
        return {"fresh": True}

    assert read() == read() == {"fresh": True}
    assert calls == [True, True]
    assert redis.reads == redis.writes == []


def test_module_session_extractor_keeps_known_tenant_cache(redis):
    calls = []

    @cache.cached(
        prefix="portfolio_valuation:module",
        ttl=41,
        category="portfolio_valuation",
        extract_tenant=cache.tenant_from_first_db_arg,
    )
    def read(db):
        calls.append(db)
        return {"tenant": db.info["tenant_id"]}

    engine = create_engine("sqlite://")
    try:
        with Session(engine) as db:
            db.info["tenant_id"] = 7
            assert read(db=db) == read(db=db) == {"tenant": 7}
            assert calls == [db]
        assert len(redis.writes) == 1 and ":tenant:7:" in redis.writes[0][0]
    finally:
        engine.dispose()
