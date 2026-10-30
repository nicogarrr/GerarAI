"""Errores de API visibles en la UI, bilingues (i18n B4).

El espanol debe ser byte a byte el literal que habia antes en cada ruta; el
ingles solo aparece con el flag activo y scope "en".
"""
from __future__ import annotations

from app.core import i18n
from app.core.ui_errors import _MESSAGES, ui_error


class TestUiError:
    def test_spanish_default_byte_identical(self):
        exc = ui_error(404, "ticker_not_in_watchlist")
        assert exc.status_code == 404
        assert exc.detail == "Ese ticker no está en tu watchlist"

    def test_flag_off_ignores_english_scope(self, monkeypatch):
        monkeypatch.setattr(i18n, "language_enabled", lambda: False)
        token = i18n.set_language_scope("en")
        try:
            assert ui_error(404, "ticker_not_in_watchlist").detail == "Ese ticker no está en tu watchlist"
        finally:
            i18n.reset_language_scope(token)

    def test_english_with_flag_and_scope(self, monkeypatch):
        monkeypatch.setattr(i18n, "language_enabled", lambda: True)
        token = i18n.set_language_scope("en")
        try:
            exc = ui_error(404, "ticker_not_in_watchlist")
            assert exc.detail == "That ticker is not in your watchlist"
        finally:
            i18n.reset_language_scope(token)
        assert ui_error(404, "ticker_not_in_watchlist").detail == "Ese ticker no está en tu watchlist"

    def test_format_vars(self, monkeypatch):
        monkeypatch.setattr(i18n, "language_enabled", lambda: True)
        token = i18n.set_language_scope("en")
        try:
            exc = ui_error(422, "symbol_not_recognized", ticker="XYZ")
            assert exc.detail == "Symbol not recognized: XYZ. Check that it is listed on an exchange."
        finally:
            i18n.reset_language_scope(token)
        exc = ui_error(422, "symbol_not_recognized", ticker="XYZ")
        assert exc.detail == "Símbolo no reconocido: XYZ. Comprueba que exista en bolsa."

    def test_every_key_has_both_languages(self):
        for key, messages in _MESSAGES.items():
            assert set(messages) == {"es", "en"}, key
            assert messages["es"].strip() and messages["en"].strip(), key
