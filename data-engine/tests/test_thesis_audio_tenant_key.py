"""El audio de una tesis es de su tenant: la clave de caché del mp3 lo incluye.

Las tesis son TenantOwned y cada tenant numera sus versiones desde 1. La clave
del sidecar TTS era ticker + versión + estado + día del dato: dos usuarios con
la v1 publicada del mismo ticker compartían clave, así que el segundo recibía
(y oía) el mp3 generado con la tesis del primero, y su propio audio nunca se
generaba porque el sidecar ya lo daba por «ready». El único doble es httpx en
la frontera de red del sidecar.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant, ThesisVersion
from app.services import thesis_audio_service
from tests.auth_helpers import auth_settings, signed_request

SECRET = "thesis-audio-tenant-key-secret-with-32-chars"


def _setup(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:6].upper()
    ticker = f"AU{suffix}"
    tenants = {}
    db = SessionLocal()
    company = Company(ticker=ticker, name="Audio Co", exchange="NYSE", currency="USD",
                      company_type="operating", valuation_model="unassigned")
    db.add(company)
    db.flush()
    for who in ("a", "b"):
        ext = f"audio-key-{who}-{suffix}"
        tenant = Tenant(external_id=ext, name=f"Audio {who}")
        db.add(tenant)
        db.flush()
        db.add(ThesisVersion(
            tenant_id=tenant.id, company_id=company.id, version=1, status="published",
            thesis_markdown=f"tesis privada de {who}", executive_summary=f"resumen {who}",
            rating="buy",
        ))
        tenants[who] = ext
    db.commit()
    db.close()
    return TestClient(main.app), tenants, ticker


def _status_key(client, tenant_ext: str, ticker: str) -> str:
    res = signed_request(client, SECRET, tenant_ext, f"user-{tenant_ext}", "GET",
                         f"/api/thesis/{ticker}/audio/status")
    assert res.status_code == 200, res.text
    key = res.json()["key"]
    assert key
    return key


def test_misma_version_de_dos_tenants_no_comparte_clave_de_audio(monkeypatch) -> None:
    client, tenants, ticker = _setup(monkeypatch)

    class _Missing:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"state": "missing"}

    monkeypatch.setattr(thesis_audio_service.httpx, "get", lambda *a, **k: _Missing())

    key_a = _status_key(client, tenants["a"], ticker)
    key_b = _status_key(client, tenants["b"], ticker)

    assert key_a != key_b
    # Estable para el mismo tenant (la caché sigue sirviendo a su dueño).
    assert key_a == _status_key(client, tenants["a"], ticker)
    assert len(key_a) <= thesis_audio_service.KEY_MAX_LEN


def test_el_mp3_de_un_tenant_no_se_sirve_a_otro(monkeypatch) -> None:
    client, tenants, ticker = _setup(monkeypatch)
    stored: dict[str, bytes] = {}

    class _Resp:
        def __init__(self, url: str) -> None:
            self.url = url
            key = url.rsplit("/", 1)[-1]
            self.content = stored.get(key, b"")
            self.status_code = 200 if key in stored else 404

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"state": "ready" if self.status_code == 200 else "missing"}

    monkeypatch.setattr(thesis_audio_service.httpx, "get", lambda url, *a, **k: _Resp(url))

    # El sidecar tiene ya el mp3 de A (generado con la tesis de A).
    stored[_status_key(client, tenants["a"], ticker)] = b"ID3-mp3-de-A"

    own = signed_request(client, SECRET, tenants["a"], f"user-{tenants['a']}", "GET",
                         f"/api/thesis/{ticker}/audio")
    assert own.status_code == 200 and own.content == b"ID3-mp3-de-A"

    other = signed_request(client, SECRET, tenants["b"], f"user-{tenants['b']}", "GET",
                           f"/api/thesis/{ticker}/audio")
    assert other.status_code == 404, f"B recibió el audio de A: {other.status_code}"
