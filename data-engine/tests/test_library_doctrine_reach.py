"""La doctrina de la biblioteca llega al Cerebro sin palabras clave ("cartas", "Buffett")."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company
from app.models.entities import Base, KnowledgeChunk, KnowledgeDocument
from app.services import chat_service
from app.services.chat_service import ChatService
from app.services.library_context import retrieve_library_context

PAD = "Texto de relleno sobre la gestion del fondo y su historia. " * 30
SAFETY = (
    "Buscar margen de seguridad es, en el fondo, reconocer que eres un ignorante "
    "sobre el futuro: pagas bastante menos de lo que vale el negocio."
)
RETURNS = "Rentabilidad desde su inicio en julio de 2017: el fondo acumula un +202%, un 13,6% anual."
BROOKFIELD = "Brookfield tiene contratos a largo plazo indexados a la inflacion: por eso es estable."


@pytest.fixture()
def db():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    session.info["tenant_id"] = 1
    session.add(
        Company(
            ticker="BN",
            name="Brookfield Corporation",
            exchange="NYSE",
            currency="USD",
            sector="x",
            industry="x",
            company_type="operating",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
    )
    doc = KnowledgeDocument(
        tenant_id=1,
        title="Numantia Patrimonio - Carta 2025",
        author="Numantia Patrimonio",
        document_type="fund_letter",
        status="ready",
    )
    session.add(doc)
    session.flush()
    for index, text in enumerate([PAD + SAFETY + " " + PAD, PAD + RETURNS, BROOKFIELD + " " + PAD, PAD]):
        session.add(
            KnowledgeChunk(
                tenant_id=1,
                knowledge_document_id=doc.id,
                chunk_index=index,
                content=text,
                page_number=1,
            )
        )
    session.commit()
    return session


def test_concepto_sin_palabra_clave(db):
    rows = retrieve_library_context(db, "¿Qué es el margen de seguridad?", vector=False)
    assert rows
    # La ventana enviada contiene el pasaje, no los primeros 600 caracteres de relleno.
    assert "margen de seguridad" in rows[0]["text"]
    assert len(rows[0]["text"]) <= 610


def test_ticker_se_traduce_a_la_empresa(db):
    rows = retrieve_library_context(db, "¿Por qué es estable BN?", vector=False)
    assert rows and "Brookfield" in rows[0]["text"]


@pytest.mark.parametrize(
    "question", ["hola", "gracias", "gracias Juan", "¿Cómo está mi cartera hoy?", "¿Qué es el PER?"]
)
def test_charla_no_trae_doctrina(db, question):
    assert retrieve_library_context(db, question, vector=False) == []


def test_pregunta_general_sin_empresa_lleva_doctrina_al_chat(db, monkeypatch):
    # Antes hacia falta escribir "cartas" o "Buffett" para que se buscara.
    # Se mira la evidencia que recibe el modelo (antes de podar lo no citado).
    monkeypatch.setattr(chat_service, "_prune_sources", lambda sources, *a, **k: sources)
    response = ChatService(provider=object())._deterministic_answer(  # type: ignore[arg-type]
        db, "¿Cuánto ha rentado Numantia desde su inicio?", "portfolio", None
    )
    doctrine = [s for s in response.sources if s.get("type") == "knowledge_chunk"]
    assert any("+202%" in str(s.get("text")) for s in doctrine), response.sources
