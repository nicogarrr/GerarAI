"""Watchlist con sufijo de mercado o en minusculas cuenta como "seguida".

`_followed_company_ids` unia `WatchItem.symbol == Company.ticker` por igualdad
exacta, mientras la ficha resuelve alias con `resolve_company` (SAN.MC -> SAN).
Un valor europeo de la watchlist quedaba fuera de `scope=followed`.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Document, Tenant, WatchItem
from tests.test_source_documents_scope import _company, _count, _list


def test_watchlist_symbol_with_market_suffix_counts_as_followed():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="scope-suffix", name="Scope Suffix")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id

        san = _company("SAN")
        aapl = _company("AAPL")
        other = _company("TSLA")
        db.add_all([san, aapl, other])
        db.flush()
        db.add_all([WatchItem(symbol="SAN.MC"), WatchItem(symbol="aapl")])
        db.add_all(
            [
                Document(company_id=san.id, title="Santander informe anual", source_type="sec"),
                Document(company_id=aapl.id, title="AAPL 10-K", source_type="sec"),
                Document(company_id=other.id, title="TSLA 10-K", source_type="sec"),
            ]
        )
        db.flush()

        assert _count(db) == 2
        assert {row["ticker"] for row in _list(db)} == {"SAN", "AAPL"}
        assert _count(db, ticker="SAN.MC", scope="followed") == 1
        assert _count(db, ticker="SAN.MC", scope="all") == 1


def test_unknown_watchlist_symbol_does_not_follow_anything():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="scope-unknown", name="Scope Unknown")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        msft = _company("MSFT")
        db.add(msft)
        db.flush()
        db.add(WatchItem(symbol="NOEXISTE.XX"))
        db.add(Document(company_id=msft.id, title="MSFT 10-K", source_type="sec"))
        db.flush()

        assert _count(db) == 0
        assert _count(db, scope="all") == 1
