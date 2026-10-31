from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.research_assistant import AssistantRequest, AssistantResponse
from app.models.entities import Base, Company, Document, FinancialFact, NewsEvent, Tenant
from app.services.research_assistant_service import answer

import pytest


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def setup(db):
    tenant = Tenant(external_id="guard-t", name="T", status="active", metadata_={})
    san = Company(ticker="SAN.MC", name="Santander", exchange="BME", currency="EUR",
                  company_type="holding", valuation_model="unassigned")
    db.add_all((tenant, san))
    db.flush()
    db.info["tenant_id"] = tenant.id
    doc = Document(tenant_id=tenant.id, company_id=san.id, title="Resultados 2024",
                   source_type="company_ir", source_url="https://www.santander.com/results.pdf",
                   published_at=datetime(2025, 2, 1, tzinfo=UTC))
    db.add(doc)
    db.flush()
    db.add(FinancialFact(tenant_id=tenant.id, company_id=san.id, metric="revenue",
                         value=Decimal("50000"), unit="EUR", period="FY2024", fiscal_year=2024,
                         source_id=doc.id, source_type="company_ir", is_reported=True))
    db.commit()
    return tenant, san


def test_question_about_other_ticker_fails_closed(db):
    """Pregunta con ticker distinto al del contexto: sin evidencia de ESE ticker,
    insufficient_data; nunca la evidencia del ticker de contexto."""
    setup(db)
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", question="¿Qué ingresos tuvo ACS.MC?", ticker="SAN.MC")))
    assert response.status == "insufficient_data"
    assert response.citations == []


def test_question_about_other_ticker_uses_its_evidence(db):
    """Con ACS.MC registrado y evidenciado, la respuesta cita a ACS.MC, no a SAN.MC."""
    tenant, san = setup(db)
    acs = Company(ticker="ACS.MC", name="ACS", exchange="BME", currency="EUR",
                  company_type="holding", valuation_model="unassigned")
    db.add(acs)
    db.flush()
    doc = Document(tenant_id=tenant.id, company_id=acs.id, title="Memoria ACS 2024",
                   source_type="company_ir", source_url="https://www.acs.com/memoria.pdf",
                   published_at=datetime(2025, 3, 1, tzinfo=UTC))
    db.add(doc)
    db.flush()
    db.add(FinancialFact(tenant_id=tenant.id, company_id=acs.id, metric="revenue",
                         value=Decimal("41654"), unit="EUR", period="FY2024", fiscal_year=2024,
                         source_id=doc.id, source_type="company_ir", is_reported=True))
    db.commit()
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", question="¿Qué ingresos tuvo ACS.MC?", ticker="SAN.MC")))
    assert response.status == "answered"
    assert len(response.citations) == 1
    assert response.citations[0].source == "Memoria ACS 2024"
    assert "41654" in response.citations[0].excerpt


def test_offtopic_question_does_not_get_newest_source(db):
    """Pregunta sin relacion con la evidencia: insufficient_data; la fuente mas
    reciente no se devuelve como si respondiera por nombrar a la empresa."""
    tenant, san = setup(db)
    db.add(NewsEvent(tenant_id=tenant.id, company_id=san.id, title="Santander gana 12.000M en 2024",
                     source="expansion",
                     url="https://www.expansion.com/santander-beneficios",
                     date=datetime(2025, 4, 1, tzinfo=UTC),
                     metadata_={"date_source": "source", "source_headline": "Santander gana 12.000M en 2024"}))
    db.commit()
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", question="¿Quién es el CEO de Santander?", ticker="SAN.MC")))
    assert response.status == "insufficient_data"
    assert response.citations == []


def test_question_about_registered_us_ticker_uses_its_evidence(db):
    """Ticker US sin punto pero registrado («AAPL»): tambien reencuadra; la
    evidencia citada es la de AAPL, no la del ticker de contexto."""
    tenant, san = setup(db)
    aapl = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
                   company_type="holding", valuation_model="unassigned")
    db.add(aapl)
    db.flush()
    doc = Document(tenant_id=tenant.id, company_id=aapl.id, title="Apple 10-K 2024",
                   source_type="company_ir", source_url="https://www.apple.com/10k.pdf",
                   published_at=datetime(2025, 3, 1, tzinfo=UTC))
    db.add(doc)
    db.flush()
    db.add(FinancialFact(tenant_id=tenant.id, company_id=aapl.id, metric="revenue",
                         value=Decimal("391000"), unit="USD", period="FY2024", fiscal_year=2024,
                         source_id=doc.id, source_type="company_ir", is_reported=True))
    db.commit()
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", question="¿Qué ingresos tuvo AAPL?", ticker="SAN.MC")))
    assert response.status == "answered"
    assert len(response.citations) == 1
    assert response.citations[0].source == "Apple 10-K 2024"


def test_common_word_unregistered_is_not_a_ticker(db):
    """Palabra en mayusculas sin registrar y sin punto («CEO», «PER»): no es un
    cambio de ticker; el contexto sigue siendo el de la empresa seleccionada."""
    from app.services.research_assistant_service import _foreign_ticker

    setup(db)
    assert _foreign_ticker(db, "¿Quién es el CEO?", "SAN.MC") is None
    assert _foreign_ticker(db, "¿Cuál es el PER de SAN.MC?", "SAN.MC") is None
    assert _foreign_ticker(db, "¿Qué ingresos tuvo AAPL?", "SAN.MC") is None  # no registrada
