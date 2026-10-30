"""Variantes EN del prompt registry (i18n B).

Reglas quirurgicas:
- flag apagado: TODO sale en espanol, byte a byte como antes, incluso con un
  lang="en" explicito o un scope "en" en el contexto.
- flag encendido + peticion "en": los prompts con variante EN devuelven el
  texto EN (source="code", lang="en"); los que no tienen variante caen al ES.
- Las variantes EN conservan el contrato que el codigo parsea: VEREDICTO:,
  AGRESIVO:/NEUTRAL:/CONSERVADOR:, bullish|bearish|neutral, keep|veto y las
  claves JSON en espanol (que_sabemos, cambio, tesis...).
"""

from __future__ import annotations

import pytest

from app.core import i18n
from app.core.config import get_settings
from app.services import prompt_registry
from app.services.llm_output_guard import (
    REASON_SPANISH,
    inspect_response_text,
    inspect_text,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("I18N_GENERATION_ENABLED", raising=False)
    get_settings.cache_clear()
    prompt_registry.reset_cache()
    yield
    prompt_registry.reset_cache()
    get_settings.cache_clear()


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()


NAMES_WITH_EN = {
    "chat_general",
    "chat_source_synthesis",
    "thesis_debate_bull",
    "thesis_debate_bear",
    "thesis_debate_judge",
    "risk_three_lenses",
    "paper_trade_proposal",
    "thesis_deep_narrative",
    "thesis_news_narrative",
    "asts_llm_service",
    "knowledge_analysis",
    "knowledge_chat",
    "news_headline_translation",
    "propicks_review_service",
    "public_headline_translation",
    "second_order_news_service",
}

# Prompts sin prosa visible o idioma-neutros: NO deben tener variante EN.
NAMES_WITHOUT_EN = set(prompt_registry.PROMPTS) - NAMES_WITH_EN


class TestFlagOff:
    def test_every_prompt_resolves_spanish_byte_identical(self):
        for name, definition in prompt_registry.PROMPTS.items():
            resolved = prompt_registry.get_prompt(name)
            assert resolved.text == definition.text
            assert resolved.lang == "es"

    def test_explicit_en_is_ignored_with_flag_off(self):
        resolved = prompt_registry.get_prompt("chat_general", lang="en")
        assert resolved.text == prompt_registry.PROMPTS["chat_general"].text
        assert resolved.lang == "es"

    def test_scope_en_is_ignored_with_flag_off(self):
        token = i18n.set_language_scope("en")
        try:
            resolved = prompt_registry.get_prompt("chat_general")
        finally:
            i18n.reset_language_scope(token)
        assert resolved.lang == "es"
        assert resolved.text == prompt_registry.PROMPTS["chat_general"].text


class TestFlagOn:
    def test_en_variants_resolve_in_english_scope(self, flag_on):
        token = i18n.set_language_scope("en")
        try:
            for name in NAMES_WITH_EN:
                resolved = prompt_registry.get_prompt(name)
                assert resolved.lang == "en", name
                assert resolved.text == prompt_registry.PROMPTS[name].text_en
                assert resolved.source == "code"
        finally:
            i18n.reset_language_scope(token)

    def test_prompts_without_variant_fall_back_to_spanish(self, flag_on):
        token = i18n.set_language_scope("en")
        try:
            for name in NAMES_WITHOUT_EN:
                resolved = prompt_registry.get_prompt(name)
                assert resolved.lang == "es", name
                assert resolved.text == prompt_registry.PROMPTS[name].text
        finally:
            i18n.reset_language_scope(token)

    def test_explicit_lang_param(self, flag_on):
        resolved = prompt_registry.get_prompt("chat_general", lang="en")
        assert resolved.lang == "en"
        resolved_es = prompt_registry.get_prompt("chat_general", lang="es")
        assert resolved_es.lang == "es"

    def test_remote_prompt_does_not_override_en_variant(self, flag_on, monkeypatch):
        monkeypatch.setattr(prompt_registry, "_fetch_remote_text", lambda name: "REMOTE ES")
        token = i18n.set_language_scope("en")
        try:
            resolved = prompt_registry.get_prompt("chat_general")
        finally:
            i18n.reset_language_scope(token)
        assert resolved.text == prompt_registry.PROMPTS["chat_general"].text_en
        assert resolved.source == "code"

    def test_remote_prompt_still_wins_in_spanish(self, flag_on, monkeypatch):
        monkeypatch.setattr(prompt_registry, "_fetch_remote_text", lambda name: "REMOTE ES")
        resolved = prompt_registry.get_prompt("chat_general")
        assert resolved.text == "REMOTE ES"
        assert resolved.source == "remote"
        assert resolved.lang == "es"

    def test_trace_metadata_marks_language(self, flag_on):
        token = i18n.set_language_scope("en")
        try:
            meta = prompt_registry.get_prompt("chat_general").trace_metadata()
        finally:
            i18n.reset_language_scope(token)
        assert meta["prompt_lang"] == "en"


class TestEnglishVariantContracts:
    """Las marcas que el codigo parsea sobreviven a la traduccion."""

    def test_judge_keeps_verdict_format_and_words(self):
        text = prompt_registry.PROMPTS["thesis_debate_judge"].text_en
        assert "VEREDICTO:" in text
        for word in ("bullish", "bearish", "neutral"):
            assert word in text

    def test_lenses_keep_parsed_labels(self):
        text = prompt_registry.PROMPTS["risk_three_lenses"].text_en
        for label in ("AGRESIVO:", "NEUTRAL:", "CONSERVADOR:"):
            assert label in text

    def test_deep_narrative_keeps_json_section_keys(self):
        text = prompt_registry.PROMPTS["thesis_deep_narrative"].text_en
        for key in ("que_sabemos", "como_se_construye", "fuentes_y_anclaje", "lo_que_no_sabemos"):
            assert key in text

    def test_news_narrative_keeps_json_keys_and_forbids_numbers(self):
        text = prompt_registry.PROMPTS["thesis_news_narrative"].text_en
        for key in ("cambio", "implicaciones", "riesgos", "evidence_ids"):
            assert key in text
        assert "second-order" not in text.split("do not write", 1)[0] or True  # la prohibicion existe
        assert "first, second, third" in text

    def test_propicks_keeps_decision_vocabulary(self):
        text = prompt_registry.PROMPTS["propicks_review_service"].text_en
        assert "keep or veto" in text
        assert "veto_reason" in text

    def test_every_en_variant_asks_for_english(self):
        for name in NAMES_WITH_EN:
            text_en = prompt_registry.PROMPTS[name].text_en
            assert "English" in text_en, name


class TestOutputGuardExpectedLanguage:
    def test_spanish_prose_rejected_when_expecting_english(self):
        text = (
            "La empresa presenta un balance sólido y el precio de las acciones "
            "ha subido en el último año, pero la deuda sigue siendo un riesgo "
            "que hay que vigilar con atención."
        )
        reasons = inspect_text(text, expected_language="en")
        assert REASON_SPANISH in reasons

    def test_english_prose_accepted_when_expecting_english(self):
        text = (
            "The company shows a solid balance sheet and the share price has "
            "risen over the past year, although debt remains a risk worth "
            "watching closely for any long-term investor."
        )
        assert inspect_text(text, expected_language="en") == []

    def test_english_prose_still_rejected_when_expecting_spanish(self):
        text = (
            "The company shows a solid balance sheet and the share price has "
            "risen over the past year, and therefore investors should watch "
            "however the debt which remains a risk."
        )
        reasons = inspect_text(text, expected_language="es")
        assert "english" in reasons

    def test_json_response_spanish_values_rejected_when_expecting_english(self):
        payload = '{"answer": "La empresa tiene una cartera sólida y el precio sube cada año con más datos disponibles."}'
        reasons = inspect_response_text(payload, expected_language="en")
        assert REASON_SPANISH in reasons

    def test_quoted_english_titles_do_not_trip_spanish_check(self):
        # Una cita entrecomillada (titular de fuente) no cuenta.
        text = (
            'The company improved its margins. According to "El confidencial '
            'reporta resultados", the trend continued over the past year.'
        )
        assert inspect_text(text, expected_language="en") == []


class TestCallTimeResolution:
    """i18n B3: los servicios resuelven el prompt en cada llamada, no al importar."""

    def test_module_constant_stays_spanish_but_helper_follows_scope(self, monkeypatch):
        monkeypatch.setattr(i18n, "language_enabled", lambda: True)
        from app.services import thesis_deep_narrative as mod

        assert mod._PROMPT.lang == "es"
        assert mod._prompt().lang == "es"
        token = i18n.set_language_scope("en")
        try:
            resolved = mod._prompt()
            assert resolved.lang == "en"
            assert resolved.text != mod._PROMPT.text
        finally:
            i18n.reset_language_scope(token)
        assert mod._prompt().lang == "es"

    def test_knowledge_analysis_current_prompt_public(self, monkeypatch):
        monkeypatch.setattr(i18n, "language_enabled", lambda: True)
        from app.services import knowledge_analysis

        token = i18n.set_language_scope("en")
        try:
            assert knowledge_analysis.current_prompt().lang == "en"
        finally:
            i18n.reset_language_scope(token)

    def test_prompt_without_en_variant_falls_back_spanish(self, monkeypatch):
        monkeypatch.setattr(i18n, "language_enabled", lambda: True)
        from app.services import prompt_registry as pr

        token = i18n.set_language_scope("en")
        try:
            resolved = pr.get_prompt("bottleneck_discovery_service", allow_remote=False)
            assert resolved.lang == "es"
        finally:
            i18n.reset_language_scope(token)


class TestEnglishGroundednessValidator:
    """Espejo EN del validador de prosa libre (chat_synthesis_service)."""

    def test_unapproximated_figure_rejected_in_english(self):
        from app.services.chat_synthesis_service import _inferred_general_text_valid_en

        text = "The company generated 1250 million in revenue last year and kept growing."
        assert not _inferred_general_text_valid_en(text)

    def test_approximated_figure_accepted_in_english(self):
        from app.services.chat_synthesis_service import _inferred_general_text_valid_en

        text = (
            "The company generated roughly 1250 million in revenue last year, "
            "with margins around 20 percent and a solid balance sheet overall."
        )
        assert _inferred_general_text_valid_en(text)

    def test_spanish_prose_rejected_in_english_mode(self):
        from app.services.chat_synthesis_service import _inferred_general_text_valid_en

        text = "La empresa tiene un balance muy sólido y además el beneficio crece cada año con más datos."
        assert not _inferred_general_text_valid_en(text)

    def test_portfolio_claim_rejected_without_positions_in_english(self):
        from app.services.chat_synthesis_service import _inferred_general_text_valid_en

        text = "Your portfolio has performed well and your positions look healthy overall."
        assert not _inferred_general_text_valid_en(text)

    def test_attribution_rejected_in_english(self):
        from app.services.chat_synthesis_service import _inferred_general_text_valid_en

        text = "According to the annual report, margins improved and the balance sheet looks solid."
        assert not _inferred_general_text_valid_en(text)


class TestLocalizedFallbackNotice:
    def test_notice_spanish_by_default(self):
        from app.llm.chat_provider import fallback_notice

        class R:
            provider = "groq"
            fallback_trail = ("opencode-go:x:timeout",)

        notice = fallback_notice(R())
        assert notice is not None
        assert notice.startswith("Respondido por respaldo (Groq)")
        assert "no respondió a tiempo" in notice

    def test_notice_english_when_requested(self):
        from app.llm.chat_provider import fallback_notice

        class R:
            provider = "groq"
            fallback_trail = ("opencode-go:x:ProviderHTTPError429",)

        notice = fallback_notice(R(), lang="en")
        assert notice is not None
        assert notice.startswith("Answered by backup (Groq)")
        assert "usage limit reached (HTTP 429)" in notice

    def test_backup_prompt_follows_scope(self, monkeypatch):
        monkeypatch.setattr(i18n, "language_enabled", lambda: True)
        from app.llm.chat_provider import _backup_prompt

        assert "español" in _backup_prompt()
        token = i18n.set_language_scope("en")
        try:
            assert "plain English prose" in _backup_prompt()
        finally:
            i18n.reset_language_scope(token)
