"""El chat de empresa lee las notas, informes y tesis propias etiquetadas con su ticker."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, KnowledgeChunk, KnowledgeDocument
from app.models.entities import Base
from app.services import chat_service
from app.services.chat_service import ChatService
from app.services.library_context import company_library_context

NOTE = "Mi regla con ASTS: si la dilución anual supera el 15% vendo la mitad de la posición."
OTHER = "Nota sobre RKLB: Neutron es el riesgo principal del plan."


def _company(session: Session, ticker: str, name: str) -> Company:
    company = Company(
        ticker=ticker,
        name=name,
        exchange="NASDAQ",
        currency="USD",
        sector="x",
        industry="x",
        company_type="operating",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.flush()
    return company


def _note(session: Session, tenant: int, ticker: str, text: str) -> None:
    doc = KnowledgeDocument(
        tenant_id=tenant,
        title=f"Nota {ticker}",
        author=None,
        document_type="personal_note",
        status="ready",
        ticker=ticker,
    )
    session.add(doc)
    session.flush()
    session.add(
        KnowledgeChunk(
            tenant_id=tenant,
            knowledge_document_id=doc.id,
            chunk_index=0,
            content=text,
            page_number=1,
        )
    )


@pytest.fixture()
def db():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    _company(session, "ASTS", "AST SpaceMobile, Inc.")
    _company(session, "RKLB", "Rocket Lab Corporation")
    _note(session, 1, "ASTS", NOTE)
    _note(session, 1, "RKLB", OTHER)
    _note(session, 2, "ASTS", "Nota de OTRO usuario: la dilución no importa.")
    session.commit()
    session.info["tenant_id"] = 1
    return session


def test_nota_propia_de_la_empresa(db):
    asts = db.query(Company).filter_by(ticker="ASTS").one()
    rows = company_library_context(db, asts, "¿Qué apunté sobre el riesgo de dilución?")
    assert [r["text"] for r in rows] == [NOTE]
    assert rows[0]["evidence_role"] == "user_document_about_company_not_official"


def test_no_mezcla_empresas_ni_usuarios(db):
    asts = db.query(Company).filter_by(ticker="ASTS").one()
    texts = " ".join(r["text"] for r in company_library_context(db, asts, "¿Qué dicen mis notas?"))
    assert "Neutron" not in texts
    assert "OTRO usuario" not in texts


def test_sin_coincidencia_ni_pista_de_nota_no_trae_nada(db):
    asts = db.query(Company).filter_by(ticker="ASTS").one()
    assert company_library_context(db, asts, "¿Cuál es el precio de ASTS?") == []


def test_el_chat_de_empresa_pasa_la_nota_al_modelo(db, monkeypatch):
    # Evidencia que recibe el modelo, antes de podar lo no citado.
    monkeypatch.setattr(chat_service, "_prune_sources", lambda sources, *a, **k: sources)
    response = ChatService(provider=object())._deterministic_answer(  # type: ignore[arg-type]
        db, "¿Qué apunté en mis notas sobre el riesgo de dilución?", "company", "ASTS"
    )
    own = [s for s in response.sources if s.get("type") == "knowledge_chunk"]
    assert own and NOTE in str(own[0].get("text"))
    inferences = next(s for s in response.sections if s.key == "inferences")
    assert f"knowledge_chunk:{own[0]['id']}" in inferences.citations
    assert "no es un dato oficial" in inferences.body
