"""La fuente de doctrina se muestra aunque el autor lleve parentesis."""
import asyncio

from app.llm import LLMResponse, Message, Usage
from app.schemas import ChatResponse
from app.services.chat_synthesis_service import ChatSynthesisService


class Stub:
    name = "stub"

    async def complete(self, request):
        return LLMResponse(
            message=Message("assistant", "En las cartas de Numantia la paciencia es clave para el largo plazo."),
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
            model="stub-model", provider="stub", request_id="r",
        )


def test_author_with_parentheses_is_listed_as_source():
    baseline = ChatResponse(answer="", sources=[{
        "type": "knowledge_chunk", "id": 1, "title": "Numantia Patrimonio - Carta 2020",
        "author": "Emérito Quintana (Numantia Patrimonio)", "year": 2020, "page_number": 3,
        "text": "La paciencia es una cualidad esencial.", "url": "https://example.org/carta",
    }], model="x", prompt_version="x", confidence=0.5)
    out = asyncio.run(ChatSynthesisService(Stub()).synthesize_general(
        question="¿Qué dicen las cartas de Numantia sobre la paciencia?", baseline=baseline, db=None, history=None, page=None))
    assert out.model == "stub-model"
    assert [s["id"] for s in out.sources] == [1]
    assert out.sources[0]["url"] == "https://example.org/carta"
