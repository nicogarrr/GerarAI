"""Alcance de /api/sources/documents: seguido (cartera + watchlist) y all.

El inventario global mostraba documentos de empresas que el tenant no sigue.
`scope=followed` (default) limita a las empresas con `Position` o `WatchItem`
del tenant; `all` conserva el inventario completo. Listado y recuento comparten
exactamente los mismos filtros y siguen aislados por tenant.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.sources import documents, documents_count
from app.core.database import Base
from app.models import Company, Document, Position, Tenant, WatchItem


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def _list(db: Session, **kwargs):
    params = {
        "ticker": None,
        "scope": "followed",
        "source_type": None,
        "q": None,
        "include_chunks": False,
        "page": 1,
        "page_size": 50,
        "chunk_limit": 1000,
        "chunk_text_limit": 1500,
        **kwargs,
    }
    return documents(db=db, **params)


def _count(db: Session, **kwargs) -> int:
    params = {
        "ticker": None,
        "scope": "followed",
        "source_type": None,
        "q": None,
        **kwargs,
    }
    return documents_count(db=db, **params)["total"]


def test_followed_scope_is_cartera_plus_watchlist_and_tenant_scoped():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant_a = Tenant(external_id="scope-a", name="Scope A")
        tenant_b = Tenant(external_id="scope-b", name="Scope B")
        db.add_all([tenant_a, tenant_b])
        db.flush()

        db.info["tenant_id"] = tenant_a.id
        held = _company("MSFT")
        watched = _company("AAPL")
        other = _company("TSLA")
        db.add_all([held, watched, other])
        db.flush()
        db.add_all(
            [
                Position(company_id=held.id, quantity=10),
                WatchItem(symbol="AAPL"),
            ]
        )
        db.add_all(
            [
                Document(
                    company_id=held.id,
                    title="MSFT 10-K annual report",
                    source_type="sec",
                ),
                Document(
                    company_id=held.id,
                    title="MSFT 8-K current report",
                    source_type="sec",
                ),
                Document(
                    company_id=watched.id,
                    title="AAPL earnings transcript",
                    source_type="manual_transcript",
                ),
                Document(
                    company_id=other.id,
                    title="TSLA annual report",
                    source_type="sec",
                ),
                Document(
                    company_id=None,
                    title="Market note",
                    source_type="manual_upload",
                ),
            ]
        )
        db.flush()  # el tenant A se asigna al flush

        db.info["tenant_id"] = tenant_b.id
        b_held = _company("V")
        db.add(b_held)
        db.flush()
        db.add(Position(company_id=b_held.id, quantity=5))
        db.add(
            Document(
                company_id=b_held.id,
                title="V annual report",
                source_type="sec",
            )
        )
        db.flush()  # el documento de B se asigna a B

        db.info["tenant_id"] = tenant_a.id
        # Default = followed: solo cartera + watchlist, nunca el resto.
        assert _count(db) == 3
        assert {row["ticker"] for row in _list(db)} == {"MSFT", "AAPL"}

        # all conserva el inventario del tenant A, sin ver el de B.
        assert _count(db, scope="all") == 5
        assert {row["ticker"] for row in _list(db, scope="all")} == {
            "MSFT",
            "AAPL",
            "TSLA",
            None,
        }

        # Filtros combinados: mismo subconjunto en pagina y count.
        assert _count(db, source_type="sec") == 2
        assert _count(db, q="annual") == 1
        assert _count(db, source_type="sec", q="8-K") == 1
        combined = _list(db, scope="all", source_type="sec", q="annual")
        assert {row["title"] for row in combined} == {
            "MSFT 10-K annual report",
            "TSLA annual report",
        }
        assert _count(db, scope="all", source_type="sec", q="annual") == len(combined)
        assert _count(db, source_type="sec", q="annual") == 1

        # Tenant B ve solo lo suyo, con el mismo default followed.
        db.info["tenant_id"] = tenant_b.id
        assert _count(db) == 1
        assert [row["ticker"] for row in _list(db, scope="all")] == ["V"]
        assert _count(db, q="annual") == 1
        assert _count(db, q="MSFT") == 0
