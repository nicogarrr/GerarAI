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


@pytest.mark.parametrize(
    "question,expected",
    [
        # Regresion c31b (17-nov-2026): el saludo de QA trataba «QA» como ticker.
        (
            "Hola, ¿qué tal? Soy una prueba sintética de QA en Audit. "
            "Contesta en español, sin datos de otras cuentas.",
            [],
        ),
        ("Esto es una prueba de QA", []),
        ("OK, gracias", []),
        ("Tengo una duda sobre la IA en EE.UU.", []),
        ("EL mercado sube", []),
        ("Revisa la UI y el UX", []),
        # Con contexto de empresa, un ticker corto desconocido sigue avisando.
        ("¿qué opinas de ZM?", ["ZM"]),
        ("¿Qué opina la carta de Numantia sobre AST SpaceMobile?", ["AST"]),
        ("háblame sobre ZM", ["ZM"]),
        ("¿qué opinas de ZM? ¿y qué opinas de ZM?", ["ZM"]),  # repetido: una sola vez
        ("precio de ZM", ["ZM"]),
        ("¿cuánto vale $ZM?", ["ZM"]),
        ("acciones de ZM", ["ZM"]),
        ("ticker ZM", ["ZM"]),
        ("¿Está barata PLTR?", ["PLTR"]),
        ("hola, ¿qué opinas de XYZQ?", ["XYZQ"]),
        ("tesis de ZZ.L", ["ZZ.L"]),
        ("¿qué opinas de KO?", []),
        # Distintivo de la regla de contexto: sin cue de empresa, 1-3 letras no avisan...
        ("ZM sube un 5%", []),
        ("Hoy ZM y XY se mueven", []),
        # ...y con cue si (espejo del anterior).
        ("¿qué opinas de ZM?", ["ZM"]),
        # Distintivo de las siglas: aunque haya cue, una sigla conocida no es ticker.
        ("¿qué opinas de QA?", []),
        ("precio de UI", []),
    ],
)
def test_siglas_y_palabras_cortas_no_son_tickers(question, expected):
    assert unknown_ticker_mentions(question, KNOWN + ["KO"]) == expected


def test_respuesta_sugiere_parecido_y_no_inventa():
    answer = unknown_ticker_answer(["TSLAA"], KNOWN)
    assert "No tengo «TSLAA» entre las empresas de GerarAI" in answer
    assert "¿quizá TSLA en vez de TSLAA?" in answer
    assert "/research/TSLAA" in answer


def test_nombre_de_empresa_conocida_se_ignora_por_tramo():
    question = "¿Qué opina la carta de Numantia sobre AST SpaceMobile?"
    start = question.index("AST")
    assert unknown_ticker_mentions(question, ["ASTS"], ignore_spans=[(start, start + 3)]) == []
    # un tramo que no cubre el token no lo oculta
    assert unknown_ticker_mentions(question, ["ASTS"], ignore_spans=[(0, 5)]) == ["AST"]


def test_sin_minusculas_no_hay_menciones():
    assert unknown_ticker_mentions("", KNOWN) == []
    assert unknown_ticker_mentions(None, KNOWN) == []


def test_respuesta_varios_tickers_en_plural_y_uno_con_parecido():
    answer = unknown_ticker_answer(["TSLAA", "QQQQ"], KNOWN)
    assert "«TSLAA», «QQQQ»" in answer and "puedo opinar sobre ellos" in answer
    assert "¿quizá TSLA en vez de TSLAA?" in answer and "QQQQ?" not in answer


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
