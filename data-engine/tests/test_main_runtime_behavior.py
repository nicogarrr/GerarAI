"""Isolated bootstrap/probe behavior, with real lifecycle and no network/models."""
from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def pools(monkeypatch):
    originals = (main._HEALTH_REQUIRED_EXECUTOR, main._HEALTH_PROBE_EXECUTOR, main._HEALTH_LLM_EXECUTOR)
    owned = []
    for name in ("_HEALTH_REQUIRED_EXECUTOR", "_HEALTH_PROBE_EXECUTOR", "_HEALTH_LLM_EXECUTOR"):
        pool = ThreadPoolExecutor(max_workers=1)
        owned.append(pool)
        monkeypatch.setattr(main, name, pool)
    yield owned
    for pool in owned:
        pool.shutdown(wait=True)
    assert all(not pool._shutdown for pool in originals)


@pytest.mark.parametrize("env,workers", [("production", True), ("development", False), ("test", False)])
def test_lifespan_runs_only_environment_appropriate_steps(monkeypatch, pools, env, workers):
    from app.api.routes import market
    from app.core import gc_tuning, pool_probe, route_warmup, slow_query
    from app.workers import scheduler

    settings = SimpleNamespace(app_env=env, model_fields_set={"app_env"}, workers_enabled=workers)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    db = SimpleNamespace(commit=Mock())
    monkeypatch.setattr(main, "SessionLocal", lambda: nullcontext(db))
    observed = {}
    for name in ("init_db", "configure_model_aliases", "validate_llm_configuration", "ensure_company_master",
                 "apply_master_taxonomy_to_stubs", "_start_embedder_warmup"):
        observed[name] = Mock()
        monkeypatch.setattr(main, name, observed[name])
    for module, name in ((pool_probe, "install"), (slow_query, "install"),
                         (gc_tuning, "freeze_startup_heap"), (route_warmup, "start_route_warmup")):
        observed[module.__name__] = Mock()
        monkeypatch.setattr(module, name, observed[module.__name__])
    jobs = SimpleNamespace(start=Mock(), shutdown=Mock())
    build = Mock(return_value=jobs)
    monkeypatch.setattr(scheduler, "build_scheduler", build)
    close = Mock()
    monkeypatch.setattr(market, "close_shared_yahoo_client", close)

    async def run():
        async with main.lifespan(main.app):
            assert not any(pool._shutdown for pool in pools)
            observed["validate_llm_configuration"].assert_called_once_with(settings)
    asyncio.run(run())
    assert all(pool._shutdown for pool in pools)
    close.assert_called_once()
    assert observed["init_db"].call_count == (env == "test")
    assert observed["ensure_company_master"].call_count == (env != "production")
    assert observed["apply_master_taxonomy_to_stubs"].call_count == (env == "production")
    assert observed["_start_embedder_warmup"].call_count == (env == "production")
    assert observed[pool_probe.__name__].call_count == (env != "test")
    assert observed[slow_query.__name__].call_count == (env != "test")
    assert observed[gc_tuning.__name__].call_count == (env != "test")
    assert observed[route_warmup.__name__].call_count == (env != "test")
    if workers:
        build.assert_called_once_with(background=True)
        jobs.start.assert_called_once()
        jobs.shutdown.assert_called_once_with(wait=False)
    else:
        build.assert_not_called()


def test_implicit_environment_refuses_boot_before_side_effects(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(model_fields_set=set()))
    boot = Mock()
    monkeypatch.setattr(main, "init_db", boot)
    async def run():
        async with main.lifespan(main.app):
            pytest.fail("implicit environment must not start")
    with pytest.raises(RuntimeError, match="APP_ENV is not set"):
        asyncio.run(run())
    boot.assert_not_called()


@pytest.mark.parametrize("ready,fallback_fails", [(True, False), (False, False), (False, True)])
def test_embedder_warmup_is_background_and_fallback_failure_is_nonfatal(monkeypatch, ready, fallback_fails, caplog):
    import threading

    from app.services import hybrid_retrieval, rag

    warm = Mock(return_value=ready)
    fallback = Mock(side_effect=RuntimeError("missing model") if fallback_fails else None)
    monkeypatch.setattr(hybrid_retrieval, "warm_models", warm)
    monkeypatch.setattr(rag.RAGIndex, "warm_fallback", fallback)
    threads = []
    real_thread = threading.Thread
    def owned_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setattr(threading, "Thread", owned_thread)
    main._start_embedder_warmup(SimpleNamespace(rag_dense_model="qa-model"))
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive() and thread.daemon
    warm.assert_called_once_with("qa-model")
    assert fallback.call_count == (not ready)
    if fallback_fails:
        assert "fallback embedder warmup skipped" in caplog.text


@pytest.mark.parametrize("probe,status", [("_probe_qdrant", 200), ("_probe_qdrant", 503),
                                         ("_probe_minio", 200), ("_probe_minio", 503)])
