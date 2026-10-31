"""GET /api/investors* con response_model: el wire es el contrato exacto.

Estas rutas devolvian schema free-form. Al modelar el payload real aparecio
una deriva: holders[].filing_url llega null (gestor sin URL de filing) y el
front lo tipaba string. Los tests ejercitan la respuesta HTTP real con los
payloads de cada rama: si response_model recorta un campo o rechaza un null
legitimo, fallan.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant

from tests.auth_helpers import auth_settings, signed_request

SECRET = "investors-read-routes-test-secret-at-least-32-chars"

PROVENANCE = {
    "source": "SEC EDGAR 13F",
    "source_kind": "sec_edgar",
    "source_url": None,
    "fetched_at": "2026-10-30T04:00:00+00:00",
    "coverage": "ok",
    "note": None,
}


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"investors-read-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Investors read routes test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "investors-read-user"


def test_list_investors_wire_shape_with_nulls(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    payload = {
        "investors": [
            {
                "slug": "buffett",
                "name": "Warren Buffett",
                "firm": "Berkshire Hathaway",
                "kind": "person",
                "cik": "0001067983",
                "has_13f": True,
                "has_public_profile": False,
                "coverage": "ok",
                "verification": "verified",
                "official_name": "Berkshire Hathaway Inc",
                "report_date": "2026-06-30",
                "positions": 41,
                "value_usd_thousands": 257000000.0,
                "note": None,
            },
            {
                # Sin 13F: lo que el listado no tiene va en null; official_name
                # es "" (REVIEWED_MANAGERS.get), nunca null.
                "slug": "mark-leonard",
                "name": "Mark Leonard",
                "firm": "Constellation Software",
                "kind": "person",
                "cik": None,
                "has_13f": False,
                "has_public_profile": True,
                "coverage": None,
                "verification": None,
                "official_name": "",
                "report_date": None,
                "positions": None,
                "value_usd_thousands": None,
                "note": "Sin 13F: no declara cartera publica.",
            },
        ],
        "limitations": ["solo gestores revisados"],
        "provenance": PROVENANCE,
    }
    monkeypatch.setattr("app.api.routes.investors.list_investors", lambda db: payload)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/investors")
    assert res.status_code == 200, res.text
    body = res.json()
    sin_datos = body["investors"][1]
    assert sin_datos["cik"] is None
    assert sin_datos["positions"] is None
    assert sin_datos["value_usd_thousands"] is None
    assert sin_datos["verification"] is None
    assert sin_datos["official_name"] == ""
    assert body["provenance"]["source_kind"] == "sec_edgar"


def test_most_bought_wire_shape(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    payload = {
        "status": "ok",
        "managers_compared": 3,
        "managers_without_history": 1,
        "managers_partial": 0,
        "report_dates": ["2026-06-30"],
        "items": [
            {
                "name_of_issuer": "APPLE INC",
                "name_of_issuer_filed": "APPLE INC",
                "cusip": "037833100",
                "buyers_count": 2,
                "new_count": 1,
                "sellers_count": 0,
                "value_usd": None,  # filas sin cifra no suman: el agregado queda null
                "buyers": [
                    {"slug": "buffett", "name": "Warren Buffett", "change": "new", "report_date": "2026-06-30"},
                    {"slug": "akre", "name": "Chuck Akre", "change": "increased", "report_date": "2026-06-30"},
                ],
            }
        ],
        "limitations": ["solo gestores revisados"],
        "provenance": PROVENANCE,
    }
    monkeypatch.setattr("app.api.routes.investors.most_bought", lambda db: payload)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/investors/most-bought")
    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    assert item["value_usd"] is None
    assert item["buyers"][0]["change"] == "new"


def test_portfolio_overlap_holder_filing_url_null(monkeypatch) -> None:
    """La deriva detectada: holder.filing_url llega null y debe seguir en el wire."""
    client, tenant, user = _client(monkeypatch)
    payload = {
        "status": "ok",
        "kind": "derivado",
        "positions": [
            {
                "ticker": "AAPL",
                "name": "Apple Inc",
                "cusip": "037833100",
                "identity_source": "CUSIP derivado del ISIN registrado",
                "holders": [
                    {
                        "slug": "buffett",
                        "name": "Warren Buffett",
                        "report_date": "2026-06-30",
                        "filing_date": None,
                        "filing_url": None,
                        "coverage": "ok",
                        "verification": "verified",
                    }
                ],
                "status": "coincidencia",
            },
            {
                "ticker": "SAN.MC",
                "name": "Banco Santander",
                "cusip": None,
                "identity_source": None,
                "holders": [],
                "status": "sin_identificador",
            },
        ],
        "not_owned": [],
        "unresolved_positions": 1,
        "managers_with_data": 5,
        "managers_without_data": 2,
        "managers_partial": 1,
        "report_dates": ["2026-06-30"],
        "message": None,
        "comparison_complete": False,
        "limitations": ["Derivado por CUSIP exacto."],
    }
    monkeypatch.setattr("app.services.investor_overlap.portfolio_overlap", lambda db: payload)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/investors/portfolio-overlap")
    assert res.status_code == 200, res.text
    body = res.json()
    holder = body["positions"][0]["holders"][0]
    assert holder["filing_url"] is None
    assert holder["filing_date"] is None
    assert body["positions"][1]["cusip"] is None
    assert body["message"] is None


def test_portfolio_overlap_empty_branch_omits_optional_keys(monkeypatch) -> None:
    """La rama empty (sin cartera) no trae comparison_complete ni limitations."""
    client, tenant, user = _client(monkeypatch)
    empty = {
        "status": "sin_datos",
        "kind": "derivado",
        "positions": [],
        "not_owned": [],
        "unresolved_positions": 0,
        "managers_with_data": 0,
        "managers_without_data": 0,
        "managers_partial": 0,
        "report_dates": [],
        "message": "Cartera sin posiciones abiertas.",
    }
    monkeypatch.setattr("app.services.investor_overlap.portfolio_overlap", lambda db: empty)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/investors/portfolio-overlap")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "sin_datos"
    assert body["message"] == "Cartera sin posiciones abiertas."


def test_investor_portfolio_wire_shape_sin_datos_and_string_limitations(monkeypatch) -> None:
    """Rama sin 13F: datum N/D (todo null), movements con transaction_code null,
    limitations como texto (no lista) y sin clave coverage."""
    client, tenant, user = _client(monkeypatch)
    datum_empty = {"value": None, "label": "SIN_DATOS", "as_of": None, "source_url": None}
    payload = {
        "slug": "bezos",
        "name": "Jeff Bezos",
        "firm": "Amazon",
        "has_13f": False,
        "status": "ok",
        "labels": ["OFICIAL", "INFERIDO", "SIN_DATOS"],
        "limitations": "Sin 13F: solo posiciones documentadas en 13D/Forms 3/4.",
        "positions": [
            {
                "issuer": "AMAZON COM INC",
                "ticker": "AMZN",
                "cusip": None,
                "title_of_class": "COM",
                "shares": {"value": 900000000.0, "label": "OFICIAL", "as_of": "2025-11-01", "source_url": "https://www.sec.gov/x"},
                "ownership_pct": datum_empty,
                "value_usd": datum_empty,
                "weight_pct": datum_empty,
                "source_form": "4",
                "note": None,
            }
        ],
        "movements": [
            {
                "date": "2025-11-01",
                "filing_date": None,
                "issuer": "AMAZON COM INC",
                "ticker": "AMZN",
                "action": "venta",
                "transaction_code": None,
                "shares": {"value": -1000000.0, "label": "OFICIAL", "as_of": "2025-11-01", "source_url": "https://www.sec.gov/x"},
                "price_usd": datum_empty,
                "shares_after": datum_empty,
                "source_form": "4",
                "note": None,
            }
        ],
        "as_of": "2025-11-01",
        "source_kinds": ["4"],
        "total_value_usd": datum_empty,
        "note": None,
    }
    monkeypatch.setattr("app.services.investor_portfolio.investor_portfolio", lambda db, slug: payload)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/investors/bezos/portfolio")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["limitations"] == "Sin 13F: solo posiciones documentadas en 13D/Forms 3/4."
    pos = body["positions"][0]
    assert pos["ownership_pct"]["label"] == "SIN_DATOS"
    assert pos["ownership_pct"]["value"] is None
    mov = body["movements"][0]
    assert mov["transaction_code"] is None
    assert mov["filing_date"] is None
    assert body["total_value_usd"]["label"] == "SIN_DATOS"


def test_investor_portfolio_13f_branch_list_limitations_and_coverage(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    datum_empty = {"value": None, "label": "SIN_DATOS", "as_of": None, "source_url": None}
    payload = {
        "slug": "buffett",
        "name": "Warren Buffett",
        "firm": "Berkshire Hathaway",
        "has_13f": True,
        "status": "sin_datos",
        "labels": ["OFICIAL", "INFERIDO", "SIN_DATOS"],
        "limitations": ["solo gestores revisados"],
        "positions": [],
        "movements": [],
        "as_of": None,
        "source_kinds": [],
        "total_value_usd": datum_empty,
        "coverage": "partial",
        "note": "Sin datos: no hay 13F ingerido para este gestor.",
    }
    monkeypatch.setattr("app.services.investor_portfolio.investor_portfolio", lambda db, slug: payload)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/investors/buffett/portfolio")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["limitations"] == ["solo gestores revisados"]
    assert body["coverage"] == "partial"
    assert body["as_of"] is None
