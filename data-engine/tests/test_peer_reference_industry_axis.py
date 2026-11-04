"""Eje de referencia (FinanceDatabase) en la selección de comparables.

Una sola taxonomía equivocada o grosera no decide sola: la referencia de
instrumentos (tabla ``instrument_references``, seed FinanceDatabase) aporta
puntos y evidencia de negocio cuando coincide, rescata pares reales bajo
etiquetas groseras del enriquecimiento y veta conflictos que la etiqueta
principal no ve. Sin filas de referencia, el eje es inerte.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, InstrumentReference
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


def _ref(db, ticker, sector, industry):
    db.add(InstrumentReference(ticker_normalized=ticker, sector=sector, industry=industry))
    db.commit()


def _selected(db, target):
    out = PeerComparisonService().compare(db, target)
    return [row["ticker"] for row in out["companies"] if not row["is_target"]]


def test_reference_industry_builds_a_real_cohort_for_a_stub_target(db):
    """BFIT.AS (sin clasificar) + referencia: entra MEL.MC (Hospitality &
    Leisure, como Basic-Fit), no la A de la lista alfabética de stubs."""
    target = _co(db, "BFIT.AS", exchange="AMS")
    _co(db, "A3M.MC")
    _co(db, "ACS.MC")
    _co(db, "MEL.MC")
    _ref(db, "BFIT.AS", "Consumer Discretionary", "Hospitality & Leisure")
    _ref(db, "A3M.MC", "Communication Services", "Media")
    _ref(db, "ACS.MC", "Industrials", "Construction & Engineering")
    _ref(db, "MEL.MC", "Consumer Discretionary", "Hospitality & Leisure")
    assert _selected(db, target) == ["MEL.MC"]


def test_reference_conflict_vetoes_what_the_main_taxonomy_cannot_see(db):
    target = _co(db, "BFIT.AS", exchange="AMS")
    _co(db, "ACS.MC")
    _ref(db, "BFIT.AS", "Consumer Discretionary", "Hospitality & Leisure")
    _ref(db, "ACS.MC", "Industrials", "Construction & Engineering")
    assert _selected(db, target) == []


def test_reference_same_industry_rescues_from_coarse_main_labels(db):
    """Dos negocios iguales con etiquetas principales distintas (groseras):
    la referencia que declara la misma industria para ambos los salva."""
    target = _co(db, "CABLE1", sector="Communication Services", industry="Entertainment",
                 company_type="media_company")
    _co(db, "CABLE2", sector="Communication Services", industry="Telecom Services",
        company_type="media_company")
    _ref(db, "CABLE1", "Communication Services", "Fixed & Integrated Telecom")
    _ref(db, "CABLE2", "Communication Services", "Fixed & Integrated Telecom")
    assert _selected(db, target) == ["CABLE2"]


def test_reference_axis_is_inert_without_rows(db):
    target = _co(db, "BFIT.AS", exchange="AMS")
    for t in ("A3M.MC", "ACS.MC", "MEL.MC"):
        _co(db, t)
    assert _selected(db, target) == []


def test_reference_agreement_outranks_reference_conflict(db):
    """PLTR: WDC/STX comparten la etiqueta principal (grosera «software/
    tecnología») pero su referencia es hardware; el software con referencia
    coincidente los supera."""
    target = _co(db, "PLTR", sector="Technology", industry="Software - Application",
                 company_type="platform", currency="USD", exchange="NYSE")
    _co(db, "WDC", sector="Technology", industry="Software - Application",
        company_type="platform", currency="USD", exchange="NYSE")
    _co(db, "CRM", sector="Technology", industry="Software - Application",
        company_type="platform", currency="USD", exchange="NYSE")
    _ref(db, "PLTR", "Information Technology", "Software")
    _ref(db, "WDC", "Information Technology", "Computers & Hardware")
    _ref(db, "CRM", "Information Technology", "Software")
    selected = _selected(db, target)
    assert set(selected) == {"WDC", "CRM"}  # la etiqueta principal compartida no veta
    assert selected[0] == "CRM"  # pero la referencia coincidente manda
