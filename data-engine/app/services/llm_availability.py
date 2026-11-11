"""Local, read-only readiness. No provider calls and no quota promise."""
import math
import time
from dataclasses import replace
from typing import Literal

from app.core.config import get_settings
from app.llm import base
from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, Message

Feature = Literal['chat', 'thesis', 'analysis', 'debate']


def _candidates(provider, request):
    """Enumerate the same (adapter, model) pairs the execution wrappers use.

    Adapter fallback is sent directly to _complete_traced, not re-resolved.
    Composite explicit models *are* resolved via complete(replace(request,...)).
    A shared adapter can therefore contribute multiple distinct candidates.
    """
    from app.llm.chat_provider import GEMINI_MODELS, ChatFallbackProvider, SequentialFallbackProvider
    seen = set()
    visiting = set()

    def visit(p, req):
        route = (id(p), req.model, req.task)
        if route in visiting:
            return
        visiting.add(route)
        try:
            if hasattr(p, '_api_key'):
                model = p.model_router.resolve(req)
                models = [model]
                fallback = getattr(p, '_fallback_model', None)
                overrides = getattr(p.model_router, 'overrides', None) or {}
                if fallback and fallback != model and overrides.get(fallback, fallback) != model:
                    models.append(fallback)
                for candidate in models:
                    key = (id(p), candidate)
                    if key not in seen:
                        seen.add(key)
                        yield p, candidate
                return
            if isinstance(p, ChatFallbackProvider):
                yield from visit(p.primary, req)
                members = [(p.backup, p.backup_model)]
                if p.backup2 is not None:
                    members += [(p.backup2, model) for model in GEMINI_MODELS]
                members += list(p.extra_backups)
                for child, model in members:
                    yield from visit(child, replace(req, model=model))
                return
            if isinstance(p, SequentialFallbackProvider):
                yield from visit(p.primary, req)
                for child, models in ((p.backup, p.backup_models), (p.backup2, p.backup2_models)):
                    if child is not None:
                        for model in models:
                            yield from visit(child, replace(req, model=model))
                return
            for child in getattr(p, 'members', ()):
                if isinstance(child, LLMProvider):
                    yield from visit(child, req)
        finally:
            visiting.remove(route)
    return list(visit(provider, request))


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
    request = LLMRequest([Message('user', 'availability probe: local only')], task='chat' if feature == 'chat' else 'main_financial_analysis')
    try:
        candidates = _candidates(factories[feature](cfg), request)
    except (RuntimeError, ValueError):
        candidates = []
    result = {'feature': feature, 'state': 'off', 'can_start': False,
              'reason': 'disabled', 'retry_after_seconds': None}
    if not candidates:
        return result
    states = [_paused(leaf, model) for leaf, model in candidates]
    open_states = [s for s in states if s[0] > 0]
    if len(open_states) == len(states):
        seconds, reason = min(open_states)
        return {**result, 'state': 'paused', 'reason': reason, 'retry_after_seconds': seconds}
    return {**result, 'state': 'degraded' if open_states else 'unverified',
            'can_start': True, 'reason': 'fallback' if open_states else 'not_probed'}
