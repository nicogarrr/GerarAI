"""POST /api/portfolio/snapshots/capture con response_model.

Forma medida contra la ruta (dict literal de 7 claves, todas siempre
presentes): subconjunto del payload del historial. En la primera foto de
la serie daily_return/cumulative_twr salen null (sin foto previa no hay
retorno que enlazar, medido en PortfolioSnapshotService.capture).
Servicio real, sin mock.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.schemas.api import PortfolioSnapshotCaptureOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-snapshot-capture-test-secret"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-snapshot-capture-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio snapshot capture test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-snapshot-capture-user"


def test_capture_first_snapshot_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/snapshots/capture")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioSnapshotCaptureOut.model_validate(payload)
    # Las 7 claves del dict literal de la ruta, ni una mas ni una menos.
    assert set(payload) == {
        "id",
        "snapshot_date",
        "total_value_base",
        "pricing_coverage",
        "daily_return",
        "cumulative_twr",
        "metadata",
    }
    assert payload["snapshot_date"] == date.today().isoformat()
    # Primera foto de la serie: sin foto previa no hay retorno que enlazar.
    assert payload["daily_return"] is None
    assert payload["cumulative_twr"] is None
    # Cartera vacia: nada que valorar, cobertura y valor en cero.
    assert payload["total_value_base"] == 0
    assert payload["pricing_coverage"] == 0
    assert isinstance(payload["metadata"], dict)
