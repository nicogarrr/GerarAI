"""Feature-only HTTP attempt cap. No scope means no change to other LLM work."""
from __future__ import annotations

import contextlib
import contextvars
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from app.llm.errors import LLMError

DAILY_ATTEMPTS = 10
GLOBAL_DAILY_ATTEMPTS = 30
ENABLED_KEY = "cavaai:thesis-input-inference:enabled"
MAX_OUTPUT_TOKENS = 700
MAX_REQUEST_BYTES = 65_536
MODEL = "deepseek-v4.1-flash"
_current: contextvars.ContextVar[int | None] = contextvars.ContextVar("thesis_inference_tenant", default=None)
_SCRIPT = """
if redis.call('GET', KEYS[3]) == '0' then return -1 end
local tenant = tonumber(redis.call('GET', KEYS[1]) or '0')
local global = tonumber(redis.call('GET', KEYS[2]) or '0')
if tenant >= tonumber(ARGV[1]) or global >= tonumber(ARGV[2]) then return 0 end
local t = redis.call('INCR', KEYS[1])
local g = redis.call('INCR', KEYS[2])
if t == 1 then redis.call('EXPIRE', KEYS[1], 172800) end
if g == 1 then redis.call('EXPIRE', KEYS[2], 172800) end
return t
"""


class ThesisInferenceQuotaError(LLMError):
    pass


@contextlib.contextmanager
def scope(tenant_id: int):
    if type(tenant_id) is not int or tenant_id <= 0:
        raise ThesisInferenceQuotaError("verified_tenant_required")
    token = _current.set(tenant_id)
    try:
        yield
    finally:
        _current.reset(token)


def _reserve(tenant: int, now: datetime) -> None:
    from app.core.cache import _redis_client

    client = _redis_client()
    if client is None:
        raise ThesisInferenceQuotaError("attempt_store_unavailable")
    key = f"cavaai:thesis-input-inference:{tenant}:day:{now:%Y%m%d}"
    try:
        global_key = f"cavaai:thesis-input-inference:global:day:{now:%Y%m%d}"
        allowed = int(client.eval(_SCRIPT, 3, key, global_key, ENABLED_KEY, DAILY_ATTEMPTS, GLOBAL_DAILY_ATTEMPTS))
    except Exception:
        raise ThesisInferenceQuotaError("attempt_store_unavailable") from None
    if allowed == -1:
        raise ThesisInferenceQuotaError("feature_disabled")
    if not allowed:
        raise ThesisInferenceQuotaError("daily_attempts_exhausted")


def reserve_request(url: str, payload: Any) -> None:
    tenant = _current.get()
    if tenant is None:
        return
    parsed = urlparse(str(url))
    if (parsed.scheme, parsed.netloc, parsed.path) != (
        "https", "opencode.ai", "/zen/go/v1/chat/completions"
    ):
        raise ThesisInferenceQuotaError("go_subscription_destination_required")
    if payload.get("model") != MODEL:
        raise ThesisInferenceQuotaError("go_subscription_model_required")
    tokens = payload.get("max_tokens")
    if type(tokens) is not int or not 0 < tokens <= MAX_OUTPUT_TOKENS:
        raise ThesisInferenceQuotaError("output_tokens_exceeded")
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ThesisInferenceQuotaError("request_bytes_exceeded")
    _reserve(tenant, datetime.now(UTC))
