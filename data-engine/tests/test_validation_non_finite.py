"""Un cuerpo JSON con NaN/Infinity en un campo inválido da 422, no 500.

Ronda 3 (Hypothesis sobre PUT /api/settings/dca): ``{"up_min_level": Infinity}``
llegaba al 422 por defecto de FastAPI, que devuelve el ``input`` rechazado; al
serializar ``inf`` con JSON estricto saltaba ValueError y la respuesta era 500.
Afecta a cualquier endpoint con cuerpo JSON.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, signed_request

SECRET = "nan-validation-secret-with-at-least-32-chars!!"


@pytest.fixture()
def call(monkeypatch):
    init_db()
    monkeypatch.setattr(auth_module, "get_settings",
                        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"))
    client = TestClient(main.app, raise_server_exceptions=False)
    suffix = uuid4().hex[:8]

    def _call(method: str, path: str, body):
        return signed_request(client, SECRET, f"t-{suffix}", f"u-{suffix}", method, path, json_body=body)

    return _call


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), [float("nan")], {"x": float("inf")}])
def test_non_finite_number_in_invalid_field_is_422(call, bad):
    response = call("PUT", "/api/settings/dca", {"up_min_level": bad, "down_max_level": 1})
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "up_min_level"]


def test_plain_validation_errors_keep_the_default_shape(call):
    response = call("PUT", "/api/settings/dca", {"up_min_level": 9, "down_max_level": 1})
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "up_min_level"] and error["input"] == 9 and "msg" in error
