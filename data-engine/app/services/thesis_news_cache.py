"""Best-effort Redis reuse of validated news narratives for identical inputs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from app.core import cache
from app.core.i18n import current_language

TTL_SECONDS = 24 * 60 * 60
MAX_VALUE_BYTES = 32 * 1024


def input_key(db, request, provider) -> str | None:
    """No unscoped entries, credentials, source text or endpoints in Redis keys."""
    tenant = (getattr(db, "info", None) or {}).get("tenant_id")
    if request.cache is False:
        return None
    if not isinstance(tenant, int) or isinstance(tenant, bool) or tenant <= 0:
        return None
    try:
        model = provider.model_router.resolve(request)
        if not isinstance(model, str) or not model:
            return None
        configuration = {
            name: getattr(provider, name, None)
            for name in (
                "name", "_base_url", "_fallback_model", "_reasoning_effort",
                "_max_output_tokens", "_strip_response_format",
                "_hidden_reasoning_min_tokens",
            )
        }
        # Rotation must not reuse a response from a previous credential.
        # Only a digest enters the identity; never serialize the credential.
        credential = getattr(provider, "_api_key", "") or ""
        configuration["credential_sha256"] = hashlib.sha256(credential.encode()).hexdigest()
        configuration["headers_sha256"] = hashlib.sha256(json.dumps(
            getattr(provider, "_extra_headers", {}), sort_keys=True,
        ).encode()).hexdigest()
        for name in ("_reasoning_effort_models", "_hidden_reasoning_models"):
            values = getattr(provider, name, ()) or ()
            configuration[name] = sorted(values)
        identity = {
            "tenant": tenant, "language": current_language(),
            "session_language": (getattr(db, "info", None) or {}).get("language"),
            "request": asdict(request), "model": model,
            "provider_class": f"{type(provider).__module__}.{type(provider).__qualname__}",
            "provider": configuration,
        }
        digest = hashlib.sha256(json.dumps(
            identity, sort_keys=True, ensure_ascii=False, allow_nan=False,
        ).encode()).hexdigest()
        return f"thesis_news:v1:tenant:{tenant}:{digest}"
    except Exception:
        # Unknown/nonserializable configuration must miss, never collide.
        return None


def read(key: str | None):
    if key is None:
        return None
    try:
        client = cache._redis_client()
        if client is None:
            return None
        value = client.get(key)
        if value is None or len(value) > MAX_VALUE_BYTES:
            return None
        return json.loads(value)
    except Exception:
        cache._redis_down()
        return None


def write(key: str | None, raw: dict) -> None:
    if key is None:
        return
    try:
        value = json.dumps(raw, ensure_ascii=False, allow_nan=False)
        if len(value.encode()) > MAX_VALUE_BYTES:
            return
        client = cache._redis_client()
        if client is not None:
            client.set(key, value, ex=TTL_SECONDS)
    except Exception:
        cache._redis_down()
