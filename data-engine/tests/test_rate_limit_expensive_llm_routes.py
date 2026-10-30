"""Las rutas que llaman a un LLM en la peticion cuentan en el tier caro.

Antes solo /chat, /extract-kpis, /long-term-model/generate, /thesis/generate y
/snapshot/refresh eran "expensive" (20/min); debate de tesis, asistente,
propuestas de paper trading, segundo orden, etc. iban por el estandar (300/min)
y un usuario podia agotar la cuota compartida del proveedor LLM.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import _tier_for

LLM_ROUTES = [
    "/api/news/123/second-order",
    "/api/companies/AAPL/inferred-inputs/llm",
    "/api/bottlenecks/discoveries/run",
    "/api/paper-trading/llm-proposals",
    "/api/paper-trading/feed",
    "/api/propicks/review",
    "/api/thesis/AAPL/debate",
    "/api/research/assistant",
    "/api/knowledge/documents/7/extract-principles",
    "/api/knowledge/documents/upload",
    "/api/settings/llm/test",
    "/api/knowledge-rag/query",
]


@pytest.mark.parametrize("path", LLM_ROUTES)
def test_llm_routes_are_expensive(path: str) -> None:
    assert _tier_for(path) == "expensive"
    assert _tier_for(path + "/") == "expensive"


@pytest.mark.parametrize(
    "path",
    [
        # Traducciones automaticas por titular visible: proveedor gratuito y cache.
        "/api/news/translate-headline",
        "/api/news/123/translation",
        "/api/news/123/translation/summary",
        # Lecturas baratas vecinas de las rutas caras.
        "/api/propicks/review/brier",
        "/api/knowledge/documents",
        "/api/settings/llm",
        "/api/paper-trading/proposals",
        "/api/thesis/AAPL",
    ],
)
def test_cheap_neighbours_stay_standard(path: str) -> None:
    assert _tier_for(path) == "standard"


def test_market_and_existing_markers_unchanged() -> None:
    assert _tier_for("/api/market/quote/AAPL") == "market"
    assert _tier_for("/api/chat") == "expensive"
    assert _tier_for("/api/thesis/generate") == "expensive"


def test_every_suffix_matches_a_real_route() -> None:
    """Un sufijo que no casa con ninguna ruta es una errata que deja la ruta cara sin limite."""
    from app.core.rate_limit import EXPENSIVE_PATH_SUFFIXES
    from main import app

    def walk(routes, prefix=""):
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                ctx = getattr(route, "include_context", None)
                yield from walk(inner.routes, prefix + (getattr(ctx, "prefix", "") or "") + (inner.prefix or ""))
            elif hasattr(route, "routes") and not hasattr(route, "endpoint"):
                yield from walk(route.routes, prefix + (getattr(route, "path", "") or ""))
            else:
                yield prefix + getattr(route, "path", "")

    paths = list(walk(app.routes))
    for suffix in EXPENSIVE_PATH_SUFFIXES:
        assert any(p.endswith(suffix) for p in paths), suffix
