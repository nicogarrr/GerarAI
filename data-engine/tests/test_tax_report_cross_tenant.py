"""IDOR: el informe fiscal (compute_report) de un tenant no se ve desde otro.

`TaxReportService.compute_report` lee `select(Transaction, Company)` sin
filtro explícito de tenant. El aislamiento lo pone el listener
`do_orm_execute` de app/core/database.py (with_loader_criteria sobre
TenantOwnedMixin) con el tenant que `get_db` fija desde la petición firmada.
Estas sondas comprueban, por cada ruta que llega a compute_report (informe,
preview, regenerate, export JSON/CSV, Modelo 720, holdings), que B no ve nada
de A y que el informe persistido de A no se pisa ni se lee desde B.
"""

from __future__ import annotations

import json

from tests.test_cross_tenant_probes import api  # noqa: F401  (fixture)

YEAR = 2024
MARKER_QTY = 37


def _seed_a(api):  # noqa: F811
    for body in (
        {"ticker": "MSFT", "action": "buy", "quantity": MARKER_QTY, "price": 100,
         "trade_date": f"{YEAR}-02-01", "currency": "USD"},
        {"ticker": "MSFT", "action": "sell", "quantity": MARKER_QTY, "price": 333,
         "trade_date": f"{YEAR}-06-03", "currency": "USD"},
    ):
        r = api("a", "POST", "/api/portfolio/transactions", body)
        assert r.status_code in (200, 201), r.text


def _realized(payload: dict) -> list:
    rows = payload.get("realized") or []
    if isinstance(payload.get("report"), dict):
        rows = rows or payload["report"].get("realized") or []
    return rows


def _mentions_a(text: str) -> bool:
    return "MSFT" in text or str(MARKER_QTY * 333) in text or "12321" in text


def test_tax_report_routes_do_not_leak_across_tenants(api):  # noqa: F811
    _seed_a(api)
    regen_a = api("a", "POST", f"/api/taxes/report/{YEAR}/regenerate")
    assert regen_a.status_code == 200, regen_a.text
    assert "MSFT" in regen_a.text, "control: A must see its own sale"

    probes = [
        ("GET", f"/api/taxes/report/{YEAR}", None),
        ("POST", f"/api/taxes/report/{YEAR}/preview", {}),
        ("GET", "/api/taxes/holdings", None),
        ("GET", f"/api/export/{YEAR}", {"format": "json"}),
        ("GET", f"/api/export/{YEAR}", {"format": "csv"}),
        ("GET", f"/api/taxes/modelo720/{YEAR}/thresholds", None),
        ("GET", f"/api/taxes/modelo720/{YEAR}/file", None),
        ("POST", f"/api/taxes/report/{YEAR}/regenerate", None),
    ]
    for method, path, extra in probes:
        if method == "GET":
            r = api("b", method, path, params=extra)
        else:
            r = api("b", method, path, json_body=extra)
        assert r.status_code < 500, f"{method} {path}: {r.status_code} {r.text[:300]}"
        if r.status_code >= 400:
            continue
        assert not _mentions_a(r.text), f"B sees A's tax data via {method} {path}: {r.text[:400]}"
        if r.headers.get("content-type", "").startswith("application/json"):
            payload = r.json()
            if isinstance(payload, dict):
                assert not _realized(payload), f"{path}: {json.dumps(payload)[:300]}"

    # B's regenerate must not have overwritten A's persisted snapshot.
    again_a = api("a", "GET", f"/api/taxes/report/{YEAR}")
    assert again_a.status_code == 200
    assert "MSFT" in again_a.text
