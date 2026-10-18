"""Contratos de resolve_company: exacto gana, fallback solo con sufijo conocido.

La píldora de búsqueda navega a /research/SAN.MC mientras el universo usa
tickers base (SAN). El fallback resuelve europeas sin tocar tickers reales
con punto (BRK.B) ni sufijos desconocidos.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company
from app.services.company_resolver import resolve_company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="X", currency="EUR",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def test_exact_match_wins(db):
    base = _company(db, "SAN")
    assert resolve_company(db, "SAN").id == base.id
    assert resolve_company(db, "san").id == base.id  # case-insensitive


def test_known_suffix_falls_back_to_base(db):
    base = _company(db, "SAN")
    assert resolve_company(db, "SAN.MC").id == base.id
    assert resolve_company(db, "san.mc").id == base.id


def test_exact_match_beats_suffix_fallback(db):
    base = _company(db, "SAN")
    dotted = _company(db, "SAN.MC")
    assert resolve_company(db, "SAN.MC").id == dotted.id
    assert resolve_company(db, "SAN").id == base.id


def test_unknown_suffix_never_falls_back(db):
    _company(db, "BRK")
    assert resolve_company(db, "BRK.B") is None  # tickers reales con punto intactos


def test_dotless_miss_returns_none(db):
    assert resolve_company(db, "NOEXISTE") is None


def test_suffix_without_base_company_returns_none(db):
    assert resolve_company(db, "FALTA.MC") is None


def test_us_share_class_dash_resolves_to_master_dot(db):
    """BRK-B (notacion Yahoo/SEC) resuelve a la ficha BRK.B del master."""
    brk = _company(db, "BRK.B")
    assert resolve_company(db, "BRK-B").id == brk.id
    assert resolve_company(db, "brk-b").id == brk.id


def test_us_share_class_dot_resolves_to_master_dash(db):
    """Simetrico: si el master guardara guion, el punto tambien resuelve."""
    brk = _company(db, "BRK-B")
    assert resolve_company(db, "BRK.B").id == brk.id


def test_share_class_exact_match_still_wins(db):
    dashed = _company(db, "BRK-B")
    _company(db, "BRK.B")
    assert resolve_company(db, "BRK-B").id == dashed.id


def test_share_class_variant_never_creates_identity(db):
    _company(db, "BRK.A")
    assert resolve_company(db, "BRK-B") is None  # variante distinta: no es la clase A
    assert resolve_company(db, "BTC-USD") is None  # sufijo >1 letra: no es clase US


def test_resolve_companies_share_class_bulk(db):
    from app.services.company_resolver import resolve_companies

    brk = _company(db, "BRK.B")
    companies, missing = resolve_companies(db, ["BRK-B", "AAPL"])
    assert [c.id for c in companies] == [brk.id]
    assert missing == ["AAPL"]
