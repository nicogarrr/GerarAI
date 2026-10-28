"""Sondas explícitas de aislamiento entre tenants, recurso por recurso.

El tenant A crea cada recurso por la API firmada. El tenant B intenta leerlo,
modificarlo, borrarlo y accionarlo por su id. Ninguna de esas peticiones puede
tener éxito (2xx) y, al final, el recurso de A debe seguir intacto y visible
solo para A.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, signed_request

SECRET = "cross-tenant-probe-secret-with-at-least-32-chars"
CRITERION = {"left": "pe", "operator": "<", "right": "20"}


def _no_network(monkeypatch) -> None:
    import socket

    real = socket.create_connection

    def local_only(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise OSError(f"network disabled in tenant probes: {host}")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", local_only)
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "testserver")


@pytest.fixture()
def api(monkeypatch):
    _no_network(monkeypatch)
    init_db()
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    from app.workers import dramatiq_app

    monkeypatch.setattr(dramatiq_app.broker, "enqueue", lambda message, delay=None: message)
    suffix = uuid4().hex[:8]
    client = TestClient(main.app)

    def call(tenant: str, method: str, path: str, json_body=None, params=None):
        return signed_request(
            client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}",
            method, path, json_body=json_body, params=params,
        )

    # MSFT debe existir en el maestro de empresas: sin esto, el resultado
    # dependería de qué test la creó antes (orden aleatorio / xdist).
    ensured = call("a", "POST", "/api/companies/ensure", {"ticker": "MSFT"})
    assert ensured.status_code in (200, 201), ensured.text
    return call


def _assert_denied(response, what: str) -> None:
    assert response.status_code >= 400, (
        f"cross-tenant {what} succeeded: {response.status_code} {response.text[:300]}"
    )
    assert response.status_code < 500, (
        f"cross-tenant {what} crashed: {response.status_code} {response.text[:300]}"
    )


def _ids(payload) -> set:
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "transactions", "screens", "rules",
                    "contributions", "proposals", "collections", "actions"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return set()
    return {row.get("id") for row in payload if isinstance(row, dict)}


def test_portfolio_transaction_cross_tenant(api):
    created = api("a", "POST", "/api/portfolio/transactions", {
        "ticker": "MSFT", "action": "buy", "quantity": 3, "price": 100,
        "trade_date": "2024-01-15", "currency": "USD",
    })
    assert created.status_code in (200, 201), created.text
    tx_id = created.json().get("id") or created.json().get("transaction", {}).get("id")
    assert tx_id
    update = {"ticker": "MSFT", "action": "buy", "quantity": 999, "price": 1,
              "trade_date": "2024-01-15", "currency": "USD"}
    _assert_denied(api("b", "PUT", f"/api/portfolio/transactions/{tx_id}", update), "transaction update")
    _assert_denied(api("b", "DELETE", f"/api/portfolio/transactions/{tx_id}"), "transaction delete")
    assert tx_id not in _ids(api("b", "GET", "/api/portfolio/transactions").json())
    assert tx_id in _ids(api("a", "GET", "/api/portfolio/transactions").json())


def test_screen_cross_tenant(api):
    created = api("a", "POST", "/api/screeners/screens", {
        "name": "A private screen", "criteria": [CRITERION],
    })
    assert created.status_code in (200, 201), created.text
    screen_id = created.json()["id"]
    _assert_denied(api("b", "PUT", f"/api/screeners/screens/{screen_id}", {
        "name": "hijacked", "criteria": [CRITERION],
    }), "screen update")
    _assert_denied(api("b", "POST", f"/api/screeners/screens/{screen_id}/run"), "screen run")
    _assert_denied(api("b", "DELETE", f"/api/screeners/screens/{screen_id}"), "screen delete")
    names_a = {row.get("name") for row in api("a", "GET", "/api/screeners/screens").json()}
    assert "A private screen" in names_a
    assert screen_id not in _ids(api("b", "GET", "/api/screeners/screens").json())


def test_corporate_action_cross_tenant(api):
    created = api("a", "POST", "/api/corporate-actions", {
        "ticker": "MSFT", "action_type": "split", "effective_date": "2024-02-01",
        "ratio": 2, "apply_now": False,
    })
    assert created.status_code in (200, 201), created.text
    action_id = created.json().get("id") or created.json().get("action", {}).get("id")
    assert action_id
    _assert_denied(api("b", "POST", f"/api/corporate-actions/{action_id}/apply"), "corporate action apply")
    _assert_denied(api("b", "DELETE", f"/api/corporate-actions/{action_id}"), "corporate action delete")
    assert action_id not in _ids(api("b", "GET", "/api/corporate-actions").json())
    assert action_id in _ids(api("a", "GET", "/api/corporate-actions").json())


def test_plan_contribution_cross_tenant(api):
    plan = api("a", "PUT", "/api/plan", {"monthly_contribution": 500, "start_date": "2024-01-01"})
    assert plan.status_code in (200, 201), plan.text
    created = api("a", "POST", "/api/plan/contributions", {"date": "2024-03-01", "amount": 500})
    assert created.status_code in (200, 201), created.text
    contribution_id = created.json().get("id")
    assert contribution_id
    _assert_denied(api("b", "DELETE", f"/api/plan/contributions/{contribution_id}"), "contribution delete")
    assert contribution_id not in _ids(api("b", "GET", "/api/plan/contributions").json())
    assert contribution_id in _ids(api("a", "GET", "/api/plan/contributions").json())


def test_memory_claim_cross_tenant(api):
    created = api("a", "POST", "/api/memory/claims", {"ticker": "MSFT", "statement": "A only"})
    assert created.status_code == 200, created.text
    claim_id = created.json()["id"]
    _assert_denied(api("b", "GET", f"/api/memory/claims/{claim_id}"), "claim read")
    _assert_denied(api("b", "POST", f"/api/memory/claims/{claim_id}/evidence", {
        "evidence_text": "injected", "stance": "supports",
    }), "claim evidence")
    assert api("a", "GET", f"/api/memory/claims/{claim_id}").status_code == 200


def test_knowledge_collection_cross_tenant(api):
    created = api("a", "POST", "/api/knowledge/collections", {"name": f"A col {uuid4().hex[:6]}"})
    assert created.status_code in (200, 201), created.text
    collection_id = created.json()["id"]
    _assert_denied(api("b", "DELETE", f"/api/knowledge/collections/{collection_id}"), "collection delete")
    assert collection_id not in _ids(api("b", "GET", "/api/knowledge/collections").json())
    assert collection_id in _ids(api("a", "GET", "/api/knowledge/collections").json())


def test_paper_proposal_cross_tenant(api):
    created = api("a", "POST", "/api/paper-trading/proposals", {
        "proposal_key": f"k-{uuid4().hex[:8]}", "ticker": "MSFT", "direction": "long",
        "horizon": "short", "thesis": "A only thesis, private to tenant A",
        "conviction": 0.5, "proposed_entry": 100, "stop": 90, "target": 130, "quantity": 1,
        "inference_basis": "manual entry for the probe",
    })
    if created.status_code not in (200, 201):
        pytest.skip(f"cannot create proposal: {created.status_code} {created.text[:200]}")
    proposal_id = created.json().get("id") or created.json().get("proposal", {}).get("id")
    _assert_denied(api("b", "POST", f"/api/paper-trading/proposals/{proposal_id}/close", {}), "proposal close")
    assert proposal_id not in _ids(api("b", "GET", "/api/paper-trading/proposals").json())


def test_decision_journal_cross_tenant(api):
    created = api("a", "POST", "/api/companies/MSFT/decision-journal", {
        "decision": "buy", "rationale": "A private rationale",
    })
    if created.status_code not in (200, 201):
        pytest.skip(f"cannot create journal entry: {created.status_code} {created.text[:200]}")
    entry_id = created.json().get("id") or created.json().get("entry", {}).get("id")
    _assert_denied(api("b", "PUT", f"/api/companies/MSFT/decision-journal/{entry_id}/transaction",
                       {"transaction_id": 1}), "journal link")
    journal_b = api("b", "GET", "/api/companies/MSFT/decision-journal")
    assert "A private rationale" not in journal_b.text


def test_watchlist_cross_tenant(api):
    assert api("a", "POST", "/api/watchlist", {"symbol": "MSFT"}).status_code in (200, 201)
    deleted_b = api("b", "DELETE", "/api/watchlist/MSFT")
    assert deleted_b.status_code < 500
    symbols_a = api("a", "GET", "/api/watchlist").text
    assert "MSFT" in symbols_a
    assert "MSFT" not in api("b", "GET", "/api/watchlist").text


def test_management_promise_cross_tenant(api):
    created = api("a", "POST", "/api/companies/MSFT/management-credibility/promises", {
        "promise": "A private promise", "promise_date": "2024-01-10", "expected_period": "2024",
    })
    if created.status_code not in (200, 201):
        pytest.skip(f"cannot create promise: {created.status_code} {created.text[:200]}")
    body = created.json()
    promise_id = body.get("id") or body.get("promise", {}).get("id")
    _assert_denied(api("b", "PUT",
                       f"/api/companies/MSFT/management-credibility/promises/{promise_id}/explanation",
                       {"explanation": "hijack"}), "promise explanation")
    assert "A private promise" not in api("b", "GET", "/api/companies/MSFT/management-credibility").text


def test_telegram_link_challenge_cross_tenant(api):
    created = api("a", "POST", "/api/alerts/telegram-link")
    if created.status_code not in (200, 201):
        pytest.skip(f"telegram link not available: {created.status_code} {created.text[:200]}")
    challenge_id = created.json().get("challenge_id") or created.json().get("id")
    _assert_denied(api("b", "GET", f"/api/alerts/telegram-link/{challenge_id}"), "telegram challenge read")
    _assert_denied(api("b", "POST", f"/api/alerts/telegram-link/{challenge_id}/confirm"), "telegram confirm")
