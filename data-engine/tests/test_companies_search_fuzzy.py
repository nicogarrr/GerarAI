"""Respaldo tolerante a erratas de GET /api/companies/search.

Caso real 2026-11-19: «Antrophic» (errata) en el buscador del móvil no
devolvía nada —ni master, ni proveedor— y la app solo ofrecía «Abrir la
ficha de ANTROPHIC», una ficha vacía, el mismo día de la IPO de Anthropic.
Con una empresa en el master, la errata pequeña ahora la encuentra.

El respaldo SOLO se activa cuando la búsqueda literal no devuelve nada:
nunca desplaza ni reordena coincidencias literales. La política de umbrales
(≥ 5 letras; distancia 1 hasta 7 letras, 2 desde 8) es la misma que aplica
el Cerebro a tus empresas (app.services.company_names).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.companies import search_companies
from app.models.entities import Base, Company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str, name: str) -> Company:
    company = Company(
        ticker=ticker, name=name, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_antrophic_finds_anthropic(db: Session):
    """La errata real de la captura: «Antrophic» -> Anthropic (ANT)."""
    _company(db, "ANT", "Anthropic, PBC")

    out = search_companies(q="Antrophic", db=db)

    assert [r.ticker for r in out.results] == ["ANT"]


def test_fuzzy_is_case_and_accent_insensitive(db: Session):
    _company(db, "ANT", "Anthropic, PBC")

    out = search_companies(q="ANTROPHIC", db=db)

    assert [r.ticker for r in out.results] == ["ANT"]


def test_transposition_of_neighbouring_letters_matches(db: Session):
    _company(db, "MSFT", "Microsoft Corporation")

    out = search_companies(q="Mcirosoft", db=db)

    assert [r.ticker for r in out.results] == ["MSFT"]


def test_literal_matches_win_and_fuzzy_never_runs(db: Session):
    """Con coincidencia literal no hay barrido aproximado: nada que desplazar."""
    _company(db, "ANT", "Anthropic, PBC")
    _company(db, "ANTM", "Anthem Inc")

    out = search_companies(q="anth", db=db)

    tickers = [r.ticker for r in out.results]
    assert "ANT" in tickers  # literal por prefijo de nombre


def test_short_term_never_guesses(db: Session):
    _company(db, "ANT", "Anthropic, PBC")

    out = search_companies(q="zz", db=db)

    assert out.results == []


def test_unrelated_term_returns_nothing_invented(db: Session):
    _company(db, "ANT", "Anthropic, PBC")
    _company(db, "MSFT", "Microsoft Corporation")

    out = search_companies(q="wxyzqr", db=db)

    assert out.results == []


def test_term_with_digits_is_not_a_name_guess(db: Session):
    _company(db, "ANT", "Anthropic, PBC")

    out = search_companies(q="anthr0piczz", db=db)

    assert out.results == []


def test_several_candidates_ranked_by_distance_then_ticker(db: Session):
    """El buscador sí puede mostrar varias candidatas: orden honesto."""
    _company(db, "ANT", "Anthropic, PBC")
    _company(db, "ANH", "Anthropic Health")
    _company(db, "ANTX", "Antrhopic Lab")  # a 2 letras de «antrophic», sin solape literal

    out = search_companies(q="antrhopic", db=db)

    # ANTX es literal (prefijo de nombre): el respaldo aproximado ni se activa.
    assert [r.ticker for r in out.results] == ["ANTX"]

    out = search_companies(q="antrophic", db=db)

    # Sin literal: las tres a distancia 2 (límite para ≥ 8 letras); desempate por ticker.
    assert [r.ticker for r in out.results] == ["ANH", "ANT", "ANTX"]


def test_fuzzy_respects_limit(db: Session):
    _company(db, "ANH", "Anthropic Health")
    _company(db, "ANT", "Anthropic, PBC")

    out = search_companies(q="antrophic", limit=1, db=db)

    assert len(out.results) == 1


def test_accents_folded_either_way(db: Session):
    """«nestle» encuentra «Nestlé S.A.» y «loreal» a «L'Oréal» (y al revés)."""
    _company(db, "NESN", "Nestlé S.A.")
    _company(db, "OR", "L'Oréal")

    assert [r.ticker for r in search_companies(q="nestle", db=db).results] == ["NESN"]
    assert [r.ticker for r in search_companies(q="Nestlé", db=db).results] == ["NESN"]
    assert [r.ticker for r in search_companies(q="loreal", db=db).results] == ["OR"]
    assert [r.ticker for r in search_companies(q="L'Oréal", db=db).results] == ["OR"]