def test_http_probe_reports_actual_response_status(monkeypatch, probe, status):
    import urllib.request
    response = SimpleNamespace(status=status)
    read = Mock(return_value=nullcontext(response))
    monkeypatch.setattr(urllib.request, "urlopen", read)
    settings = SimpleNamespace(qdrant_url="http://qdrant.test/", minio_endpoint="minio.test:9000")
    assert getattr(main, probe)(settings) == ("ok" if status < 500 else "error:status_503")
    expected = "http://qdrant.test/healthz" if probe == "_probe_qdrant" else "http://minio.test:9000"
    read.assert_called_once_with(expected, timeout=main.HEALTH_READY_TIMEOUT_SECONDS)


@pytest.mark.parametrize("status", [403, 503])
def test_minio_http_exception_distinguishes_live_service_from_failure(monkeypatch, status):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", Mock(side_effect=HTTPError("http://minio.test", status, "test", {}, None)))
    assert main._probe_minio(SimpleNamespace(minio_endpoint="http://minio.test")) == ("ok" if status < 500 else "error:status_503")


@pytest.mark.parametrize("outcome", ["invalid_config", "official_provider", "bridge_ok", "bridge_503", "bridge_403", "network"])
def test_llm_readiness_does_not_generate_and_reports_failure_class(monkeypatch, outcome):
    import urllib.request

    from app.llm import readiness
    monkeypatch.setattr(readiness, "llm_configuration_issue", lambda _: "disabled" if outcome == "invalid_config" else None)
    monkeypatch.setattr(readiness, "bridge_health_url", lambda _: None if outcome == "official_provider" else "http://bridge.test/health")
    if outcome in {"bridge_503", "bridge_403"}:
        error = HTTPError("http://bridge.test", int(outcome[-3:]), "internal canary", {}, None)
        read = Mock(side_effect=error)
    elif outcome == "network":
        read = Mock(side_effect=ConnectionError("private canary"))
    else:
        read = Mock(return_value=nullcontext(SimpleNamespace(status=200)))
    monkeypatch.setattr(urllib.request, "urlopen", read)
    actual = main._probe_llm(SimpleNamespace(opencode_go_base_url="unused"))
    expected = {"invalid_config": "error:disabled", "official_provider": "ok", "bridge_ok": "ok",
                "bridge_503": "error:status_503", "bridge_403": "ok", "network": "error:ConnectionError"}[outcome]
    assert actual == expected and "canary" not in actual
    assert read.call_count == (outcome not in {"invalid_config", "official_provider"})


def test_queue_failure_is_retryable_and_redacts_internal_details():
    from redis.exceptions import ConnectionError
    from starlette.requests import Request
    req = Request({"type": "http", "method": "POST", "path": "/api/test", "headers": []})
    response = asyncio.run(main.job_queue_unavailable_handler(req, ConnectionError("secret host")))
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert "nothing was queued" in json.loads(response.body)["detail"]
    assert "secret host" not in response.body.decode()


def test_reporter_failure_cannot_replace_sanitized_500(monkeypatch):
    from starlette.requests import Request

    from app.core import error_reporting
    monkeypatch.setattr(error_reporting, "report_exception", Mock(side_effect=RuntimeError("reporter down")))
    req = Request({"type": "http", "method": "GET", "path": "/api/test", "headers": []})
    response = asyncio.run(main.unhandled_exception_handler(req, KeyError("private canary")))
    assert response.status_code == 500 and "ref:" in json.loads(response.body)["detail"]
    assert "private canary" not in response.body.decode()


def test_csrf_token_route_generates_token_accepted_by_validator():
    from app.core.csrf import validate_csrf_token
    response = TestClient(main.app).get("/api/csrf-token")
    assert response.status_code == 200
    assert validate_csrf_token(response.json()["csrf_token"])


@pytest.mark.parametrize("broken", [None, "database", "llm", "redis"])
def test_ready_response_requires_database_and_llm_but_not_redis(monkeypatch, pools, broken):
    def probe(name):
        def run(_settings):
            if broken == name:
                raise ConnectionError("private endpoint")
            return "ok"
        return run
    for name in ("database", "llm", "redis", "qdrant", "minio"):
        monkeypatch.setattr(main, f"_probe_{name}", probe(name))
    response = TestClient(main.app).get("/health/ready")
    ready = broken not in {"database", "llm"}
    assert response.status_code == (200 if ready else 503)
    assert response.json()["status"] == ("ready" if ready else "degraded")
    if broken:
        assert response.json()["checks"][broken] == "error:ConnectionError"
    assert "private endpoint" not in response.text


def test_upstream_error_handler_returns_502_without_leaking_url():
    import httpx
    from starlette.requests import Request
    req = Request({"type": "http", "method": "GET", "path": "/api/test", "headers": []})
    response = asyncio.run(main.upstream_network_error_handler(req, httpx.ConnectError("https://private.example/?api_key=canary")))
    assert response.status_code == 502 and "ref:" in json.loads(response.body)["detail"]
    assert "canary" not in response.body.decode()
