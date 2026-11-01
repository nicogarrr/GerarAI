"""Tests hermeticos del arnes de carga de tres usuarios.

No levanta servicios ni abre sockets: el modulo se carga por ruta y las
peticiones se sustituyen por httpx.MockTransport.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ENGINE_ROOT / "scripts" / "load_test_three_users.py"
sys.path.insert(0, str(ENGINE_ROOT / "scripts"))


def _load_harness():
    spec = importlib.util.spec_from_file_location("_load_test_three_users", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()
Identity = harness.Identity
LoadConfig = harness.LoadConfig


def _settings_payload(*, configured: bool = True, scoped: bool = True) -> dict[str, Any]:
    return {
        "budget": {"tenant_scoped": scoped, "daily_cost_eur": 0.0},
        "llm": {"configured": configured, "provider": "fake"},
    }


def _run_with_handler(
    handler: Any,
    *,
    rounds: int = 1,
    skip_llm: bool = False,
    identities: list[Any] | None = None,
    inicio_watchlist: bool = False,
) -> dict[str, Any]:
    cfg = LoadConfig(
        base_url="http://127.0.0.1:8000",
        rounds=rounds,
        timeout_s=2.0,
        p95_ms=2000.0,
        chat_p95_ms=30000.0,
        skip_llm=skip_llm,
    )
    people = identities or harness.build_identities("test-load")

    async def runner() -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=cfg.base_url,
            transport=httpx.MockTransport(handler),
            timeout=cfg.timeout_s,
        ) as client:
            return await harness.run_load(
                client,
                cfg=cfg,
                secret="s" * 32,
                identities=people,
                portfolio_path=harness.DEFAULT_PORTFOLIO_PATH,
                include_inicio_watchlist=inicio_watchlist,
            )

    return asyncio.run(runner())


def test_parse_args_defaults() -> None:
    args = harness.parse_args([])
    assert args.base_url == "http://127.0.0.1:8000"
    assert args.rounds == 3
    assert args.timeout_s == 30.0
    assert args.p95_ms == 2000.0
    assert args.chat_p95_ms == 30000.0
    assert args.skip_llm is False
    assert args.allow_remote is False
    assert args.json_out is None
    assert args.dry_run is False


def test_parse_args_custom_and_invalid() -> None:
    args = harness.parse_args(["--rounds", "7", "--timeout", "5", "--skip-llm", "--allow-remote"])
    assert args.rounds == 7
    assert args.timeout_s == 5.0
    assert args.skip_llm is True
    assert args.allow_remote is True
    with pytest.raises(SystemExit):
        harness.parse_args(["--rounds", "0"])


def test_validate_base_url_rejects_remote_by_default() -> None:
    with pytest.raises(ValueError, match="loopback"):
        harness.validate_base_url("http://192.0.2.10:8000", allow_remote=False)
    with pytest.raises(ValueError, match="loopback"):
        harness.validate_base_url("https://example.com", allow_remote=False)


def test_validate_base_url_accepts_loopback_and_explicit_remote() -> None:
    assert harness.validate_base_url("http://127.0.0.1:8000", allow_remote=False) == ("http://127.0.0.1:8000")
    assert harness.validate_base_url("http://localhost:8000/", allow_remote=False) == (
        "http://localhost:8000"
    )
    assert harness.validate_base_url("http://[::1]:8000", allow_remote=False) == ("http://[::1]:8000")
    assert harness.validate_base_url("http://192.0.2.10:8000", allow_remote=True) == (
        "http://192.0.2.10:8000"
    )
    with pytest.raises(ValueError):
        harness.validate_base_url("ftp://127.0.0.1:8000", allow_remote=False)
    with pytest.raises(ValueError):
        harness.validate_base_url("http://127.0.0.1:8000/api", allow_remote=False)


def test_percentiles_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert harness.percentile(values, 50) == 20.0
    assert harness.percentile(values, 95) == 40.0
    assert harness.percentile(values, 100) == 40.0
    assert harness.percentile([], 95) is None
    with pytest.raises(ValueError):
        harness.percentile(values, 0)


def test_classify_status_and_exception() -> None:
    assert harness.classify_status(200) == "2xx"
    assert harness.classify_status(302) == "3xx"
    assert harness.classify_status(404) == "4xx"
    assert harness.classify_status(503) == "5xx"
    assert harness.classify_exception(httpx.ConnectError("boom")) == "connection_error"
    assert harness.classify_exception(httpx.ReadTimeout("slow")) == "timeout"
    assert harness.classify_exception(httpx.HTTPError("bad")) == "http_error"
    assert harness.classify_exception(RuntimeError("raro")) == "unexpected_error"


def test_inspect_tenant_payload_detects_foreign_tenant() -> None:
    issues = harness.inspect_tenant_payload(
        {
            "items": [{"tenant_id": "test-load-u2"}],
            "note": "dato de test-load-u3",
        },
        expected_tenant="test-load-u1",
        other_tenants=["test-load-u2", "test-load-u3"],
    )
    assert any("tenant_id=test-load-u2" in issue for issue in issues)
    assert any("menciona test-load-u3" in issue for issue in issues)


def test_dry_run_makes_no_network_calls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("RESEARCH_AUTH_SECRET", raising=False)
    exit_code = harness.main(["--dry-run", "--base-url", "http://127.0.0.1:8000"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "DRY-RUN" in output
    assert "45 en total" in output
    assert "portfolio_summary" in output


def test_main_rejects_remote_without_flag_without_network() -> None:
    exit_code = harness.main(["--dry-run", "--base-url", "http://198.51.100.4:8000"])
    assert exit_code == 2


def test_load_uses_signed_requests_per_tenant_and_computes_stats() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload())
        if request.url.path == "/api/chat":
            return httpx.Response(
                200,
                json={
                    "answer": "ok",
                    "sources": [],
                    "llm_trace": {"path": "chat_synthesis", "fallback": False},
                },
            )
        return httpx.Response(200, json=[])

    report = _run_with_handler(handler, rounds=2)

    assert report["ok"] is True
    assert report["scenarios"]["health_live"]["count"] == 6
    assert report["scenarios"]["chat"]["count"] == 6
    assert report["isolation"]["ok"] is True
    assert report["chat_fallback_reasons"] == {}
    assert len(seen) == 3 + 3 * 5 * 2

    tenants = {request.headers["x-cavaai-tenant"] for request in seen}
    assert tenants == {"test-load-u1", "test-load-u2", "test-load-u3"}
    nonces = [request.headers["x-cavaai-nonce"] for request in seen]
    assert len(nonces) == len(set(nonces))

    for request in seen:
        if request.url.path == "/api/screeners/real":
            assert request.url.query == b"limit=5"
            assert request.headers["x-cavaai-path"] == "/api/screeners/real"
        if request.url.path == "/api/chat":
            digest = hashlib.sha256(request.content).hexdigest()
            assert request.headers["x-cavaai-body-hash"] == digest
            assert request.headers["x-cavaai-method"] == "POST"

    for tenant, scenarios in report["per_user"].items():
        assert tenant in tenants
        assert scenarios["portfolio_summary"]["count"] == 2


def test_no_llm_configured_omits_chat() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload(configured=False))
        return httpx.Response(200, json=[])

    report = _run_with_handler(handler, rounds=1)

    assert "chat" not in report["scenarios"]
    assert any("llm.configured=false" in note for note in report["notes"])
    assert report["ok"] is True


def test_skip_llm_omits_chat_even_when_configured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload(configured=True))
        return httpx.Response(200, json=[])

    report = _run_with_handler(handler, rounds=1, skip_llm=True)

    assert "chat" not in report["scenarios"]
    assert any("--skip-llm" in note for note in report["notes"])


def test_settings_without_tenant_scope_fails_isolation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload(configured=False, scoped=False))
        return httpx.Response(200, json=[])

    report = _run_with_handler(handler, rounds=1)

    assert report["ok"] is False
    assert report["isolation"]["ok"] is False
    assert any("aislamiento" in failure for failure in report["failures"])


def test_five_hundred_marks_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload(configured=False))
        if request.url.path == "/api/companies/thesis-tickers":
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json=[])

    report = _run_with_handler(handler, rounds=1)

    assert report["ok"] is False
    assert report["scenarios"]["thesis_tickers"]["5xx"] == 3
    assert any("5xx en thesis_tickers" in failure for failure in report["failures"])


def test_connection_error_is_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload(configured=False))
        if request.url.path == "/api/portfolio/summary":
            raise httpx.ConnectError("sin backend", request=request)
        return httpx.Response(200, json=[])

    report = _run_with_handler(handler, rounds=1)

    assert report["ok"] is False
    assert report["scenarios"]["portfolio_summary"]["connection_error"] == 3
    assert any(
        "errores de conexion/timeout en portfolio_summary" in failure for failure in report["failures"]
    )


def test_slow_p95_marks_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload(configured=False))
        if request.url.path == "/health/live":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json=[])

    cfg = LoadConfig(
        base_url="http://127.0.0.1:8000",
        rounds=1,
        timeout_s=10.0,
        p95_ms=0.01,
        chat_p95_ms=30000.0,
        skip_llm=True,
    )
    identities = harness.build_identities("test-load")

    async def runner() -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=cfg.base_url, transport=httpx.MockTransport(handler)) as client:
            return await harness.run_load(
                client,
                cfg=cfg,
                secret="s" * 32,
                identities=identities,
                portfolio_path=harness.DEFAULT_PORTFOLIO_PATH,
            )

    report = asyncio.run(runner())

    assert report["ok"] is False
    assert any("supera el umbral" in failure for failure in report["failures"])


def test_inicio_watchlist_profile_adds_readonly_scenarios() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload())
        return httpx.Response(200, json={"items": [], "page_info": {"has_next": False}})

    report = _run_with_handler(handler, rounds=2, skip_llm=True, inicio_watchlist=True)

    for key in (
        "watchlist_list",
        "watchlist_monitor",
        "calendar_earnings",
        "metric_coverage",
        "data_health",
    ):
        assert report["scenarios"][key]["count"] == 6, key
    assert any("inicio-watchlist" in note for note in report["notes"])

    new_paths = {
        "/api/watchlist",
        "/api/watchlist/monitor",
        "/api/calendar/earnings",
        "/api/screeners/metric-coverage",
        "/api/data-health",
    }
    new_requests = [request for request in seen if request.url.path in new_paths]
    assert len(new_requests) == 5 * 3 * 2  # 5 escenarios x 3 usuarios x 2 rondas
    assert {request.method for request in new_requests} == {"GET"}
    monitor = [request for request in new_requests if request.url.path == "/api/watchlist/monitor"]
    assert monitor and all(request.url.query == b"tickers=MSFT,NVDA,ASTS" for request in monitor)


def test_inicio_watchlist_profile_off_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/settings":
            return httpx.Response(200, json=_settings_payload())
        return httpx.Response(200, json=[])

    report = _run_with_handler(handler, rounds=1, skip_llm=True)

    assert "watchlist_list" not in report["scenarios"]
    assert "data_health" not in report["scenarios"]


def test_parse_args_inicio_watchlist_flag() -> None:
    assert harness.parse_args([]).inicio_watchlist is False
    assert harness.parse_args(["--inicio-watchlist"]).inicio_watchlist is True
