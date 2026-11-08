"""Rutas de telegram-link e importacion de cartera por imagen: contrato de fallos.

Los servicios se sustituyen por dobles y las funciones de la ruta se llaman
directamente: se prueba solo el mapeo funcion -> resultado (isoformat en el
challenge, 403 del relay fuera del chat privado, preview sin sesion = 403,
base64 corrupto = 422, OCR caido = 503, ValueError del review/confirm = 422
con rollback). No se prueba la capa HTTP, la auth real, la firma HMAC ni la
busqueda SQL de instrumentos (esa va por integracion).
"""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.routes import portfolio_images as images_routes
from app.api.routes import telegram_link as telegram_routes


def run_async(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapped


class TestTelegramLink:
    @pytest.fixture
    def service(self, monkeypatch):
        doble = Mock()
        monkeypatch.setattr(telegram_routes, "service", doble)
        return doble

    def test_start_serializa_la_caducidad(self, service):
        service.start_link.return_value = {
            "challenge_id": 5,
            "command": "/vincular ABC",
            "expires_at": datetime(2026, 11, 8, 22, 0, tzinfo=UTC),
        }
        result = telegram_routes.start(db=object())
        assert result["expires_at"] == "2026-11-08T22:00:00+00:00"

    def test_status_devuelve_chat_y_confirmacion(self, service):
        service.inspect_link.return_value = SimpleNamespace(
            candidate_chat_id="123", confirmed=True
        )
        assert telegram_routes.status(challenge_id=5, db=object()) == {
            "chat_id": "123",
            "confirmed": True,
        }

    def test_confirm_delega_en_el_servicio(self, service):
        service.confirm_link.return_value = {"chat_id": "123", "verified": True}
        payload = telegram_routes.LinkConfirmIn(chat_id="123")
        assert telegram_routes.confirm(challenge_id=5, payload=payload, db=object())["verified"] is True

    @run_async
    async def test_relay_fuera_del_chat_privado_es_403(self, service, monkeypatch):
        monkeypatch.setattr(
            telegram_routes, "get_settings", lambda: SimpleNamespace(telegram_link_secret="s")
        )
        request = SimpleNamespace(body=AsyncMock(return_value=b"{}"))
        payload = telegram_routes.BotLinkIn(
            token="t" * 40, chat_id="123", telegram_user_id="123", chat_type="channel"
        )
        with pytest.raises(HTTPException) as exc:
            await telegram_routes.relay(request=request, payload=payload)
        assert exc.value.status_code == 403
        service.receive_bot_link.assert_not_called()

    @run_async
    async def test_relay_chat_ajeno_es_403(self, service, monkeypatch):
        monkeypatch.setattr(
            telegram_routes, "get_settings", lambda: SimpleNamespace(telegram_link_secret="s")
        )
        request = SimpleNamespace(body=AsyncMock(return_value=b"{}"))
        payload = telegram_routes.BotLinkIn(
            token="t" * 40, chat_id="123", telegram_user_id="456", chat_type="private"
        )
        with pytest.raises(HTTPException) as exc:
            await telegram_routes.relay(request=request, payload=payload)
        assert exc.value.status_code == 403
        service.receive_bot_link.assert_not_called()


    @run_async
    async def test_relay_ok_verifica_firma_y_recibe(self, service, monkeypatch):
        monkeypatch.setattr(
            telegram_routes, "get_settings", lambda: SimpleNamespace(telegram_link_secret="s")
        )
        sesion = Mock()

        class _SessionCtx:
            def __enter__(self):
                return sesion

            def __exit__(self, *args):
                return None

        monkeypatch.setattr(telegram_routes, "SessionLocal", _SessionCtx)
        request = SimpleNamespace(body=AsyncMock(return_value=b"{}"))
        payload = telegram_routes.BotLinkIn(
            token="t" * 40, chat_id="123", telegram_user_id="123", chat_type="private"
        )
        result = await telegram_routes.relay(
            request=request, payload=payload,
            x_asistenta_timestamp="1", x_asistenta_signature="sig",
        )
        assert result == {"status": "received"}
        service.verify_relay.assert_called_once_with("s", b"{}", "1", "sig")
        service.receive_bot_link.assert_called_once_with(sesion, payload.token, "123")


class TestPortfolioImages:
    def _db(self, tenant_id=1):
        return Mock(info={"tenant_id": tenant_id})

    def _input(self, data: bytes) -> images_routes.ImageInput:
        return images_routes.ImageInput(image_base64=base64.b64encode(data).decode())

    def test_preview_sin_sesion_es_403(self, monkeypatch):
        extract = Mock()
        monkeypatch.setattr(images_routes, "extract_image", extract)
        with pytest.raises(HTTPException) as exc:
            images_routes.preview(payload=self._input(b"png"), db=self._db(None))
        assert exc.value.status_code == 403
        extract.assert_not_called()

    def test_preview_base64_corrupto_es_422(self, monkeypatch):
        monkeypatch.setattr(
            images_routes, "extract_image", Mock(side_effect=ValueError("no es imagen"))
        )
        with pytest.raises(HTTPException) as exc:
            images_routes.preview(payload=self._input(b"no-image"), db=self._db())
        assert exc.value.status_code == 422

    def test_preview_ocr_caido_es_503(self, monkeypatch):
        monkeypatch.setattr(
            images_routes, "extract_image", Mock(side_effect=RuntimeError("OCR no disponible"))
        )
        with pytest.raises(HTTPException) as exc:
            images_routes.preview(payload=self._input(b"png"), db=self._db())
        assert exc.value.status_code == 503

    def test_preview_ok_devuelve_la_extraccion(self, monkeypatch):
        monkeypatch.setattr(
            images_routes, "extract_image", Mock(return_value={"rows": []})
        )
        assert images_routes.preview(payload=self._input(b"png"), db=self._db()) == {"rows": []}

    @run_async
    async def test_review_value_error_es_422_con_rollback(self, monkeypatch):
        monkeypatch.setattr(
            images_routes, "review_rows", AsyncMock(side_effect=ValueError("hash desconocido"))
        )
        db = self._db()
        payload = Mock(image_hash="h" * 64, rows=[])
        with pytest.raises(HTTPException) as exc:
            await images_routes.review(payload=payload, db=db)
        assert exc.value.status_code == 422
        db.rollback.assert_called_once()

    def test_confirm_value_error_es_422_con_rollback(self, monkeypatch):
        monkeypatch.setattr(
            images_routes, "confirm_review", Mock(side_effect=ValueError("review cerrada"))
        )
        db = self._db()
        payload = Mock(review_id=3, confirmed=True)
        with pytest.raises(HTTPException) as exc:
            images_routes.confirm(payload=payload, db=db)
        assert exc.value.status_code == 422
        db.rollback.assert_called_once()

    def test_confirm_ok_devuelve_el_resultado(self, monkeypatch):
        monkeypatch.setattr(
            images_routes, "confirm_review", Mock(return_value={"status": "imported"})
        )
        payload = Mock(review_id=3, confirmed=True)
        assert images_routes.confirm(payload=payload, db=self._db()) == {"status": "imported"}
