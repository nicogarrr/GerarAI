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

    assert chat_synthesis_service.PROMPT_VERSION == "source-aware-synthesis-v6"
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


# Hash del texto ANTES de moverlo al registro: si alguien edita el prompt, o su
# version no se mueve con el, este test falla. Cambiar el texto exige subir la
# version y actualizar el hash aqui a proposito.
_THESIS_NARRATIVE_PROMPTS = {
    "thesis_deep_narrative": ("thesis-deep-narrative-v1", "c4dbfb842434", "deep_thesis"),
    "thesis_news_narrative": ("thesis-news-narrative-v1", "6d66c3af37d3", "main_financial_analysis"),
}


@pytest.mark.parametrize("name", sorted(_THESIS_NARRATIVE_PROMPTS))
def test_thesis_narrative_prompt_version_and_hash_are_pinned(name):
    version, content_hash, task = _THESIS_NARRATIVE_PROMPTS[name]
    resolved = prompt_registry.get_prompt(name, allow_remote=False)
    assert (resolved.version, resolved.content_hash, resolved.task) == (version, content_hash, task)
    assert resolved.source == "code"
    assert resolved.trace_metadata() == {
        "prompt_name": name,
        "prompt_version": version,
        "prompt_hash": content_hash,
        "prompt_source": "code",
    }


def test_thesis_narrative_services_use_registry_text_and_trace_it():
    from app.services import thesis_deep_narrative, thesis_news_narrative

    deep = prompt_registry.get_prompt("thesis_deep_narrative", allow_remote=False)
    news = prompt_registry.get_prompt("thesis_news_narrative", allow_remote=False)
    assert thesis_deep_narrative._SYSTEM == deep.text == prompt_registry.THESIS_DEEP_NARRATIVE
    assert thesis_news_narrative._SYSTEM == news.text == prompt_registry.THESIS_NEWS_NARRATIVE

    news_request = thesis_news_narrative.build_request("META", [])
    assert news_request.messages[0].content == news.text
    assert news_request.metadata == news.trace_metadata()
    deep_request = thesis_deep_narrative._build_request([{"id": "f1", "texto": "t", "fuente": "x"}])
    assert deep_request.messages[0].content == deep.text
    assert deep_request.metadata == deep.trace_metadata()


def test_asts_llm_service_prompt_version_and_hash_are_pinned():
    # Hash del texto ANTES de moverlo al registro: editar el prompt sin subir
    # la version (y este hash a proposito) rompe el test.
    resolved = prompt_registry.get_prompt("asts_llm_service", allow_remote=False)
    assert (resolved.version, resolved.content_hash, resolved.task) == (
        "asts-catalog-analysis-v1",
        "bc4b6648d20d",
        "asts_catalog_analysis",
    )
    assert resolved.source == "code"
    assert resolved.text == prompt_registry.ASTS_CATALOG_ANALYSIS


def test_bottleneck_discovery_prompt_version_hash_and_closed_lists_are_pinned():
    from app.services import bottleneck_discovery_service as service

    resolved = prompt_registry.get_prompt("bottleneck_discovery_service", allow_remote=False)
    assert (resolved.version, resolved.content_hash, resolved.task) == (
        "bottleneck-discovery-v1",
        "c5a549ec7b59",
        "bottleneck_discovery",
    )
    assert resolved.source == "code"
    assert service.SYSTEM == resolved.text == prompt_registry.BOTTLENECK_DISCOVERY
    # El registro guarda el texto ya renderizado: las listas cerradas del
    # servicio tienen que seguir apareciendo en el, o el prompt y el schema
    # divergirian (cambiar EXPOSURES/CHANNELS exige subir la version).
    assert "exposicion (una de: " + ", ".join(service.EXPOSURES) + ")" in resolved.text
    assert "canal (uno de: " + ", ".join(service.CHANNELS) + ")" in resolved.text


def test_jev_fallback_prompt_version_and_hash_are_pinned():
    resolved = prompt_registry.get_prompt("jev_fallback", allow_remote=False)
    assert (resolved.version, resolved.content_hash, resolved.task) == (
        "jev-fallback-v1",
        "88d9371956c6",
        "jev_fallback",
    )
    assert resolved.source == "code"
    assert resolved.text == prompt_registry.JEV_FALLBACK
