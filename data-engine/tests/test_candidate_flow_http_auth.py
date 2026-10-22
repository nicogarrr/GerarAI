"""Regresion HTTP (app real, firmas reales): rutas de extraccion/revision/checks exigen identidad
firmada y respetan el tenant. Texto SINTETICO. Sin red: las descargas fallarian el test si se llamaran."""
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core import replay as replay_module
from app.core.auth import body_digest, sign_research_identity
from app.core.database import SessionLocal, init_db
from app.models import Company

SECRET = "research-security-test-secret-at-least-32-chars"
SYN = "Jane Roe \nChief Executive Officer, Acme Corp. \nWe will open 12 sites in 2031. \n"
BASE = "/api/companies/MSFT/management-credibility"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(auth_module, "get_settings", lambda: SimpleNamespace(
        app_env="test", is_production=False, research_auth_required=True, research_auth_secret=SECRET,
        research_auth_max_age_seconds=300, research_auth_strict_binding=False, redis_url="redis://127.0.0.1:1/0"))

    def _no_network(*a, **k):
        raise AssertionError("descarga invocada sin autorizacion")

    monkeypatch.setattr("app.services.transcript_source_service.fetch_transcript_text", _no_network)
    monkeypatch.setattr("app.services.commitment_primary_pipeline.fetch_registered_document_isolated", _no_network)
    replay_module.reset_local_nonces()
    init_db()
    db = SessionLocal()
    if not db.scalar(select(Company).where(Company.ticker == "MSFT")):
        db.add(Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD", sector="T",
                       industry="S", company_type="tech", valuation_model="standard_dcf",
                       special_sources=[], special_risks=[], factor_tags=[]))
        db.commit()
    db.close()


def _h(tenant, user, method, path, body=b""):
    ts, nonce, bh = str(int(time.time())), uuid4().hex, body_digest(body)
    return {"X-CavaAI-Tenant": tenant, "X-CavaAI-User": user, "X-CavaAI-Timestamp": ts, "X-CavaAI-Nonce": nonce,
            "X-CavaAI-Method": method, "X-CavaAI-Path": path, "X-CavaAI-Body-Hash": bh,
            "X-CavaAI-Signature": sign_research_identity(SECRET, tenant_id=tenant, user_id=user, timestamp=ts,
                                                         nonce=nonce, method=method, path=path, body_hash=bh),
            "Content-Type": "application/json"}


def _post(c, path, payload, tenant, user):
    body = json.dumps(payload).encode()
    return c.post(path, content=body, headers=_h(tenant, user, "POST", path, body))


def test_unsigned_requests_are_rejected_before_any_fetch_or_write():
    c = TestClient(main.app)
    calls = [
        ("post", f"{BASE}/extract-candidates-from-url", {"call_date": "2026-08-05", "source_url": "https://ir.example.com/t.pdf"}),
        ("post", f"{BASE}/extract-candidates-from-registry", {"source_url": "https://ir.example.com/t.pdf"}),
        ("post", f"{BASE}/extract-candidates", {"transcript_text": SYN, "call_date": "2026-08-05", "source_url": "https://x.invalid/a"}),
        ("post", f"{BASE}/promises/1/review", {"fulfillment_criteria": "criterio de prueba 123", "confirmed_source_checked": True}),
        ("post", f"{BASE}/promises/1/checks", {"outcome": "unknown", "checked_on": "2026-10-22", "summary": "x"}),
        ("get", f"{BASE}/promises/1/checks", None),
        ("get", f"{BASE}/promises/1/notes", None),
        ("get", BASE, None),
    ]
    for method, path, payload in calls:
        r = getattr(c, method)(path, **({"json": payload} if payload is not None else {}))
        assert r.status_code == 401, (path, r.status_code)


def test_signed_flow_is_tenant_scoped_and_review_needs_signed_human():
    sfx = uuid4().hex[:8]
    ta, tb = f"ta-{sfx}", f"tb-{sfx}"
    c = TestClient(main.app)
    r = _post(c, f"{BASE}/extract-candidates",
              {"transcript_text": SYN, "call_date": "2026-08-05", "source_url": f"https://x.invalid/{sfx}"}, ta, "ua")
    assert r.status_code == 201, r.text
    cand = r.json()[0]
    assert cand["status"] == "candidate" and cand["fulfillment_criteria"] is None
    pid = cand["id"]
    # otro tenant no ve ni revisa ni chequea el candidato
    for path, payload in [
        (f"{BASE}/promises/{pid}/review", {"fulfillment_criteria": "criterio de prueba 123", "confirmed_source_checked": True}),
        (f"{BASE}/promises/{pid}/checks", {"outcome": "unknown", "checked_on": "2026-10-22", "summary": "x"}),
    ]:
        assert _post(c, path, payload, tb, "ub").status_code == 404
    # sin revisar no hay veredicto aunque sea el tenant dueño
    r = _post(c, f"{BASE}/promises/{pid}/checks",
              {"outcome": "met", "checked_on": "2026-10-22", "evidence_url": "https://x.invalid/e", "evidence_excerpt": "x"}, ta, "ua")
    assert r.status_code == 422
    r = _post(c, f"{BASE}/promises/{pid}/review",
              {"fulfillment_criteria": "12 sitios abiertos segun documento oficial", "confirmed_source_checked": True}, ta, "ua")
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["reviewed_by_user_id"] == "ua"
    r = _post(c, f"{BASE}/promises/{pid}/checks",
              {"outcome": "met", "checked_on": "2032-01-05", "evidence_url": "https://x.invalid/e", "evidence_excerpt": "12 abiertos"}, ta, "ua")
    assert r.status_code == 201
    # notas privadas por usuario: otro usuario del MISMO tenant no las lee
    r = _post(c, f"{BASE}/promises/{pid}/notes", {"body": "nota privada"}, ta, "ua")
    assert r.status_code == 201
    path = f"{BASE}/promises/{pid}/notes"
    other = c.get(path, headers=_h(ta, "otro-usuario", "GET", path))
    mine = c.get(path, headers=_h(ta, "ua", "GET", path))
    assert other.status_code == 200 and other.json() == [] and len(mine.json()) == 1
