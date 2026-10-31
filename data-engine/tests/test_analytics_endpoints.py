"""La API analytics legacy (data-engine/routers/analytics.py) fue retirada.

Los endpoints /analytics/* ya no se montan en main.py: el frontend consume
el research API (/api/*). Este test garantiza que la superficie legacy
devuelve 404 y que no hay efectos colaterales sobre el research API.

Run from data-engine/:
    pytest tests/test_analytics_endpoints.py -v
"""

import pytest

import main
from tests.auth_helpers import csrf_client


@pytest.fixture
def client():
    return csrf_client(main.app)


def test_legacy_analytics_endpoints_are_retired(client):
    retired_endpoints = [
        ("post", "/analytics/portfolio", {"symbols": ["AAPL"]}),
        ("post", "/analytics/portfolio/returns", {"symbols": ["AAPL"]}),
        ("get", "/analytics/holding/AAPL", None),
        ("post", "/analytics/montecarlo", {"symbols": ["AAPL"]}),
        ("post", "/analytics/correlation", {"symbols": ["AAPL"]}),
        ("get", "/analytics/regime/AAPL", None),
    ]
    for method, path, body in retired_endpoints:
        kwargs = {"json": body} if body is not None else {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404, f"{path} debe estar retirado, obtuvo {response.status_code}"


def test_no_legacy_analytics_routes_in_openapi(client):
    paths = main.app.openapi()["paths"]
    legacy = [path for path in paths if path.startswith("/analytics")]
    assert legacy == []