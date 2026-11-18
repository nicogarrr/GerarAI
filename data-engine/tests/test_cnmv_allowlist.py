"""Allowlist de descarga de los conectores CNMV (se aplica via public_fetch)."""

from __future__ import annotations

import pytest

from app.services.connectors import cnmv_pacer


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://www.cnmv.es/Portal/Consultas/Directivos-Resultado?fechad=1", True),
        ("https://www.cnmv.es:443/x", True),
        ("http://www.cnmv.es/x", False),
        ("https://www.cnmv.es:8443/x", False),
        ("https://cnmv.es/x", False),
        ("https://www.cnmv.es.evil.example/x", False),
        ("https://evil.example/www.cnmv.es", False),
        ("https://user@www.cnmv.es@evil.example/x", False),
        ("ftp://www.cnmv.es/x", False),
    ],
)
def test_is_cnmv_url_allowlist(url, ok):
    assert cnmv_pacer.is_cnmv_url(url) is ok
