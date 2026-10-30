"""Contrato del buscador de instrumentos de /api/portfolio/image/instruments.

Sin cobertura previa a nivel de ruta: los comodines SQL (``%``, ``_``, ``\\``)
deben tratarse como literales (un ``_`` no es «un caracter cualquiera»), las
entradas de exchange UNKNOWN quedan fuera y la respuesta va acotada a 12.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.portfolio_images import instruments
from app.models.entities import Base, Company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        db.add_all(
            [
                Company(ticker="ABC", name="Alpha Beta Corp", exchange="NYSE", company_type="x", valuation_model="y"),
                Company(ticker="A_C", name="Under Score Inc", exchange="NYSE", company_type="x", valuation_model="y"),
                Company(ticker="GH%I", name="Percent Co", exchange="NASDAQ", company_type="x", valuation_model="y"),
                Company(ticker="TEST1", name="Test placeholder", exchange="UNKNOWN", company_type="x", valuation_model="y"),
            ]
        )
        db.commit()
        yield db
    engine.dispose()


def test_underscore_is_literal_not_wildcard(db):
    # Sin escape, "_" casa con cualquier caracter y devolveria ABC tambien.
    assert [r["ticker"] for r in instruments(q="_", db=db)] == ["A_C"]


def test_percent_is_literal(db):
    assert [r["ticker"] for r in instruments(q="%", db=db)] == ["GH%I"]


def test_matches_ticker_and_name(db):
    assert [r["ticker"] for r in instruments(q="alpha", db=db)] == ["ABC"]
    assert [r["ticker"] for r in instruments(q="AB", db=db)] == ["ABC"]


def test_unknown_exchange_excluded(db):
    assert [r["ticker"] for r in instruments(q="TEST", db=db)] == []
    assert [r["ticker"] for r in instruments(q="placeholder", db=db)] == []


def test_result_shape_and_order(db):
    rows = instruments(q="A", db=db)
    assert [r["ticker"] for r in rows] == sorted(r["ticker"] for r in rows)
    assert set(rows[0]) == {"ticker", "name", "exchange", "currency"}


def test_limit_is_twelve(db):
    for i in range(20):
        db.add(Company(ticker=f"LIM{i:02d}", name=f"Limit {i}", exchange="NYSE", company_type="x", valuation_model="y"))
    db.commit()
    assert len(instruments(q="LIM", db=db)) == 12
