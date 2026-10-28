"""Bounded tenant-scoped display translation of external news. Originals are immutable."""
from __future__ import annotations

import asyncio
import json
import re
import time
from difflib import SequenceMatcher
from types import SimpleNamespace

from app.core.config import get_settings
from app.llm import LLMRequest, Message, ResponseFormat, create_llm_provider, parse_json_response
from app.services.asts_llm_quota import reserve_quota
from app.services.knowledge_rag.query_translation import _resolved_verified_free_model
from app.services.news_headline_translation import NON_LATIN, QUOTA, fingerprint, headline_numbers_match
from app.services.prompt_registry import get_prompt

_PROMPT = get_prompt("public_headline_translation", allow_remote=False)

_cache: dict[tuple[int, str], tuple[float, dict]] = {}
_slots = asyncio.Semaphore(2)


# Marcas de idioma compartidas con el front (lib/news-language.ts). Regla
# (decisión del auditor, 19-oct-2026): sin marcas claras NO es traducible,
# salvo una señal latina-inglesa explícita: el titular en Title Case de >=3
# palabras, convención de la prensa anglosajona («Meta Llama Beats Rivals
# Again»). Así «Inditex bate previsiones» no gasta presupuesto ni puede
# mostrar «Traducción automática» sobre texto ya español.
_ENGLISH_MARK = re.compile(
    r"\b(the|with|says|shares|stocks|earnings|reports|raises|falls|after|amid|outlook|growth|investors|market|billion|million|revenue|warns|cuts|for|and|as|to|in)\b",
    re.IGNORECASE,
)
_SPANISH_MARK = re.compile(
    r"\b(el|la|los|las|una?|de|del|que|en|para|por|con|sus|más|años?|empresa|"
    r"acciones|según|tras|sobre|está|están|han|será|anuncia|sube|baja|informa)\b"
    r"|[áéíóúñ]|[¿¡]",
    re.IGNORECASE,
)
_TITLE_CASE_WORD = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñü]{2,}\b")


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wáéíóúñü]+", " ", text.lower())).strip()


def _nearly_identical(original: str, text: str) -> bool:
    # Si la «traducción» apenas difiere del original, el modelo no tradujo
    # (p. ej. devolvió el texto ya español): no se marca como traducida.
    return SequenceMatcher(None, _normalized(original), _normalized(text)).ratio() >= 0.9


def needs_translation(text: str) -> bool:
    if NON_LATIN.search(text):
        return True
    if _ENGLISH_MARK.search(text):
        return True
    if _SPANISH_MARK.search(text):
        return False
    return len(_TITLE_CASE_WORD.findall(text)) >= 3


def free_provider():
    settings = get_settings()
    model = settings.opencode_go_model
    if _resolved_verified_free_model(model, settings) is None:
        return None, None
    # A cascade can contain billable keys. Pin its verified-free OpenCode member only.
    pinned = settings.model_copy(update={"llm_provider": "opencode-go", "llm_model_overrides": {}, "opencode_go_fallback_model": ""})
    return create_llm_provider(pinned), model


def free_provider_chain() -> list:
    """Cadena gratuita verificada, mismo orden que el chat: OpenCode -> Groq -> Gemini.

    Cada eslabón usa los builders con sus puertas de plan gratuito verificado
    (``_groq_backup``/``_gemini_backup``): un respaldo desactivado o mal
    configurado simplemente no entra en la cadena. Vacía si no hay ninguno:
    la traducción se declara no disponible, nunca se inventa.
    """
    from app.llm.chat_provider import (
        GEMINI_MODEL,
        GEMINI_MODEL_2,
        GROQ_MODEL,
        _gemini_backup,
        _groq_backup,
    )

    settings = get_settings()
    chain = []
    provider, model = free_provider()
    if provider is not None:
        chain.append((provider, model))
    try:
        groq = _groq_backup(settings, None)
    except ValueError:
        groq = None
    if groq is not None:
        chain.append((groq, GROQ_MODEL))
    try:
        gemini = _gemini_backup(settings, None)
    except ValueError:
        gemini = None
    if gemini is not None:
        chain.append((gemini, GEMINI_MODEL))
        chain.append((gemini, GEMINI_MODEL_2))
    return chain


async def translate_external_headline(db, original: str, *, provider=None) -> dict:
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise PermissionError("Tenant context required")
    result = {"status": "unavailable", "text": None, "original": original, "target_language": "es", "machine_translation": True}
    if not needs_translation(original):
        return {**result, "status": "not_needed"}
    key = (tenant, fingerprint(original))
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    if _slots.locked():
        return {**result, "status": "busy"}
    async with _slots:
        # Recheck after waiting to avoid duplicate calls within this worker.
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        # nosemgrep: gerarai-broad-except-pass -- traduccion opcional: si falla se muestra el titular original
        try:
            chain = [(provider, None)] if provider is not None else free_provider_chain()
            chain = [(candidate, m) for candidate, m in chain if candidate is not None and candidate.name != "disabled"]
            if not chain:
                raise RuntimeError("No verified free provider")
            settings = get_settings()
            quota = SimpleNamespace(is_production=settings.is_production, redis_url=settings.redis_url, minute_limit=10, day_limit=100)
            if not reserve_quota(tenant, quota, namespace=QUOTA)["allowed"]:
                raise RuntimeError("Quota")
            # Cadena OpenCode -> Groq -> Gemini: el primer candidato con una
            # traducción valida gana; un fallo (red, cuota del proveedor,
            # salida inválida) pasa al siguiente. Si todos fallan, el estado
            # queda "unavailable": nunca se inventa un titular.
            for candidate, model in chain:
                try:
                    response = await asyncio.wait_for(candidate.complete(LLMRequest(
                        model=model, messages=[Message("system", _PROMPT.text),
                                               Message("user", json.dumps({"headline": original}, ensure_ascii=False))],
                        temperature=0, max_tokens=800, reasoning_effort=settings.reasoning_effort_for("traduccion_titular"), metadata={**_PROMPT.trace_metadata(), "tenant_id": str(tenant)}, response_format=ResponseFormat.json_object(),
                    )), timeout=20)
                except Exception:
                    continue
                payload = parse_json_response(response.text)
                text = payload.get("text") if isinstance(payload, dict) else None
                if (isinstance(text, str) and 3 <= len(text.strip()) <= 500 and text.strip() != original
                        and not NON_LATIN.search(text) and not response.degraded and not response.warnings
                        and headline_numbers_match(original, text)
                        and not _nearly_identical(original, text.strip())):
                    result = {**result, "status": "translated", "text": text.strip()}
                    break
        except Exception:
            pass  # The caller still has the linked original, never a made-up translation.
        # Both success and failure are cached; provider also has a tenant-scoped Redis cache.
        for expired in [k for k, (expiry, _) in _cache.items() if expiry <= now]:
            _cache.pop(expired, None)
        while len(_cache) >= 512:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic() + (86400 if result["status"] == "translated" else 600), result)
        return result
