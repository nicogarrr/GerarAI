"""GET /api/companies/search y /api/companies/basics.

/search: busqueda local del master sin proveedor externo. El buscador de
la app mostraba «fallo del proveedor de datos» cuando Finnhub devolvia
429 (cuota free de 60 req/min compartida por toda la app, quemada por la
propia watchlist; medido 2026-10-30): sin respaldo local la busqueda de
«Amzn» fallaba pese a tener AMAZON en el master.

/basics: basics por lote en UNA llamada, con la MISMA politica de alias
que GET /{ticker} (resolve_company), keyed por ticker pedido.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.companies import (
    MAX_BASICS_BATCH_TICKERS,
    companies_basics_batch,
    search_companies,
)
from app.models.entities import Base, Company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(
    db: Session,
    ticker: str,
    name: str | None = None,
    exchange: str = "NASDAQ",
    currency: str = "USD",
) -> Company:
    company = Company(
        ticker=ticker, name=name or f"{ticker} Co", exchange=exchange, currency=currency,
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_search_exact_ticker_wins_and_is_case_insensitive(db: Session):
    _company(db, "AMZN", "AMAZON.COM INC")
    _company(db, "AMZ", "AMZ HOLDINGS")
    _company(db, "ZZAMZNO", "OTRA")

    out = search_companies(q="amzn", db=db)

    tickers = [r.ticker for r in out.results]
    assert tickers[0] == "AMZN"
    assert set(tickers) == {"AMZN", "ZZAMZNO"}  # AMZ no contiene "amzn"


def test_search_matches_by_name_prefix_after_ticker_prefix(db: Session):
    _company(db, "AMZN", "AMAZON.COM INC")
    _company(db, "SAN", "BANCO SANTANDER SA", exchange="BME", currency="EUR")

    by_name = search_companies(q="amazon", db=db)
    assert [r.ticker for r in by_name.results] == ["AMZN"]

    by_lower = search_companies(q="santander", db=db)
    assert [r.ticker for r in by_lower.results] == ["SAN"]


def test_search_ticker_prefix_ranks_before_name_match(db: Session):
    _company(db, "AM", "AM CORP")
    _company(db, "ZZ", "AMALIA GROUP")

    out = search_companies(q="AM", db=db)

    assert [r.ticker for r in out.results] == ["AM", "ZZ"]


def test_search_limit_and_literal_wildcards(db: Session):
    for i in range(20):
        _company(db, f"AM{i:02d}")
    _company(db, "A_M", "GUION BAJO")

    out = search_companies(q="AM", db=db, limit=15)
    assert len(out.results) == 15

    # % y _ son literales, no comodines LIKE
    out = search_companies(q="A_M", db=db)
    assert [r.ticker for r in out.results] == ["A_M"]


def test_search_unknown_returns_empty_not_invention(db: Session):
    _company(db, "AMZN", "AMAZON.COM INC")
    out = search_companies(q="NVIDIA", db=db)
    assert out.results == []


def test_basics_maps_requested_ticker_and_alias_policy(db: Session):
    _company(db, "SAN", "BANCO SANTANDER SA", exchange="BME", currency="EUR")
    _company(db, "TSLA", "TESLA INC")

    out = companies_basics_batch(tickers="san.mc,TSLA,TSLA,NOPE", db=db)

    # keyed por ticker PEDIDO normalizado; dedupe de repetidos
    assert set(out.items) == {"SAN.MC", "TSLA"}
    assert out.items["SAN.MC"].ticker == "SAN"  # alias resuelto al canonico
    assert out.items["SAN.MC"].exchange == "BME"
    assert out.items["TSLA"].name == "TESLA INC"
    assert out.missing == ["NOPE"]


def test_basics_rejects_over_the_cap(db: Session):
    tickers = ",".join(f"X{i}" for i in range(MAX_BASICS_BATCH_TICKERS + 1))
    with pytest.raises(HTTPException) as excinfo:
        companies_basics_batch(tickers=tickers, db=db)
    assert excinfo.value.status_code == 400
