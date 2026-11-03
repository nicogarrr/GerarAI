"""Chat: una respuesta buena del modelo ya no se tira por escribir las cifras en millones.

Prueba real 2026-11-03 (cerebro-real-2, OpenCode Go): en TODAS las preguntas
sobre una empresa («¿Qué riesgos tiene Uber?», «¿Debería comprar más Uber?»…)
DeepSeek contestaba bien, pero escribía «51.200 millones de dólares» y el
dato guardado es 51200000000 (la respuesta de datos dice «51,2 mil
millones»). El control de cifras inventadas comparaba el texto de los
números, veía «51.200» como cifra que no está en el contexto y tiraba la
respuesta entera: salía el volcado de datos («Datos almacenados: …»). Ahora
compara el valor, con los mismos cambios de escala y redondeo que ya acepta
el validador del equipo de expertos. Una cifra que no está en el contexto
(ni reescalada) se sigue rechazando.
"""

import pytest

from app.schemas.api import ChatResponse, SynthesisSection
from app.services.chat_synthesis_service import _reject_untrusted_output

BASELINE = ChatResponse(
    answer="",
    sections=[
        SynthesisSection(
            key="facts",
            body=(
                "Datos almacenados: ingresos 51,2 mil millones USD (ejercicio 2025, SEC); flujo de caja libre "
                "8,6 mil millones USD (ejercicio 2025, SEC); beneficio neto 7,1 mil millones USD (ejercicio "
                "2025, SEC); deuda total 10,5 mil millones USD (ejercicio 2025, SEC)."
            ),
            citations=["financial_fact:8"],
        )
    ],
    sources=[
        {"type": "financial_fact", "id": "financial_fact:8", "metric": "revenue", "value": "51200000000.000000",
         "source_id": "10-K-2025", "fiscal_year": 2025},
        {"type": "financial_fact", "id": "financial_fact:9", "metric": "free_cash_flow", "value": "8600000000"},
        {"type": "financial_fact", "id": "financial_fact:10", "metric": "net_income", "value": "7100000000"},
        {"type": "financial_fact", "id": "financial_fact:12", "metric": "total_debt", "value": "10500000000"},
        {"type": "financial_fact", "id": "financial_fact:13", "metric": "operating_income", "value": "5234567890"},
    ],
    prompt_version="t",
    model="deterministic",
    confidence=0.5,
)

# Respuesta real de DeepSeek v4.1 Flash (3 nov 2026) a «¿Qué riesgos tiene Uber?».
REAL_ANSWER = (
    "Con lo que tengo, los riesgos que puedo señalarte son sobre todo competitivos: según las noticias "
    "recuperadas, Waymo amplía su servicio de robotaxis en Austin y Atlanta como competidor directo de Uber. "
    "La parte financiera del ejercicio 2025, según los datos regulatorios presentados ante la SEC, muestra "
    "ingresos de 51.200 millones de dólares, beneficio neto de 7.100 millones, flujo de caja libre de 8.600 "
    "millones y deuda total de 10.500 millones, así que el apalancamiento no parece el punto débil. Lo que "
    "falta es lo importante para un análisis de riesgo completo: no tengo el detalle de factores de riesgo "
    "del 10-K ni datos de flujo de caja operativo, deuda neta y caja."
)


def _payload(answer):
    return {"answer": answer, "sections": [{"key": "facts", "body": "Cifras del ejercicio 2025.", "citations": []}]}


@pytest.mark.parametrize(
    "answer",
    [
        REAL_ANSWER,
        "Ingresos de 51.200 M USD y deuda de 10.500 M USD en 2025.",
        "Revenue was $51,200 million in 2025, debt $10.5 billion.",
        "Ingresos de 51.200.000.000 USD.",
        "Resultado operativo de unos 5.235 millones (5,2 mil millones).",
    ],
)
def test_rescaled_figures_from_the_context_are_grounded(answer):
    _reject_untrusted_output(_payload(answer), BASELINE, "¿Qué riesgos tiene Uber?")


@pytest.mark.parametrize(
    "answer",
    [
        "Ingresos de 62.300 millones de dólares en 2025.",
        "El precio objetivo es 145 dólares.",
        "Deuda total de 13.700 millones.",
    ],
)
def test_figures_not_in_the_context_are_still_rejected(answer):
    with pytest.raises(ValueError, match="Ungrounded number"):
        _reject_untrusted_output(_payload(answer), BASELINE, "¿Qué riesgos tiene Uber?")
