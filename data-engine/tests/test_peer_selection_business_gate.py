"""Puerta de negocio en la selección de comparables (batería de 7, 4-nov-2026).

BFIT.AS en tenant 5 salía con «constructoras españolas» (A3M, ACS, ACX, AENA…):
el universo era 100 % stubs sin clasificar y «mismo company_type/valuation_model»
puntuaba igualdades VACÍAS (+0,26), con desempate alfabético. Ahora: igualdad de
placeholders no puntúa, conflicto conocido industria/sector excluye, y sin una
evidencia de negocio conocida compartida no hay cohorte (dato ausente = N/D).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.peer_comparison_service import PeerComparisonService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _co(db, ticker, *, sector="Unknown", industry="Unknown", company_type="unassigned",
        valuation_model="unassigned", currency="EUR", exchange="MCE", tags=None):
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, currency=currency,
        sector=sector, industry=industry, company_type=company_type,
        valuation_model=valuation_model, special_sources=[], special_risks=[],
        factor_tags=tags or [],
    )
    db.add(company)
    db.commit()
    return company


def _selected(service, db, target):
    out = service.compare(db, target)
    return [row["ticker"] for row in out["companies"] if not row["is_target"]], out


def test_stub_universe_gives_no_peers_instead_of_alphabetical_cohort(db):
    """El caso BFIT.AS: sin clasificar en un universo de stubs, 0 comparables."""
    target = _co(db, "BFIT.AS", exchange="AMS")
    for t in ("A3M", "ACS", "ACX", "AENA", "AI"):
        _co(db, t)
    selected, out = _selected(PeerComparisonService(), db, target)
    assert selected == []
    assert out["peer_count_selected"] == 0


def test_known_industry_sector_conflict_is_excluded(db):
    target = _co(db, "GYM", sector="Consumer Cyclical", industry="Leisure",
                 company_type="consumer_services")
    _co(db, "CONSTR", sector="Industrials", industry="Construction & Engineering",
        company_type="industrial")
    _co(db, "RIVALGYM", sector="Consumer Cyclical", industry="Leisure",
        company_type="consumer_services")
    selected, _ = _selected(PeerComparisonService(), db, target)
    assert selected == ["RIVALGYM"]


def test_same_sector_different_industry_still_allowed(db):
    """CHTR-CMCSA: industria distinta pero sector común conocido → entra."""
    target = _co(db, "CABLE1", sector="Communication Services", industry="Entertainment",
                 company_type="media_company")
    _co(db, "CABLE2", sector="Communication Services", industry="Telecom Services",
        company_type="media_company")
    selected, _ = _selected(PeerComparisonService(), db, target)
    assert selected == ["CABLE2"]


def test_currency_exchange_size_alone_never_qualifies(db):
    target = _co(db, "TGT", sector="Consumer Cyclical", industry="Leisure",
                 company_type="consumer_services")
    _co(db, "ONLYEUR")  # stub: solo divisa/plaza en común
    selected, _ = _selected(PeerComparisonService(), db, target)
    assert selected == []


def test_known_company_type_and_shared_tags_qualify(db):
    target = _co(db, "TGT2", company_type="holding", tags=["compounders", "europe"])
    _co(db, "PEER2", company_type="holding", tags=["compounders"], exchange="AMS")
    _co(db, "NOPE2", company_type="industrial", tags=[])
    selected, _ = _selected(PeerComparisonService(), db, target)
    assert selected == ["PEER2"]


def test_enriched_cohort_like_unh_is_preserved(db):
    """Regresión: una cohorte buena conocida (sanitarias) no cambia."""
    target = _co(db, "UNH", sector="Healthcare", industry="Healthcare Plans",
                 company_type="insurer", currency="USD", exchange="NYSE")
    for t in ("ELV", "CVS", "HCA"):
        _co(db, t, sector="Healthcare", industry="Healthcare Plans",
            company_type="insurer", currency="USD", exchange="NYSE")
    _co(db, "UNP", sector="Industrials", industry="Railroads",
        company_type="railroad", currency="USD", exchange="NYSE")
    selected, _ = _selected(PeerComparisonService(), db, target)
    assert set(selected) == {"ELV", "CVS", "HCA"}
