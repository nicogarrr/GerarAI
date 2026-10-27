"""Rutas del Cerebro que cortaban preguntas a la biblioteca o leían nombres como tickers.

Evaluación real del RAG (2026-10-27, casos N2, N3, K3 y M1):
- «¿Cómo reparte Numantia la cartera…?» y «¿Qué empresas de mi cartera menciona
  Numantia en su carta…?» acababan en el contexto personal («Watchlist vacía»)
  sin llegar a la biblioteca.
- «¿Qué opina la carta de Numantia sobre AST SpaceMobile?» y «¿Qué tengo
  apuntado sobre AST SpaceMobile?» acababan en «No tengo «AST» entre las
  empresas de GerarAI»: la primera palabra del nombre se leía como ticker.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company
from app.models.entities import Base, KnowledgeChunk, KnowledgeDocument
from app.services import chat_service
from app.services.chat_service import ChatService
from app.services.chat_unknown_ticker import unknown_ticker_mentions
from app.services.company_names import companies_named_in

PAD = "Texto de relleno sobre la gestion del fondo y su historia. " * 20
REPARTO = (
    "En la cartera repartimos entre negocios aburridos y estables, que son el grueso, "
    "e ideas con mas riesgo y mucho potencial, que pesan poco."
)


class _LLMReached(Exception):
    pass


class _StubProvider:
    """Cualquier llamada al LLM corta la prueba: basta con saber que la pregunta llegó."""

    name = "stub"

    async def complete(self, *args, **kwargs):
        raise _LLMReached("complete")

    async def generate_json(self, *args, **kwargs):
        raise _LLMReached("generate_json")


def _company(session, ticker, name):
    session.add(Company(
        ticker=ticker, name=name, exchange="NYSE", currency="USD", sector="x", industry="x",
        company_type="operating", valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    ))


@pytest.fixture()
def db():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    session.info["tenant_id"] = 1
    _company(session, "ASTS", "AST SpaceMobile, Inc.")
    _company(session, "ASTL", "Algoma Steel Group Inc.")
    _company(session, "AAPL", "Apple Inc.")
    doc = KnowledgeDocument(
        tenant_id=1, title="Numantia Patrimonio - Carta 2025", author="Numantia Patrimonio",
        document_type="fund_letter", status="ready",
    )
    session.add(doc)
    session.flush()
    session.add(KnowledgeChunk(
        tenant_id=1, knowledge_document_id=doc.id, chunk_index=0, content=PAD + REPARTO + " " + PAD, page_number=1,
    ))
    session.commit()
    return session


@pytest.fixture()
def library_calls(monkeypatch):
    calls: list[int] = []
    original = chat_service.retrieve_library_context

    def spy(db, question, **kwargs):
        rows = original(db, question, **kwargs)
        calls.append(len(rows))
        return rows

    monkeypatch.setattr(chat_service, "retrieve_library_context", spy)
    return calls


def _route(db, question):
    """(path, empresa resuelta) o ("llm", None) si llegó al generador."""
    try:
        resp = asyncio.run(ChatService(provider=_StubProvider()).answer(db, question, "portfolio", None))
    except _LLMReached:
        return "llm", None
    return (resp.llm_trace or {}).get("path"), resp


# ------------------------------------------------------------ nombres

def test_nombre_en_texto_no_es_un_ticker_desconocido():
    named = companies_named_in("¿Qué opina la carta de Numantia sobre AST SpaceMobile?",
                               [Company(id=1, ticker="ASTS", name="AST SpaceMobile, Inc.")])
    assert [c.ticker for c in named.companies] == ["ASTS"]
    question = "¿Qué opina la carta de Numantia sobre AST SpaceMobile?"
    assert unknown_ticker_mentions(question, ["ASTS"]) == ["AST"]  # antes
    assert unknown_ticker_mentions(question, ["ASTS"], ignore_spans=named.spans) == []


def test_nombre_de_una_palabra_solo_con_mayuscula():
    companies = [Company(id=1, ticker="AAPL", name="Apple Inc.")]
    assert [c.ticker for c in companies_named_in("¿Qué opinas de Apple?", companies).companies] == ["AAPL"]
    assert companies_named_in("me gusta la tarta de apple", companies).companies == []


@pytest.mark.parametrize(
    "question,ticker",
    [
        ("¿Qué opinas de AST SpaceMobile?", "ASTS"),
        ("¿Qué tengo apuntado sobre AST SpaceMobile?", "ASTS"),
        ("¿Qué opinas de ast spacemobile?", "ASTS"),
        ("¿Cómo ves Algoma?", "ASTL"),
        ("¿Qué opinas de Apple?", "AAPL"),
    ],
)
def test_el_nombre_resuelve_el_ticker(db, question, ticker):
    company = ChatService(provider=_StubProvider())._resolve_company(db, question, "portfolio", None)
    assert company is not None and company.ticker == ticker
    path, _ = _route(db, question)
    assert path != "unknown_ticker"


def test_nombre_ambiguo_pregunta_cual(db):
    _company(db, "BN", "Brookfield Corporation")
    _company(db, "BAM", "Brookfield Asset Management Ltd.")
    db.commit()
    path, resp = _route(db, "¿Qué opinas de Brookfield?")
    assert path == "company_ambiguous"
    assert "¿te refieres a" in resp.answer
    assert "BN (Brookfield Corporation)" in resp.answer
    assert "BAM (Brookfield Asset Management Ltd.)" in resp.answer


def test_ticker_inexistente_sigue_diciendose(db):
    path, resp = _route(db, "¿Qué opinas de TSLAA?")
    assert path == "unknown_ticker"
    assert "No tengo «TSLAA»" in resp.answer


# --------------------------------------------------------- biblioteca

@pytest.mark.parametrize(
    "question",
    [
        "¿Cómo reparte Numantia la cartera entre negocios aburridos e ideas con más riesgo?",
        "¿Qué empresas de mi cartera o watchlist menciona Numantia en su carta y qué opina de ellas?",
        "¿Qué opina la carta de Numantia sobre AST SpaceMobile?",
        "¿Qué opina Numantia de XYZQ?",
    ],
)
def test_pregunta_a_la_biblioteca_llega_a_la_recuperacion(db, library_calls, question):
    path, _ = _route(db, question)
    assert path not in {"personal_context", "unknown_ticker", "company_ambiguous"}
    assert library_calls, "la pregunta no llegó a la recuperación de la biblioteca"


def test_el_reparto_de_numantia_recupera_el_pasaje(db, library_calls):
    _route(db, "¿Cómo reparte Numantia la cartera entre negocios aburridos e ideas con más riesgo?")
    assert library_calls and library_calls[0] >= 1


@pytest.mark.parametrize("question", ["¿Qué riesgo tengo en mi cartera?", "¿Cómo va mi cartera?"])
def test_preguntas_personales_siguen_en_el_contexto_personal(db, question):
    path, _ = _route(db, question)
    assert path == "personal_context"


@pytest.mark.parametrize("question", [
    "¿Qué riesgo tengo en mi cartera a principios de año?",
    "Para una carta a mi banco, ¿qué riesgo tengo en mi cartera?",
    "Mi filosofía es ahorrar: ¿qué riesgo tengo en mi cartera?",
])
def test_palabras_comunes_no_desvian_la_pregunta_personal(db, library_calls, question):
    path, _ = _route(db, question)
    assert path == "personal_context"
    assert not library_calls


@pytest.mark.parametrize("question", [
    "¿Qué principios aplica la carta de Numantia a mi cartera?",
    "¿Qué dicen las cartas a los accionistas sobre diversificar mi cartera?",
    "¿Qué principios de inversión explican el riesgo de mi cartera?",
    "¿Qué filosofía de inversión explica el riesgo de mi cartera?",
])
def test_doctrina_explicita_aun_consulta_biblioteca(db, library_calls, question):
    path, _ = _route(db, question)
    assert path != "personal_context"
    assert library_calls


@pytest.mark.parametrize("question", [
    "¿Qué opinas de TSLAA a principios de año?",
    "En mi carta al banco, ¿qué opinas de TSLAA?",
])
def test_palabras_comunes_no_ocultan_ticker_desconocido(db, question):
    path, _ = _route(db, question)
    assert path == "unknown_ticker"


@pytest.mark.parametrize("suffix", ["S.A.", "S.L."])
def test_generic_first_word_with_dotted_legal_suffix_resolves(db, suffix):
    _company(db, "SAN", f"Banco Santander, {suffix}")
    db.commit()
    resolved = ChatService(provider=_StubProvider())._resolve_company(
        db, "¿Cómo va Banco Santander?", "portfolio", None,
    )
    assert resolved is not None and resolved.ticker == "SAN"
    path, _ = _route(db, "¿Cómo va Banco Santander?")
    assert path not in {"unknown_ticker", "company_ambiguous", "general"}
