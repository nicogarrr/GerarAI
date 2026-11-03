"""Paginacion y filtro de carril de /api/news (scroll infinito)."""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant

# Relativa a ahora: la ruta filtra frescura real (macro 72 h) contra el reloj
# del sistema; una fecha fija (27-sep) quedó vieja y el carril macro devolvía 0.
NOW = datetime.now(UTC)


def _client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    company = Company(ticker="ASTS", name="AST", exchange="NASDAQ", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add(company)
    db.flush()
    for i in range(5):
        db.add(NewsEvent(tenant_id=1, company_id=company.id, title=f"emp {i}", source="rss",
                         url=f"https://p.example/e{i}", date=NOW - timedelta(hours=i),
                         metadata_={"date_source": "source"}))
    for i in range(3):
        db.add(NewsEvent(tenant_id=1, company_id=None, title=f"mac {i}", source="GDELT",
                         url=f"https://p.example/m{i}", date=NOW - timedelta(minutes=i * 7),
                         metadata_={"news_lane": "macro", "macro_theme": "ormuz"}))
    db.commit()
    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_pages_do_not_overlap_and_cover_all():
    client = _client()
    first = client.get("/api/news", params={"limit": 3, "offset": 0}).json()
    second = client.get("/api/news", params={"limit": 3, "offset": 3}).json()
    third = client.get("/api/news", params={"limit": 3, "offset": 6}).json()
    ids = [r["id"] for r in first + second + third]
    assert len(first) == 3 and len(second) == 3 and len(third) == 2
    assert len(set(ids)) == 8


def test_lane_filter_is_applied_in_sql():
    client = _client()
    macro = client.get("/api/news", params={"lane": "macro"}).json()
    empresa = client.get("/api/news", params={"lane": "empresa", "limit": 2}).json()
    assert {r["news_lane"] for r in macro} == {"macro"} and len(macro) == 3
    assert all(r["ticker"] == "ASTS" for r in empresa) and len(empresa) == 2


def test_invalid_params_rejected():
    client = _client()
    assert client.get("/api/news", params={"limit": 0}).status_code == 422
    assert client.get("/api/news", params={"limit": 101}).status_code == 422
    assert client.get("/api/news", params={"offset": -1}).status_code == 422
    assert client.get("/api/news", params={"lane": "otro"}).status_code == 422


def test_scan_keyset_sin_offset_y_con_fechas_empatadas(monkeypatch):
    """El barrido por chunks no usa OFFSET (keyset) y no pierde ni repite
    filas con la fecha empatada entre chunks."""
    from sqlalchemy import event

    from app.models.entities import NewsEvent

    monkeypatch.setattr(news_module, "_SCAN_CHUNK", 3)
    client, db = _client_with_db()
    base = NOW - timedelta(days=1)
    # 8 filas: 3 grupos de fecha empatada cruzando los chunks de 3.
    for i in range(8):
        db.add(NewsEvent(tenant_id=1, company_id=None, title=f"k {i}", source="rss",
                         url=f"https://p.example/k{i}",
                         date=base - timedelta(hours=i // 3),
                         metadata_={"news_lane": "macro", "macro_theme": "x"}))
    db.commit()
    statements = []
    event.listen(db.get_bind(), "before_cursor_execute",
                 lambda conn, cursor, statement, parameters, context, executemany: statements.append((statement, parameters)))
    first = client.get("/api/news", params={"limit": 2, "offset": 4, "lane": "macro"}).json()
    assert len(first) == 2
    selects = [(s, p) for s, p in statements if "FROM news_events" in s and "SELECT" in s]
    assert len(selects) >= 2  # hubo mas de un chunk
    # Keyset: ningun chunk barre con OFFSET (sqlite renderiza OFFSET ? pero
    # siempre ligado a 0; el scan viejo ligaba el offset creciente).
    assert all(params[-1] == 0 for _, params in selects)

    # Cobertura completa sin solape paginando de 2 en 2 (8 macro + 3 del fixture).
    seen, off = [], 0
    while True:
        page = client.get("/api/news", params={"limit": 2, "offset": off, "lane": "macro"}).json()
        if not page:
            break
        seen += [r["id"] for r in page]
        off += 2
        if off > 40:
            break
    assert len(seen) == len(set(seen)) == 11


def _client_with_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    for i in range(3):
        db.add(NewsEvent(tenant_id=1, company_id=None, title=f"mac {i}", source="GDELT",
                         url=f"https://p.example/m{i}", date=NOW - timedelta(minutes=i * 7),
                         metadata_={"news_lane": "macro", "macro_theme": "ormuz"}))
    db.commit()
    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app), db
