"""Plumbing de idioma por petición (app/core/i18n.py).

Con el flag apagado (defecto) nada puede sacar la generación del español:
ni la cabecera, ni el scope, ni db.info. Encendido, manda la cabecera
firmada X-GerarAI-Language y todo lo demás cae a "es".
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.config import get_settings
from app.core.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_HEADER,
    bind_request_language,
    current_language,
    language_from_db,
    reset_language_scope,
    resolve_language,
    set_language_scope,
)


@pytest.fixture(autouse=True)
def _reset_language(monkeypatch):
    monkeypatch.delenv("I18N_GENERATION_ENABLED", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _request_with_language(value: str | None) -> Request:
    headers = [] if value is None else [(LANGUAGE_HEADER.encode(), value.encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


class TestResolveLanguage:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, "es"),
            ("", "es"),
            ("es", "es"),
            ("ES", "es"),
            ("es-ES", "es"),
            ("en", "en"),
            ("en-US", "en"),
            ("en_US", "en"),
            ("fr", "es"),  # no soportado -> español, nunca un idioma a medias
            ("english", "es"),
            ("  en  ", "en"),
        ],
    )
    def test_resolve(self, raw, expected):
        assert resolve_language(raw) == expected


class TestFlagOff:
    def test_current_language_ignores_scope_with_flag_off(self):
        token = set_language_scope("en")
        try:
            assert current_language() == DEFAULT_LANGUAGE
        finally:
            reset_language_scope(token)

    def test_language_from_db_ignores_info_with_flag_off(self):
        class _Db:
            info = {"language": "en"}

        assert language_from_db(_Db()) == DEFAULT_LANGUAGE

    @pytest.mark.anyio
    async def test_dependency_ignores_header_with_flag_off(self):
        seen = {}
        async for _ in bind_request_language(_request_with_language("en")):
            seen["lang"] = current_language()
        assert seen["lang"] == DEFAULT_LANGUAGE


class TestFlagOn:
    @pytest.fixture(autouse=True)
    def _flag_on(self, monkeypatch):
        monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
        get_settings.cache_clear()

    def test_scope_visible_when_enabled(self):
        token = set_language_scope("en")
        try:
            assert current_language() == "en"
        finally:
            reset_language_scope(token)
        assert current_language() == "es"

    def test_language_from_db_reads_info(self):
        class _Db:
            info = {"language": "en-US"}

        assert language_from_db(_Db()) == "en"

    def test_language_from_db_defaults_es(self):
        class _Db:
            info = {}

        assert language_from_db(_Db()) == "es"

    @pytest.mark.anyio
    async def test_dependency_binds_header_language(self):
        seen = {}
        async for _ in bind_request_language(_request_with_language("en")):
            seen["lang"] = current_language()
        assert seen["lang"] == "en"
        # Al salir de la petición, el contexto vuelve al español por defecto.
        assert current_language() == "es"

    @pytest.mark.anyio
    async def test_dependency_defaults_es_without_header(self):
        seen = {}
        async for _ in bind_request_language(_request_with_language(None)):
            seen["lang"] = current_language()
        assert seen["lang"] == "es"
