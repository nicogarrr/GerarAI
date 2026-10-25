"""LLM readiness: cheap config check, 503 on disabled/incoherent config.

No external network: only the local bridge health URL may be hit, and the test
stubs urlopen.
"""

from __future__ import annotations

import asyncio
import json

import main
from app.core.config import Settings
from app.llm.readiness import bridge_health_url, llm_configuration_issue


def _settings(**extra) -> Settings:
    base = dict(_env_file=None, app_env="test")
    base.update(extra)
    return Settings(**base)


def test_missing_key_is_not_ready() -> None:
    assert (
        llm_configuration_issue(_settings(opencode_go_api_key=None))
        == "opencode_go_api_key_not_configured"
    )


def test_default_approved_config_is_ready() -> None:
    settings = _settings(opencode_go_api_key="test-key-not-real")
    assert llm_configuration_issue(settings) is None


def test_disabled_or_unapproved_config_is_not_ready() -> None:
    assert llm_configuration_issue(_settings(llm_enabled=False)) == "disabled_by_configuration"
    assert (
        llm_configuration_issue(
            _settings(
                opencode_go_api_key="test-key-not-real",
                opencode_go_model="paid-model-unknown",
            )
        )
        == "opencode_go_model_not_owner_approved"
    )
    assert (
        llm_configuration_issue(
            _settings(
                opencode_go_api_key="test-key-not-real",
                opencode_go_fallback_model="paid-model-unknown",
            )
        )
        == "opencode_go_fallback_not_owner_approved"
    )
    assert (
        llm_configuration_issue(
            _settings(
                opencode_go_api_key="test-key-not-real",
                opencode_go_base_url="not-a-url",
            )
        )
        == "opencode_go_base_url_invalid"
    )


def test_bridge_health_is_only_probed_for_local_hosts() -> None:
    assert bridge_health_url("https://opencode.ai/zen/go/v1") is None
    assert bridge_health_url("http://127.0.0.1:4098/v1") == "http://127.0.0.1:4098/health"
    assert bridge_health_url("http://opencode-bridge:4098/v1") == (
        "http://opencode-bridge:4098/health"
    )


def _patch_checks(monkeypatch, settings) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "_probe_database", lambda _settings: "ok")
    monkeypatch.setattr(main, "_probe_redis", lambda _settings: "ok")
    monkeypatch.setattr(main, "_probe_qdrant", lambda _settings: "ok")
    monkeypatch.setattr(main, "_probe_minio", lambda _settings: "ok")


def _ready() -> tuple[int, dict]:
    response = asyncio.run(main.health_ready())
    return response.status_code, json.loads(response.body)


def test_readiness_is_503_when_the_llm_is_disabled(monkeypatch) -> None:
    _patch_checks(monkeypatch, _settings(opencode_go_api_key=None))
    status, body = _ready()
    assert status == 503
    assert body["status"] == "degraded"
    assert body["checks"]["llm"] == "error:opencode_go_api_key_not_configured"


def test_readiness_is_200_with_the_approved_go_config(monkeypatch) -> None:
    _patch_checks(monkeypatch, _settings(opencode_go_api_key="test-key-not-real"))
    status, body = _ready()
    assert status == 200
    assert body["status"] == "ready"
    assert body["checks"]["llm"] == "ok"


def test_readiness_probes_the_local_bridge_health(monkeypatch) -> None:
    calls: list[str] = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(url, timeout=0):
        calls.append(url)
        assert timeout == main.HEALTH_READY_TIMEOUT_SECONDS
        return _Response()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    _patch_checks(
        monkeypatch,
        _settings(
            opencode_go_api_key="test-key-not-real",
            opencode_go_base_url="http://127.0.0.1:4098/v1",
        ),
    )
    status, body = _ready()
    assert status == 200 and body["checks"]["llm"] == "ok"
    assert calls == ["http://127.0.0.1:4098/health"]


def test_readiness_never_calls_remote_providers(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("readiness must not call a remote provider")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    _patch_checks(monkeypatch, _settings(opencode_go_api_key="test-key-not-real"))
    status, body = _ready()
    assert status == 200 and body["checks"]["llm"] == "ok"
