"""Respuestas generales: aproximadores con contracción y listas numeradas.

Probado con DeepSeek v4.1 real (2 nov 2026): a «¿Qué es el ROIC y por qué
importa para valorar una empresa?» el modelo contestaba bien, pero el chat
enseñaba «No puedo responderte con fuentes ahora mismo; prueba de nuevo…»
porque el validador tomaba como cifras inventadas:
- «alrededor del 15 %» y «en torno al 8 %» (la contracción «del»/«al» no
  contaba como aproximador, «alrededor de 15 %» sí);
- el número de una lista numerada («1. Distingue…»).
Las cifras exactas sin aproximador se siguen rechazando.
"""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.llm import LLMResponse, Message, Usage
from app.models.entities import Base
from app.services.chat_service import ChatService
from app.services.chat_synthesis_service import (
    _inferred_general_text_valid,
    _inferred_general_text_valid_en,
)

ROIC_DEEPSEEK = (
    "El ROIC (retorno sobre el capital invertido) mide cuánto beneficio operativo genera una empresa "
    "por cada euro de capital que emplea.\n\n"
    "Su utilidad al valorar una empresa está en compararlo con el coste de ese capital. Si una compañía "
    "obtiene un ROIC de, por ejemplo, alrededor del 15% y su coste de capital ronda el 8%, cada euro "
    "reinvertido crea valor; si el ROIC se queda por debajo del coste de capital, crecer destruye valor.\n\n"
    "Por qué importa:\n\n"
    "1. **Distingue calidad de negocio.** Una empresa que reinvierte a un ROIC alto crea valor.\n"
    "2. **Se compara con el coste del capital.** El capital no es gratis.\n"
    "3. **Alimenta el crecimiento sostenible.** Un ROIC alto permite crecer con recursos propios."
)


def _valid(text: str) -> bool:
    return _inferred_general_text_valid(text, quantitative=True)


def _valid_en(text: str) -> bool:
    return _inferred_general_text_valid_en(text, quantitative=True)


def test_alrededor_del_y_en_torno_al_cuentan_como_aproximador():
    assert _valid("Un ROIC alrededor del 15% suele indicar un buen negocio.")
    assert _valid("El coste de capital suele estar en torno al 8% en empresas grandes.")
    assert _valid("Un margen por encima del 20% es raro en distribución.")
    assert _valid("Una deuda por debajo del 10% del activo es prudente.")
    assert _valid("Si el ROIC baja a menos del 5% conviene revisar la tesis.")
    # Las formas sin contracción ya valían y siguen valiendo.
    assert _valid("Un ROIC alrededor de 15% suele indicar un buen negocio.")


def test_cifra_exacta_sin_aproximador_se_sigue_rechazando():
    assert not _valid("Apple tiene un ROIC del 15%.")
    assert not _valid("El coste de capital de la empresa es el 8%.")


def test_lista_numerada_no_cuenta_como_cifra():
    assert _valid(
        "Las claves:\n\n1. Mide la calidad del negocio.\n2. Se compara con el coste del capital.\n3) Ayuda a valorar el crecimiento."
    )
    assert _valid_en(
        "Key points:\n\n1. It measures business quality.\n2. It is compared with the cost of capital."
    )
    # Una cifra dentro del punto de la lista sigue necesitando aproximador.
    assert not _valid("1. El ROIC de Apple es del 15%.")
    assert not _valid_en("1. Apple's ROIC is 15%.")


class _Stub:
    name = "stub"

    def __init__(self, text: str):
        self.text = text

    async def complete(self, request):
        return LLMResponse(
            message=Message("assistant", self.text),
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
            model="stub-model",
            provider="stub",
            request_id="req-1",
        )


def test_respuesta_de_concepto_real_se_ensena_entera():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = "tenant-test"
    response = asyncio.run(
        ChatService(_Stub(ROIC_DEEPSEEK)).answer(
            db, "¿Qué es el ROIC y por qué importa para valorar una empresa?", "portfolio", None
        )
    )
    assert "No puedo responderte con fuentes" not in response.answer
    assert "alrededor del 15%" in response.answer
    assert "1. **Distingue calidad de negocio.**" in response.answer
