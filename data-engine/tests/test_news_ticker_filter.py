from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Inc",
        exchange="NASDAQ",
        currency="USD",
        company_type="holding",
        valuation_model="unassigned",
    )


def test_news_events_filter_by_ticker():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(Tenant(id=1, external_id="t"))
        asts = _company("ASTS")
        rklb = _company("RKLB")
        db.add_all([asts, rklb])
        db.flush()
        db.add_all(
            [
                NewsEvent(
                    tenant_id=1, company_id=asts.id, title="asts news", source="rss",
                    url="https://publisher.example/1", date=NOW,
                    metadata_={"connector": "rss", "date_source": "source"},
                ),
                NewsEvent(
                    tenant_id=1, company_id=rklb.id, title="rklb news", source="rss",
                    url="https://publisher.example/2", date=NOW,
                    metadata_={"connector": "rss", "date_source": "source"},
                ),
                NewsEvent(
                    tenant_id=1, company_id=None, title="macro news", source="GDELT",
                    url="https://publisher.example/3", date=NOW,
                    metadata_={"connector": "gdelt", "news_lane": "macro"},
                ),
            ]
        )
        db.commit()

        app = FastAPI()
        app.include_router(news_module.router, prefix="/api/news")

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        client = TestClient(app)

        # Sin filtro: todo.
        response = client.get("/api/news")
        assert response.status_code == 200, response.text
        assert {row["title"] for row in response.json()} == {
            "asts news",
            "rklb news",
            "macro news",
        }

        # Con ticker (minusculas: normaliza a mayusculas): solo esa empresa.
        response = client.get("/api/news?ticker=asts")
        assert response.status_code == 200, response.text
        rows = response.json()
        assert {row["title"] for row in rows} == {"asts news"}
        assert rows[0]["ticker"] == "ASTS"

        # Ticker sin eventos: lista vacia, no error.
        response = client.get("/api/news?ticker=NVDA")
        assert response.status_code == 200, response.text
        assert response.json() == []
    engine.dispose()


def test_ticker_filter_paginates_within_ticker():
    """limit/offset recortan despues del filtro: paginas dentro del ticker."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(Tenant(id=1, external_id="t"))
        msft = _company("MSFT")
        db.add(msft)
        db.flush()
        db.add_all(
            [
                NewsEvent(
                    tenant_id=1, company_id=msft.id, title=f"msft news {i}", source="rss",
                    url=f"https://publisher.example/msft-{i}",
                    date=datetime(2026, 10, 9, 12 - i, tzinfo=UTC),
                    metadata_={"connector": "rss", "date_source": "source"},
                )
                for i in range(2)
            ]
        )
        db.commit()

        app = FastAPI()
        app.include_router(news_module.router, prefix="/api/news")

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        client = TestClient(app)

        page1 = client.get("/api/news?ticker=msft&limit=1&offset=0")
        page2 = client.get("/api/news?ticker=msft&limit=1&offset=1")
        assert page1.status_code == 200, page1.text
        assert page2.status_code == 200, page2.text
        titles1 = [row["title"] for row in page1.json()]
        titles2 = [row["title"] for row in page2.json()]
        assert len(titles1) == 1 and len(titles2) == 1
        assert titles1 != titles2
    engine.dispose()


def test_ticker_filter_does_not_leak_other_tenants():
    """Misma empresa, evento de otro tenant: el guard de tenant lo excluye."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add_all([Tenant(id=1, external_id="t"), Tenant(id=2, external_id="u")])
        aapl = _company("AAPL")
        db.add(aapl)
        db.flush()
        db.add_all(
            [
                NewsEvent(
                    tenant_id=1, company_id=aapl.id, title="aapl propia", source="rss",
                    url="https://publisher.example/propia", date=NOW,
                    metadata_={"connector": "rss", "date_source": "source"},
                ),
                NewsEvent(
                    tenant_id=2, company_id=aapl.id, title="aapl ajena", source="rss",
                    url="https://publisher.example/ajena", date=NOW,
                    metadata_={"connector": "rss", "date_source": "source"},
                ),
            ]
        )
        db.commit()

        # El guard de tenant lee session.info["tenant_id"] (ver app.core.database).
        db.info["tenant_id"] = 1

        app = FastAPI()
        app.include_router(news_module.router, prefix="/api/news")

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        client = TestClient(app)

        response = client.get("/api/news?ticker=AAPL")
        assert response.status_code == 200, response.text
        titles = [row["title"] for row in response.json()]
        assert "aapl propia" in titles
        assert "aapl ajena" not in titles
    engine.dispose()


def test_ticker_feed_hides_rows_that_only_carry_the_ticker_label():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(Tenant(id=1, external_id="t"))
        nvda = Company(
            ticker="NVDA", name="NVIDIA Corp", exchange="NASDAQ", currency="USD",
            company_type="holding", valuation_model="unassigned",
        )
        googl = Company(
            ticker="GOOGL", name="Alphabet Inc", exchange="NASDAQ", currency="USD",
            company_type="holding", valuation_model="unassigned",
        )
        db.add_all([nvda, googl])
        db.flush()
        meta = {"connector": "rss", "date_source": "source"}
        db.add_all(
            [
                NewsEvent(
                    tenant_id=1, company_id=nvda.id, source="rss", date=NOW, metadata_=meta,
                    title="NVDA Novo Nordisk cuts obesity drug price", summary="Novo Nordisk said on Monday",
                    url="https://publisher.example/a",
                ),
                NewsEvent(
                    tenant_id=1, company_id=nvda.id, source="rss", date=NOW, metadata_=meta,
                    title="NVDA NVIDIA unveils new Blackwell chip", summary="NVIDIA said on Monday",
                    url="https://publisher.example/b",
                ),
                NewsEvent(
                    tenant_id=1, company_id=googl.id, source="rss", date=NOW, metadata_=meta,
                    title="GOOGL Google launches new Gemini model", summary="",
                    url="https://publisher.example/d",
                ),
                NewsEvent(
                    tenant_id=1, company_id=googl.id, source="rss", date=NOW, metadata_=meta,
                    title="GOOGL Unity shares jump on game engine deal", summary="Unity said",
                    url="https://publisher.example/e",
                ),
                NewsEvent(
                    tenant_id=1, company_id=nvda.id, source="rss", date=NOW, metadata_=meta,
                    title="Chipmakers rally on export news", summary="",
                    url="https://publisher.example/c",
                ),
            ]
        )
        db.commit()

        app = FastAPI()
        app.include_router(news_module.router, prefix="/api/news")

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        client = TestClient(app)

        response = client.get("/api/news?ticker=NVDA")
        assert response.status_code == 200, response.text
        titles = {row["title"] for row in response.json()}
        assert titles == {"NVDA NVIDIA unveils new Blackwell chip", "Chipmakers rally on export news"}

        # El feed global no se toca: las filas siguen en la base.
        # Marca verificada (Google para GOOGL): se conserva; Unity solo con etiqueta: se oculta.
        googl_titles = {row["title"] for row in client.get("/api/news?ticker=GOOGL").json()}
        assert googl_titles == {"GOOGL Google launches new Gemini model"}
        # Feed global: tambien oculta las filas con solo la etiqueta (Unity, Novo) y el offset cuenta visibles.
        visible = [row["title"] for row in client.get("/api/news").json()]
        assert len(visible) == 3
        assert not any("Novo Nordisk" in t or "Unity" in t for t in visible)
        second = client.get("/api/news?limit=1&offset=1").json()
        assert [row["title"] for row in second] == [visible[1]]
    engine.dispose()
