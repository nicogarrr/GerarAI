"""Cheap LLM readiness checks (configuration only, no paid generations).

``/health/ready`` uses these helpers to fail closed when the configured provider
cannot work. The only optional network probe is the local OpenCode bridge
``/health`` endpoint, which never leaves the host/docker network; official
providers are never contacted by readiness.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.llm.model_aliases import is_owner_approved_model

_OPENCODE_GO_PROVIDERS = frozenset({"auto", "opencode", "opencode_go", "opencode-go"})
_LOCAL_BRIDGE_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "host.docker.internal", "opencode-bridge", "bridge"}
)


def _provider(settings: object) -> str:
    requested = str(getattr(settings, "llm_provider", "") or "").strip().lower()
    return "opencode-go" if requested in _OPENCODE_GO_PROVIDERS else requested


def _has_key(value: object) -> bool:
    return bool(str(value or "").strip())


def _valid_http_url(value: object) -> bool:
    try:
        parts = urlsplit(str(value or ""))
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def llm_configuration_issue(settings: object) -> str | None:
    """Return a stable reason code when the LLM config is disabled/incoherent."""
    if not bool(getattr(settings, "llm_enabled", True)):
        return "disabled_by_configuration"
    provider = _provider(settings)
    if provider == "disabled":
        return "disabled_by_configuration"
    if provider == "opencode-go":
        if not _has_key(getattr(settings, "opencode_go_api_key", None)):
            return "opencode_go_api_key_not_configured"
        if not _valid_http_url(getattr(settings, "opencode_go_base_url", "")):
            return "opencode_go_base_url_invalid"
        if not is_owner_approved_model(
            str(getattr(settings, "opencode_go_model", "") or "").strip(), settings
        ):
            return "opencode_go_model_not_owner_approved"
        fallback = str(getattr(settings, "opencode_go_fallback_model", "") or "").strip()
        if fallback and not is_owner_approved_model(fallback, settings):
            return "opencode_go_fallback_not_owner_approved"
        if bool(getattr(settings, "chat_go_subscription_enabled", False)) and not _valid_http_url(
            getattr(settings, "chat_go_subscription_base_url", "")
        ):
            return "chat_go_subscription_base_url_invalid"
        return None
    if provider == "cascade":
        has_member = any(
            _has_key(getattr(settings, name, None))
            for name in ("gemini_api_key", "openrouter_api_key", "opencode_go_api_key")
        )
        return None if has_member else "cascade_without_any_api_key"
    return "unsupported_llm_provider"


def bridge_health_url(base_url: object) -> str | None:
    """Return the local bridge ``/health`` URL, or None for remote providers.

    Only loopback/docker-internal hosts are probed, so CI and production
    readiness never make external network calls.
    """
    try:
        parts = urlsplit(str(base_url or ""))
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    if host not in _LOCAL_BRIDGE_HOSTS and not host.startswith("127."):
        return None
    return f"{parts.scheme}://{parts.netloc}/health"
