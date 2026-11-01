"""GET /api/alerts/{alert_id}/analysis con response_model.

Forma medida contra alert_analysis_service.read_analysis: envelope fijo
{alert_id, versions}. La rama con cita valida lleva 8 claves (second_order
presente, null sin paso LLM); la rama invalida OMITE second_order (7 claves):
response_model_exclude_unset y test explicito de ausencia.
Servicio real sobre SQLite, sin mock.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import AlertAnalysis, NewsEvent, ResearchAlert, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "alerts-analysis-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"alerts-analysis-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Alerts analysis test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "alerts-analysis-user"


def _tenant_pk(tenant_ext: str) -> int:
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.close()
    return tenant.id


def _seed_alert(tenant_ext: str) -> tuple[int, int]:
    """Alerta tracked_news + evento con titular; devuelve (alert_id, event_id)."""
    db = SessionLocal()
    tenant_pk = _tenant_pk(tenant_ext)
    event = NewsEvent(
        tenant_id=tenant_pk,
        title="Titular generado",
        source="gdelt",
        url="https://example.com/noticia",
        date=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
        metadata_={"source_headline": "Acme sube un 10%"},
    )
    db.add(event)
    db.flush()
    alert = ResearchAlert(
        tenant_id=tenant_pk,
        alert_type="tracked_news",
        title="t",
        message="m",
        fingerprint=f"fp-{uuid4().hex[:8]}",
        metadata_={"news_event_id": event.id},
    )
    db.add(alert)
    db.commit()
    ids = (alert.id, event.id)
    db.close()
    return ids


def test_analysis_empty_versions(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    alert_id, _ = _seed_alert(tenant)

    res = signed_request(client, SECRET, tenant, user, "GET", f"/api/alerts/{alert_id}/analysis")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"alert_id", "versions"}
    assert payload["alert_id"] == alert_id
    assert payload["versions"] == []


def test_analysis_invalid_citation_omits_second_order(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    alert_id, event_id = _seed_alert(tenant)
    db = SessionLocal()
    db.add(AlertAnalysis(
        tenant_id=_tenant_pk(tenant), alert_id=alert_id, news_event_id=event_id,
        version="headline-baseline-v1", status="insufficient_data",
        result={"sections": [], "citations": [], "writeback": False},
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", f"/api/alerts/{alert_id}/analysis")

    assert res.status_code == 200, res.text
    version = res.json()["versions"][0]
    # Rama invalida (sin citas que validar): exactamente 7 claves,
    # second_order AUSENTE (exclude_unset), nunca null anadido.
    assert set(version) == {
        "id", "version", "status", "sections", "citations", "missing_data", "writeback",
    }
    assert version["status"] == "insufficient_data"
    assert version["writeback"] is False


def test_analysis_valid_citation_includes_second_order_null(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    alert_id, event_id = _seed_alert(tenant)
    citation = {
        "id": f"news_event:{event_id}", "kind": "news_event", "source": "gdelt",
        "url": "https://example.com/noticia",
        "as_of": "2026-10-30T12:00:00+00:00 (fecha atribuida a la fuente)",
        "excerpt": "Acme sube un 10%",
    }
    db = SessionLocal()
    db.add(AlertAnalysis(
        tenant_id=_tenant_pk(tenant), alert_id=alert_id, news_event_id=event_id,
        version="headline-baseline-v1", status="insufficient_data",
        result={
            "sections": [
                {"key": "facts", "body": "Titular atribuido.", "citation_ids": [citation["id"]]},
            ],
            "citations": [citation],
            "writeback": False,
        },
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", f"/api/alerts/{alert_id}/analysis")

    assert res.status_code == 200, res.text
    version = res.json()["versions"][0]
    # Rama valida: 8 claves, second_order presente y null (sin paso LLM).
    assert set(version) == {
        "id", "version", "status", "sections", "citations",
        "second_order", "missing_data", "writeback",
    }
    assert version["second_order"] is None
    assert set(version["sections"][0]) == {"key", "body", "citation_ids"}
    assert set(version["citations"][0]) == {"id", "kind", "source", "url", "as_of", "excerpt"}
