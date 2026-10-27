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


def test_explicit_ticker_without_scope_is_not_narrowed_to_followed():
    """Regresion: ticker explicito sin Position/WatchItem lista y cuenta su doc.

    Matriz ticker x scope sobre listado y recuento, con aislamiento de tenant.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant_a = Tenant(external_id="rx-a", name="RX A")
        tenant_b = Tenant(external_id="rx-b", name="RX B")
        db.add_all([tenant_a, tenant_b])
        db.flush()

        db.info["tenant_id"] = tenant_a.id
        unfollowed = _company("MSFT")
        followed = _company("AAPL")
        db.add_all([unfollowed, followed])
        db.flush()
        db.add(WatchItem(symbol="AAPL"))
        db.add_all(
            [
                Document(company_id=unfollowed.id, title="MSFT upload", source_type="manual_upload"),
                Document(company_id=followed.id, title="AAPL upload", source_type="manual_upload"),
            ]
        )
        db.flush()

        db.info["tenant_id"] = tenant_b.id
        db.add(Document(company_id=unfollowed.id, title="MSFT of B", source_type="manual_upload"))
        db.flush()

        db.info["tenant_id"] = tenant_a.id
        # Sin scope (None) y con ticker: consulta explicita, no followed implicito.
        assert [r["title"] for r in _list(db, ticker="MSFT", scope=None)] == ["MSFT upload"]
        assert _count(db, ticker="MSFT", scope=None) == 1
        assert _count(db, ticker="AAPL", scope=None) == 1
        # scope explicito se respeta: followed + ticker no seguido = vacio.
        assert _list(db, ticker="MSFT", scope="followed") == []
        assert _count(db, ticker="MSFT", scope="followed") == 0
        assert _count(db, ticker="MSFT", scope="all") == 1
        # Sin ticker y sin scope: inventario global = followed.
        assert {r["ticker"] for r in _list(db, scope=None)} == {"AAPL"}
        assert _count(db, scope=None) == 1
        assert _count(db, scope="all") == 2
        # Aislamiento: el doc de B no aparece en A y viceversa.
        db.info["tenant_id"] = tenant_b.id
        assert [r["title"] for r in _list(db, ticker="MSFT", scope=None)] == ["MSFT of B"]
        assert _count(db, ticker="AAPL", scope=None) == 0
