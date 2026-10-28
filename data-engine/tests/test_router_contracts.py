"""Contratos de rutas del data engine.

Tras la consolidación del backend, la API legacy (data-engine/routers/) fue
retirada: fundamentals, market y analytics ya no se montan en main.py.
Estos contratos garantizan que las rutas retiradas devuelven 404 y que las
rutas públicas/actuales siguen expuestas.

Run from data-engine/:
    pytest tests/test_router_contracts.py -v
"""

from fastapi.testclient import TestClient

import main


def test_legacy_fundamentals_routes_are_retired():
    client = TestClient(main.app)

    retired = [
        "/fundamentals/aapl",
        "/financial-growth/AAPL",
        "/ratios-ttm/AAPL",
        "/dcf/AAPL",
        "/enterprise-value/AAPL",
        "/key-metrics-ttm/AAPL",
        "/financial-scores/AAPL",
        "/owner-earnings/AAPL",
        "/price-target/AAPL",
        "/grades/AAPL",
        "/peers/AAPL",
        "/earnings-transcript/AAPL",
        "/earnings-transcript-list/AAPL",
        "/treasury-rates",
        "/analyst-estimates/AAPL",
        "/press-releases/AAPL",
    ]
    for path in retired:
        response = client.get(path)
        assert response.status_code == 404, f"{path} debe estar retirado, obtuvo {response.status_code}"


def test_legacy_market_routes_are_retired():
    client = TestClient(main.app)

    retired = [
        "/market-movers/gainers",
        "/market-movers/losers",
        "/market-movers/active",
        "/screener",
        "/news/fmp-articles",
        "/news/general",
        "/dividends/AAPL",
        "/stock-peers/AAPL",
        "/quote/aapl",
        "/insider-trading/AAPL",
        "/strategies/garp",
        "/company-news/AAPL",
        "/test",
    ]
    for path in retired:
        response = client.get(path)
        assert response.status_code == 404, f"{path} debe estar retirado, obtuvo {response.status_code}"

    assert client.post("/batch-quotes", json=["aapl"]).status_code == 404


def test_legacy_analytics_routes_are_retired():
    client = TestClient(main.app)

    retired = [
        "/analytics/portfolio",
        "/analytics/portfolio/returns",
        "/analytics/holding/AAPL",
        "/analytics/montecarlo",
        "/analytics/correlation",
        "/analytics/regime/AAPL",
    ]
    for path in retired:
        response = client.post(path, json={"symbols": ["AAPL"]}, headers={"content-type": "application/json"})
        assert response.status_code == 404, f"{path} debe estar retirado, obtuvo {response.status_code}"


def test_legacy_direct_vector_knowledge_routes_are_retired():
    response = TestClient(main.app).post(
        "/knowledge/upload",
        json={"collection": "analyses", "content": "must not bypass canonical ingestion"},
    )

    assert response.status_code == 404


def test_api_prefix_still_serves_research_routes():
    # /api/news lee la tabla news_events: el test aporta su propio esquema en
    # memoria (get_db sobreescrito) en vez de depender de un SQLite compartido
    # que otro test haya migrado antes (dependencia de orden).
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.database import Base, get_db

    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _db():
        with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = _db
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        response = client.get("/api/news")
    finally:
        main.app.dependency_overrides.pop(get_db, None)
    assert response.status_code in (401, 200)


def test_health_is_public():
    client = TestClient(main.app)

    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert "version" in payload
    assert payload["version"].startswith("main-")