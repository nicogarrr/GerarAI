"""PATCH /api/reviews/{id}: cambiar solo el estado borraba las notas de
resolucion (el campo omitido se escribia como null). Solo se cambian si el
cliente las manda; ``null`` explicito sigue borrandolas."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.models.entities import ResearchReview
from tests.auth_helpers import auth_settings, signed_request

SECRET = "review-patch-keeps-notes-test-secret-32c"


def test_cambiar_estado_no_borra_las_notas(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    tenant_ext = f"review-notes-{uuid4().hex[:8]}"
    with SessionLocal() as db:
        tenant = Tenant(external_id=tenant_ext, name="Review notes")
        db.add(tenant)
        db.commit()
        db.info["tenant_id"] = tenant.id
        review = ResearchReview(tenant_id=tenant.id, review_type="thesis", title="Revisar margen",
                                status="open")
        db.add(review)
        db.commit()
        review_id = review.id
    client = TestClient(main.app)

    def patch(body):
        return signed_request(client, SECRET, tenant_ext, "review-user", "PATCH",
                              f"/api/reviews/{review_id}", json_body=body)

    first = patch({"status": "resolved", "resolution_notes": "El margen se recupera en Q3."})
    assert first.status_code == 200, first.text
    reopened = patch({"status": "in_progress"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["resolution_notes"] == "El margen se recupera en Q3."
    assert reopened.json()["resolved_at"] is None
    cleared = patch({"status": "open", "resolution_notes": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["resolution_notes"] is None
