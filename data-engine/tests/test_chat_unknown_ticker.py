"""El Cerebro no inventa sobre tickers que GerarAI no tiene.

Prueba real 2026-10-27: «¿qué opinas de TSLAA?» → «TSLAA es un ticker que suele
asociarse con Tesla en su versión de acciones preferentes…» (inventado).
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.chat_service import ChatService
from app.services.chat_unknown_ticker import unknown_ticker_answer, unknown_ticker_mentions

KNOWN = ["TSLA", "UBER", "KKR", "CGEO.L", "BN"]


@pytest.mark.parametrize(
    "question,expected",
    [
        ("¿qué opinas de TSLAA?", ["TSLAA"]),
        ("compara UBER y XYZQ", ["XYZQ"]),
        ("tesis de FOO.L", ["FOO.L"]),
        ("compara UBER y KKR", []),
        ("¿qué PER y ROE tiene UBER?", []),
        ("¿cómo va mi cartera en EUR y USD?", []),
        ("QUÉ OPINAS DE TSLAA", []),  # todo en mayúsculas: no se adivina
        ("¿qué es el DCF y el WACC?", []),
        ("tesis de CGEO.L", []),
    ],
)
def test_menciones_desconocidas(question, expected):
    assert unknown_ticker_mentions(question, KNOWN) == expected


def test_respuesta_sugiere_parecido_y_no_inventa():
    answer = unknown_ticker_answer(["TSLAA"], KNOWN)
    assert "No tengo «TSLAA» entre las empresas de GerarAI" in answer
    assert "¿quizá TSLA en vez de TSLAA?" in answer
    assert "/research/TSLAA" in answer


class _BoomProvider:
    """Si el chat llama al LLM, el test falla: la respuesta debe ser determinista."""

    name = "boom"

    async def generate(self, *args, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("el LLM no debe contestar sobre un ticker inexistente")

    async def chat(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("el LLM no debe contestar sobre un ticker inexistente")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        session.add(
            Company(
                ticker="TSLA", name="Tesla", exchange="NASDAQ", currency="USD", sector="Auto",
                industry="Auto", company_type="standard", valuation_model="standard_dcf",
                special_sources=[], special_risks=[], factor_tags=[],
            )
        )
        session.commit()
        yield session


def test_chat_ticker_inexistente_no_pasa_por_el_llm(db):
    service = ChatService(provider=_BoomProvider())  # type: ignore[arg-type]
    response = asyncio.run(service._answer_impl(db, "¿qué opinas de TSLAA?", "portfolio", None))
    assert "No tengo «TSLAA»" in response.answer
    assert "preferentes" not in response.answer
    assert response.llm_trace and response.llm_trace.get("path") == "unknown_ticker"
