"""Rutas de autoservicio de privacidad: mapeo de fallos del servicio a HTTP.

El servicio se sustituye por un doble: lo que se prueba aqui es el contrato
de la ruta (codigos y que los internos NO se filtran al cliente), no el
borrado en si. Un 502 del export o del delete nunca lleva el texto de la
excepcion interna; la confirmacion invalida es 400 con su motivo; un borrado
con residuo externo es 502 reintentable.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import privacy as privacy_routes
from app.api.routes.privacy import DeleteAccountRequest
from app.services.privacy_service import (
    PrivacyConfirmationError,
    PrivacyPartialFailure,
)


@pytest.fixture
def service(monkeypatch):
    doble = Mock()
    monkeypatch.setattr(privacy_routes, "PrivacyService", lambda: doble)
    return doble


class TestExport:
    def test_export_ok_devuelve_el_payload(self, service):
        service.export_account.return_value = {
            "schema_version": 1,
            "generated_at": "2026-11-08T00:00:00+00:00",
            "profile": {},
            "settings": {},
        }
        assert privacy_routes.export_account(db=object())["schema_version"] == 1

    def test_export_fallo_interno_es_502_sin_filtrar(self, service):
        service.export_account.side_effect = RuntimeError("cadena de conexion secreta")
        with pytest.raises(HTTPException) as exc:
            privacy_routes.export_account(db=object())
        assert exc.value.status_code == 502
        assert "cadena de conexion secreta" not in str(exc.value.detail)


class TestDelete:
    def test_borrado_ok(self, service):
        service.delete_account.return_value = {"status": "deleted", "already_deleted": False}
        payload = DeleteAccountRequest(confirmation="ELIMINAR MI CUENTA")
        assert privacy_routes.delete_account(payload=payload, db=object())["status"] == "deleted"

    def test_confirmacion_invalida_es_400_con_motivo(self, service):
        service.delete_account.side_effect = PrivacyConfirmationError("frase incorrecta")
        payload = DeleteAccountRequest(confirmation="no")
        with pytest.raises(HTTPException) as exc:
            privacy_routes.delete_account(payload=payload, db=object())
        assert exc.value.status_code == 400
        assert exc.value.detail == "frase incorrecta"

    def test_residuo_externo_es_502_reintentable_sin_filtrar(self, service):
        service.delete_account.side_effect = PrivacyPartialFailure(["storage: timeout"])
        payload = DeleteAccountRequest(confirmation="ELIMINAR MI CUENTA")
        with pytest.raises(HTTPException) as exc:
            privacy_routes.delete_account(payload=payload, db=object())
        assert exc.value.status_code == 502
        assert "storage: timeout" not in str(exc.value.detail)

    def test_value_error_es_400_sin_filtrar(self, service):
        service.delete_account.side_effect = ValueError("tenant roto")
        payload = DeleteAccountRequest(confirmation="ELIMINAR MI CUENTA")
        with pytest.raises(HTTPException) as exc:
            privacy_routes.delete_account(payload=payload, db=object())
        assert exc.value.status_code == 400
        assert "tenant roto" not in str(exc.value.detail)

    def test_fallo_interno_es_502_sin_filtrar(self, service):
        service.delete_account.side_effect = RuntimeError("trace interno")
        payload = DeleteAccountRequest(confirmation="ELIMINAR MI CUENTA")
        with pytest.raises(HTTPException) as exc:
            privacy_routes.delete_account(payload=payload, db=object())
        assert exc.value.status_code == 502
        assert "trace interno" not in str(exc.value.detail)
