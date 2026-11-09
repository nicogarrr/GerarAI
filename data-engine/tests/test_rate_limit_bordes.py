"""Bordes de ``app.core.rate_limit``: helpers puros.

Lo que cada test demuestra:
- ``is_exempt_path``: el conjunto exacto y el prefijo ``/api/health`` (74, 76).
- ``_tier_for``: tier expensive por sufijo exacto de ruta (101).
- ``_rate_limit_identity``: sin principal la identidad es ``anonymous@ip`` (130).
- ``public_client_ip`` y ``_trusted_proxy_peer``: X-Forwarded-For solo se
  mira si el peer esta en la allowlist; la IP usada es la ULTIMA entrada;
  entradas invalidas de la allowlist se saltan (296-301, 377-389).
- ``_carries_valid_signature``: extraccion de cabeceras x-cavaai-*, guardas
  de campos, formato de firma, ventana temporal, vinculacion opcional
  nonce/method/path/body-hash y verificacion HMAC (425-470).
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from starlette.requests import Request

from app.core.auth import sign_research_identity
from app.core.rate_limit import (
    _carries_valid_signature,
    _rate_limit_identity,
    _tier_for,
    _trusted_proxy_peer,
    is_exempt_path,
    public_client_ip,
)

SECRET = "0123456789abcdef0123456789abcdef"


def _request(client=("10.0.0.5", 12345), headers=(), method="GET", path="/api/x"):
    scope = {
        "type": "http",
        "client": client,
        "headers": list(headers),
        "method": method,
        "path": path,
    }
    return Request(scope)


def _settings(**kw):
    base = dict(research_auth_secret=SECRET, research_auth_max_age_seconds=300, forwarded_allow_ips="")
    base.update(kw)
    return SimpleNamespace(**base)


def _signed_headers(ts, **bound):
    sig = sign_research_identity(SECRET, tenant_id="t1", user_id="u1", timestamp=ts, **bound)
    headers = [
        (b"x-cavaai-user", b"u1"),
        (b"x-cavaai-tenant", b"t1"),
        (b"x-cavaai-timestamp", ts.encode()),
        (b"x-cavaai-signature", sig.encode()),
    ]
    for name, value in bound.items():
        if value is not None:
            headers.append((f"x-cavaai-{name.replace('_', '-')}".encode(), str(value).encode()))
    return headers


def test_is_exempt_path_conjunto_exacto_y_prefijo_api_health():
    assert is_exempt_path("/health") is True
    assert is_exempt_path("/") is True
    assert is_exempt_path("/api/health") is True
    assert is_exempt_path("/api/health/live") is True
    assert is_exempt_path("/api/chat") is False


def test_tier_for_sufijo_exacto_es_expensive():
    assert _tier_for("/api/portfolio/second-order") == "expensive"
    assert _tier_for("/api/discoveries/run") == "expensive"
    assert _tier_for("/api/discoveries/runner") == "standard"


def test_identity_sin_principal_es_anonymous():
    req = _request(client=("1.2.3.4", 999))
    assert _rate_limit_identity(None, req) == "anonymous@1.2.3.4"


def test_trusted_proxy_peer_allowlist_cidr_exacta_e_invalida():
    s = _settings(forwarded_allow_ips="10.0.0.0/8, 192.168.1.1, basura,,")
    assert _trusted_proxy_peer("10.1.2.3", s) is True  # CIDR
    assert _trusted_proxy_peer("192.168.1.1", s) is True  # IP exacta
    assert _trusted_proxy_peer("192.168.1.2", s) is False  # fuera
    assert _trusted_proxy_peer("not-an-ip", s) is False  # peer invalido


def test_public_client_ip_solo_confia_en_proxy_de_la_allowlist():
    s = _settings(forwarded_allow_ips="10.0.0.0/8")
    xff = [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")]
    # Peer en la allowlist: la ultima entrada de XFF (la que anadio el proxy).
    assert public_client_ip(_request(headers=xff), s) == "5.6.7.8"
    # XFF invalida: se queda con el peer.
    assert public_client_ip(_request(headers=[(b"x-forwarded-for", b"basura")]), s) == "10.0.0.5"
    # Peer fuera de la allowlist: la cabecera la controla el cliente, no se mira.
    assert public_client_ip(_request(client=("8.8.8.8", 1), headers=xff), s) == "8.8.8.8"


def test_signature_valida_sin_vinculacion():
    ts = str(int(time.time()))
    # Una cabecera ajena (no x-cavaai-*) se ignora y no rompe la firma.
    headers = _signed_headers(ts) + [(b"content-type", b"application/json")]
    req = _request(headers=headers)
    assert _carries_valid_signature(req.scope, _settings()) is True


def test_signature_valida_con_vinculacion_completa():
    ts = str(int(time.time()))
    bound = dict(nonce="n1", method="GET", path="/api/x", body_hash="bh")
    req = _request(headers=_signed_headers(ts, **bound), method="GET", path="/api/x")
    assert _carries_valid_signature(req.scope, _settings()) is True


def test_signature_guardas():
    s = _settings()
    ts = str(int(time.time()))
    # Sin secreto configurado.
    assert _carries_valid_signature({}, SimpleNamespace()) is False
    # Falta un campo obligatorio.
    partial = [h for h in _signed_headers(ts) if h[0] != b"x-cavaai-user"]
    assert _carries_valid_signature(_request(headers=partial).scope, s) is False
    # Firma con longitud o alfabeto invalidos.
    bad_len = [
        (b"x-cavaai-user", b"u1"),
        (b"x-cavaai-tenant", b"t1"),
        (b"x-cavaai-timestamp", ts.encode()),
        (b"x-cavaai-signature", b"ab"),
    ]
    assert _carries_valid_signature(_request(headers=bad_len).scope, s) is False
    bad_hex = [
        (b"x-cavaai-user", b"u1"),
        (b"x-cavaai-tenant", b"t1"),
        (b"x-cavaai-timestamp", ts.encode()),
        (b"x-cavaai-signature", b"z" * 64),
    ]
    assert _carries_valid_signature(_request(headers=bad_hex).scope, s) is False
    # Timestamp no entero.
    bad_ts = [
        (b"x-cavaai-user", b"u1"),
        (b"x-cavaai-tenant", b"t1"),
        (b"x-cavaai-timestamp", b"abc"),
        (b"x-cavaai-signature", b"a" * 64),
    ]
    assert _carries_valid_signature(_request(headers=bad_ts).scope, s) is False


def test_signature_ventana_temporal():
    s = _settings()
    future = str(int(time.time()) + 100)
    assert _carries_valid_signature(_request(headers=_signed_headers(future)).scope, s) is False
    old = str(int(time.time()) - 10000)
    assert _carries_valid_signature(_request(headers=_signed_headers(old)).scope, s) is False


def test_signature_vinculacion_parcial_o_inconsistente():
    s = _settings()
    ts = str(int(time.time()))
    # Vinculacion parcial (solo nonce): no vale.
    headers = _signed_headers(ts) + [(b"x-cavaai-nonce", b"n1")]
    assert _carries_valid_signature(_request(headers=headers).scope, s) is False
    # Metodo o path del scope distintos de los firmados.
    bound = dict(nonce="n1", method="GET", path="/api/x", body_hash="bh")
    wrong_method = _request(headers=_signed_headers(ts, **bound), method="POST", path="/api/x")
    assert _carries_valid_signature(wrong_method.scope, s) is False
    wrong_path = _request(headers=_signed_headers(ts, **bound), method="GET", path="/api/otra")
    assert _carries_valid_signature(wrong_path.scope, s) is False
    # Firma de otro mensaje: HMAC no coincide.
    sig_otra = sign_research_identity(SECRET, tenant_id="t1", user_id="otro", timestamp=ts)
    headers = [
        (b"x-cavaai-user", b"u1"),
        (b"x-cavaai-tenant", b"t1"),
        (b"x-cavaai-timestamp", ts.encode()),
        (b"x-cavaai-signature", sig_otra.encode()),
    ]
    assert _carries_valid_signature(_request(headers=headers).scope, s) is False
