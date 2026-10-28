"""SSRF: los parámetros URL nunca hacen que el servidor conecte a la red interna.

Un servidor canario escucha en 127.0.0.1. Se mandan sus URLs, en varias
codificaciones (decimal, hex, IPv6 mapeada, 127.1, 0.0.0.0, nip.io...), a cada
endpoint que acepta una URL y la descarga o la usa como base. El endpoint debe
rechazarla (4xx) y el canario no debe recibir ni una conexión.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, signed_request

SECRET = "ssrf-canary-secret-with-at-least-32-characters!"


class _Canary(BaseHTTPRequestHandler):
    connections: list = []

    def setup(self):
        type(self).connections.append(self.client_address)
        super().setup()

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><body>internal canary</body></html>")

    do_POST = do_GET  # noqa: N815

    def log_message(self, *args):  # noqa: ARG002
        pass


@pytest.fixture(scope="module")
def canary_port():
    server = HTTPServer(("127.0.0.1", 0), _Canary)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


@pytest.fixture()
def api(monkeypatch):
    init_db()
    monkeypatch.setenv("LLM_SETTINGS_ENCRYPTION_KEY", "explicit-encryption-key-with-32-bytes!")
    monkeypatch.setattr(
        auth_module, "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    client = TestClient(main.app, raise_server_exceptions=False)

    def call(method, path, body):
        return signed_request(client, SECRET, "ssrf-tenant", "ssrf-user", method, path, json_body=body)

    return call


VARIANTS = [
    "http://127.0.0.1:{port}/a",
    "http://localhost:{port}/b",
    "http://[::ffff:127.0.0.1]:{port}/c",
    "http://2130706433:{port}/d",
    "http://0x7f000001:{port}/e",
    "http://127.1:{port}/f",
    "http://0.0.0.0:{port}/g",
    "http://127.0.0.1.nip.io:{port}/h",
    "HTTP://127.0.0.1:{port}/i",
    "https://127.0.0.1:{port}/j",
    "https://localhost:{port}/k",
    "https://[::1]:{port}/l",
    "http://169.254.169.254/latest/meta-data/",
]

ENDPOINTS = [
    ("POST", "/api/sources/documents/ingest-url",
     lambda url: {"url": url, "ticker": "MSFT", "title": "Informe anual 2024"}),
    ("POST", "/api/settings/llm/test",
     lambda url: {"provider": "custom", "base_url": url, "api_key": "sk-test-123456", "model": "m"}),
    ("PUT", "/api/settings/llm",
     lambda url: {"provider": "custom", "base_url": url, "api_key": "sk-test-123456", "model": "m"}),
]


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS, ids=[e[1] for e in ENDPOINTS])
def test_internal_urls_are_rejected_without_connecting(api, canary_port, variant, method, path, body):
    url = variant.format(port=canary_port)
    before = len(_Canary.connections)
    response = api(method, path, body(url))
    assert 400 <= response.status_code < 500, (url, response.status_code, response.text[:200])
    assert len(_Canary.connections) == before, f"{path} connected to {url}"
