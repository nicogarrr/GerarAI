"""Stage 4: prompt registry — versionado, fallback a codigo, traza."""

import pytest

from app.core.config import get_settings
from app.services import prompt_registry, tracing


@pytest.fixture(autouse=True)
def clean_cache():
    prompt_registry.reset_cache()
    yield
    prompt_registry.reset_cache()


def test_every_registered_prompt_resolves_from_code_by_default():
    for name in prompt_registry.PROMPTS:
        resolved = prompt_registry.get_prompt(name)
        assert resolved.source == "code"
        assert resolved.fallback is True
        assert resolved.text == prompt_registry.PROMPTS[name].text
        assert resolved.version == prompt_registry.PROMPTS[name].version
        assert len(resolved.content_hash) == 12


def test_unknown_prompt_raises():
    with pytest.raises(KeyError):
        prompt_registry.get_prompt("no_existo")


def test_remote_prompt_wins_when_available(monkeypatch):
    monkeypatch.setattr(
        prompt_registry, "_fetch_remote_text", lambda name: "PROMPT REMOTO V2"
    )
    resolved = prompt_registry.get_prompt("chat_source_synthesis")
    assert resolved.source == "remote"
    assert resolved.fallback is False
    assert resolved.text == "PROMPT REMOTO V2"
    # El hash cambia con el contenido: version inmutable real.
    assert resolved.content_hash != prompt_registry.PROMPTS["chat_source_synthesis"].content_hash


def test_remote_failure_falls_back_to_code(monkeypatch):
    def boom(name):
        raise RuntimeError("langfuse caido")

    # _fetch_remote_text nunca lanza; simulamos el path interno.
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr("langfuse.Langfuse", lambda **kw: boom("x"))
        resolved = prompt_registry.get_prompt("thesis_debate_judge")
        assert resolved.source == "code"
        assert resolved.text == prompt_registry.DEBATE_JUDGE
    finally:
        get_settings.cache_clear()


def test_trace_metadata_carries_prompt_identity():
    resolved = prompt_registry.get_prompt("company_kpi_extraction")
    meta = resolved.trace_metadata()
    assert meta["prompt_name"] == "company_kpi_extraction"
    assert meta["prompt_version"] == "company-kpi-extraction-v1"
    assert meta["prompt_source"] == "code"
    assert len(meta["prompt_hash"]) == 12
    # Y las claves pasan la allowlist de tracing (llegan al span).
    clean = tracing.sanitize_metadata(meta)
    assert clean == meta


def test_migrated_services_use_registry_text():
    from app.services import (
        chat_synthesis_service,
        knowledge_library_service,
        kpi_extraction_service,
    )

    assert chat_synthesis_service.PROMPT_VERSION == "source-aware-synthesis-v5"
    assert kpi_extraction_service.PROMPT_VERSION == "company-kpi-extraction-v1"
    assert (
        knowledge_library_service.PRINCIPLE_PROMPT_VERSION
        == "investment-principles-v2-batched"
    )
    # Los textos que usan los servicios son los del registry.
    assert (
        prompt_registry.get_prompt("chat_source_synthesis", allow_remote=False).text
        == prompt_registry.CHAT_SOURCE_SYNTHESIS
    )
    assert (
        prompt_registry.get_prompt("company_kpi_extraction", allow_remote=False).text
        == prompt_registry.COMPANY_KPI_EXTRACTION
    )
    assert (
        prompt_registry.get_prompt("investment_principles", allow_remote=False).text
        == prompt_registry.INVESTMENT_PRINCIPLES
    )
