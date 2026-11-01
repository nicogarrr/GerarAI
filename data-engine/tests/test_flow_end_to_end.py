"""FLUJO COMPLETO end-to-end (TestClient + mocks, sin red, sin LLM real).

Cadena verificada:
  seed -> GET /api/screeners/real (vendor mockeado) -> POST /api/watchlist
  -> POST /api/thesis/generate (determinista, sin LLM) -> GET thesis latest
  -> POST /api/alerts (+ GET rules) -> probe GET /api/insider/signals
  -> probe GET /api/calendar/earnings (+ fallback real /api/earnings)

Cada paso del chain existente debe devolver 2xx y el ticker debe fluir
de screener a alerta. Los eslabones inexistentes (insider/calendar) se
reportan como ESLABON FALTANTE en lugar de romper el chain verificado.

Run from data-engine/:
    pytest tests/test_flow_end_to_end.py -v -s
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import main
from app.api.routes import screeners as screeners_module
from app.core import auth as auth_module
from app.core.csrf import generate_csrf_token
from app.seed import seed
from tests.auth_helpers import auth_settings, bound_headers

SECRET = "flow-e2e-test-secret-at-least-32-chars"

# Vendor mockeado: lo que Finnhub devolvería, sin salir a red.
FAKE_VENDOR_ITEMS = [
    {
        "symbol": "MSFT",
        "name": "Microsoft",
        "price": 420.50,
        "change": 2.10,
        "changePercent": 0.50,
        "marketCap": 3_120_000_000_000.0,
        "volume": 18_000_000.0,
        "prevClose": 418.40,
        "sector": "Technology",
        "exchange": "NASDAQ",
        "type": "Stock",
        "pe": None,
        "pb": None,
        "roe": None,
        "beta": None,
        # Campos requeridos por ScreenerRealItemOut (response_model, #3698).
        "priceAsOf": None,
        "priceTimestampKind": "quote",
        "priceDate": None,
        "currency": "USD",
        "has_fundamentals": False,
    },
    {
        "symbol": "NVDA",
        "name": "NVIDIA",
        "price": 880.00,
        "change": -5.00,
        "changePercent": -0.56,
        "marketCap": 2_160_000_000_000.0,
        "volume": 42_000_000.0,
        "prevClose": 885.00,
        "sector": "Technology",
        "exchange": "NASDAQ",
        "type": "Stock",
        "pe": None,
        "pb": None,
        "roe": None,
        "beta": None,
        # Campos requeridos por ScreenerRealItemOut (response_model, #3698).
        "priceAsOf": None,
        "priceTimestampKind": "quote",
        "priceDate": None,
        "currency": "USD",
        "has_fundamentals": False,
    },
]


def test_flow_end_to_end(monkeypatch):
    report: list[str] = []
    missing: list[str] = []

    def ok(step: str, detail: str = "") -> None:
        report.append(f"OK   {step}" + (f" — {detail}" if detail else ""))

    # 0. Seed taxonomico (companies MSFT/NVDA, sin datos de usuario).
    seed()
    ok("seed", "company master cargado")

    # El vendor real (Finnhub via httpx + sleep) queda neutralizado: el
    # refresco devuelve el mock y el cache se fuerza a caducado.
    monkeypatch.setattr(
        screeners_module, "_refetch_real_items", lambda **kwargs: list(FAKE_VENDOR_ITEMS)
    )
    screeners_module._real_items_cache.clear()

    client = TestClient(main.app)
    client.headers["X-CSRF-Token"] = generate_csrf_token()

    # 1. Screener real (mock vendor).
    screener = client.get("/api/screeners/real", params={"limit": 5})
    assert screener.status_code == 200, f"screener: {screener.status_code} {screener.text[:300]}"
    payload = screener.json()
    assert payload["source"] == "finnhub_free"
    assert payload["count"] >= 1
    ticker = payload["screener"][0]["symbol"]
    assert ticker == "MSFT", f"el primer item debe ser MSFT, fue {ticker}"
    ok("GET /api/screeners/real", f"ticker={ticker} count={payload['count']}")

    # 2. Watchlist con el ticker del screener.
    watch = client.post(
        "/api/watchlist", json={"symbol": ticker, "company": "Microsoft"}
    )
    assert watch.status_code == 201, f"watchlist: {watch.status_code} {watch.text[:300]}"
    assert watch.json()["symbol"] == ticker
    ok("POST /api/watchlist", f"symbol={ticker}")

    # 3. Thesis generate (determinista, sin LLM real).
    thesis = client.post("/api/thesis/generate", json={"ticker": ticker})
    assert thesis.status_code == 200, f"thesis generate: {thesis.status_code} {thesis.text[:300]}"
    thesis_body = thesis.json()
    thesis_id = thesis_body["id"]
    thesis_version = thesis_body["version"]
    ok(
        "POST /api/thesis/generate",
        f"id={thesis_id} v{thesis_version} status={thesis_body['status']}",
    )

    # 4. Thesis latest encadena con lo generado.
    latest = client.get(f"/api/thesis/{ticker}/latest")
    assert latest.status_code == 200, f"thesis latest: {latest.status_code} {latest.text[:300]}"
    assert latest.json()["id"] == thesis_id
    ok("GET /api/thesis/{ticker}/latest", f"id={thesis_id}")

    # 5. Alerta sobre el mismo ticker + listado de reglas.
    alert = client.post(
        "/api/alerts",
        json={
            "ticker": ticker,
            "alert_type": "price_above",
            "operator": ">",
            "value": 100.0,
        },
    )
    assert alert.status_code == 201, f"alerts: {alert.status_code} {alert.text[:300]}"
    rule_id = alert.json()["id"]
    rules = client.get("/api/alerts/rules", params={"ticker": ticker})
    assert rules.status_code == 200, f"rules: {rules.status_code} {rules.text[:300]}"
    assert any(rule["id"] == rule_id for rule in rules.json()), "la regla creada no aparece"
    alerts_list = client.get("/api/alerts", params={"ticker": ticker})
    assert alerts_list.status_code == 200
    ok("POST /api/alerts + GET rules", f"rule_id={rule_id} ticker={ticker}")

    # 6. Insider signals (mock EDGAR). Hoy no existe como ruta.
    insider = client.get("/api/insider/signals", params={"ticker": ticker})
    if insider.status_code == 200:
        ok("GET /api/insider/signals", f"ticker={ticker}")
    else:
        missing.append(
            f"/api/insider/signals?ticker= (status={insider.status_code}): "
            "sin ruta de insider en el router — senales EDGAR solo a nivel servicio "
            "(app/services/connectors/sec_edgar.py)"
        )

    # 7. Calendario de earnings. Hoy no existe como ruta.
    calendar = client.get("/api/calendar/earnings")
    if calendar.status_code == 200:
        ok("GET /api/calendar/earnings", "2xx")
    else:
        missing.append(
            f"/api/calendar/earnings (status={calendar.status_code}): "
            "sin ruta de calendario — el sustituto real es /api/earnings/{ticker}/runs"
        )
        # Fallback real: el pipeline de earnings si responde 2xx.
        runs = client.get(f"/api/earnings/{ticker}/runs")
        assert runs.status_code == 200, f"earnings runs: {runs.status_code} {runs.text[:300]}"
        ok("GET /api/earnings/{ticker}/runs (fallback)", f"ticker={ticker}")

    # Limpieza (antes del paso de auth requerida): watchlist + regla
    # (la thesis queda como historial).
    client.delete(f"/api/watchlist/{ticker}")
    client.delete(f"/api/alerts/rules/{rule_id}")

    # 8. Auth firmada: con auth requerida, sin firma -> 401, con firma -> 2xx.
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    unsigned = client.get("/api/watchlist")
    assert unsigned.status_code == 401, f"sin firma debio ser 401: {unsigned.status_code}"
    signed = client.get(
        "/api/watchlist",
        headers=bound_headers(
            SECRET, "flow-tenant", "flow-user", method="GET", path="/api/watchlist"
        ),
    )
    assert signed.status_code == 200, f"con firma debio ser 200: {signed.status_code}"
    ok("auth firmada HMAC", "401 sin firma / 200 con firma")

    print("\n--- REPORTE FLUJO E2E ---")
    for line in report:
        print(line)
    if missing:
        print("--- ESLABONES FALTANTES ---")
        for line in missing:
            print("FALTA " + line)
    else:
        print("Sin eslabones faltantes.")
