"""Local, read-only readiness. No provider calls and no quota promise."""
import math
import time
from typing import Literal

from app.core.config import get_settings
from app.llm import base
from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, Message

Feature = Literal['chat', 'thesis', 'analysis', 'debate']


def _leaves(provider):
    seen = set()
    def visit(p):
        if id(p) in seen:
            return
        seen.add(id(p))
        if hasattr(p, '_api_key'):
            yield p
            return
        for name in ('primary', 'backup', 'backup2', 'members', 'extra_backups'):
            value = getattr(p, name, None)
            values = value if isinstance(value, (list, tuple)) else (value,)
            for child in values:
                if isinstance(child, tuple):
                    child = child[0]
                if isinstance(child, LLMProvider):
                    yield from visit(child)
    return list(visit(provider))


def _paused(p, model):
    now = time.monotonic()
    key = (p.name, model)
    credential_key = (*key, base._credential_fingerprint({'Authorization': f'Bearer {p._api_key}'}))
    entries = [(base._free_tier_breaker.get(key, 0), 'origin'),
               (base._interactive_quota_breaker.get(key, 0), 'quota'),
               (base._free_quota_breaker.get(credential_key, 0), 'quota'),
               (base._payment_required_breaker.get(credential_key, 0), 'payment')]
    until, reason = max(entries)
    return (max(0, math.ceil(until - now)), reason)


def availability(feature: Feature, settings=None):
    from app.llm.chat_provider import create_chat_llm_provider
    from app.llm.factory import create_llm_provider
    from app.llm.free_interactive import create_free_interactive_provider
    from app.llm.thesis_go import create_thesis_narrative_provider
    factories = {'chat': create_chat_llm_provider, 'analysis': create_llm_provider,
                 'thesis': create_thesis_narrative_provider, 'debate': create_free_interactive_provider}
    cfg = settings or get_settings()
    try:
        leaves = _leaves(factories[feature](cfg))
    except (RuntimeError, ValueError):
        leaves = []
    result = {'feature': feature, 'state': 'off', 'can_start': False,
              'reason': 'disabled', 'retry_after_seconds': None}
    if not leaves:
        return result
    request = LLMRequest([Message('user', 'availability probe: local only')], task='chat' if feature == 'chat' else 'main_financial_analysis')
    states = []
    for leaf in leaves:
        try:
            model = leaf.model_router.resolve(request)
            states.append(_paused(leaf, model))
        except (RuntimeError, ValueError, KeyError):
            states.append((0, 'unknown'))
    open_states = [s for s in states if s[0] > 0]
    if len(open_states) == len(states):
        seconds, reason = min(open_states)
        return {**result, 'state': 'paused', 'reason': reason, 'retry_after_seconds': seconds}
    return {**result, 'state': 'degraded' if open_states else 'unverified',
            'can_start': True, 'reason': 'fallback' if open_states else 'not_probed'}
