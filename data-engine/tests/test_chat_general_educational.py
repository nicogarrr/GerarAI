"""Respuestas educativas del chat general que caían al degradado (prueba real 2026-11-03).

Con el Go de Nico, 8 de 8 preguntas de concepto («Explícame qué es el PER»,
«¿qué es el ROIC?», «¿de golpe o poco a poco?») recibían una respuesta
correcta del modelo que el validador tiraba: «No puedo responderte con
fuentes ahora mismo». Las causas, una por una: recuentos («dos formas», «la
regla de los dos meses»), ejemplos («un PER de 15», «si había 100
acciones»), «según el sector» (dependiendo de), «por encima de un 15 %»,
«4 o 5 veces», «cercano al 30 %», el «× 100» de una fórmula y «las empresas
de su cartera» hablando de un ETF. Lo que sigue protegido: cifras con dinero
o escala sin aproximador, fuentes inventadas y la cartera del usuario.
"""

import pytest

from app.services.chat_synthesis_service import _general_text_rejection

ACCEPTED = [
    "Qué te dice: cuántos años de beneficios harían falta. Un PER de 15 implica que pagas unas 15 veces el beneficio anual.",
    "Buena pregunta, porque son dos formas distintas de devolver dinero al accionista.",
    "No te llega dinero, pero tu trozo crece: si había 100 acciones y se amortizan 10, pasa de 1/100 a 1/90.",
    "El margen de seguridad se expresa en porcentaje: (valor intrínseco − precio) / valor intrínseco × 100. "
    "Si estimas que vale unos 100 y cotiza alrededor de 70, el margen sería cercano al 30 %.",
    "Un ETF de acumulación reinvierte los dividendos de las empresas de su cartera en lugar de repartirlos.",
    "La regla de los dos meses impide computar una pérdida si recompras valores homogéneos.",
    "No hay un número universal, pero sí referencias útiles según el ratio y el sector. "
    "Por encima de unas 4 o 5 veces el margen se estrecha mucho.",
    "La ventaja histórica no es enorme, con mucha dispersión según el periodo que mires.",
    "Si estimas que vale unos 100 y cotiza a unos 70, el margen ronda el 30 %. Si cotiza a 60, cerca del 40 %.",
    "En negocios más volátiles, algunos inversores piden un 40-50% o más.",
    "Un ROIC alto y sostenido (pongamos por encima de un 15% durante años) suele indicar ventajas competitivas.",
]

REJECTED = [
    ("Apple ganó 100.000 millones de dólares el año pasado.", "cifra exacta sin aproximador"),
    ("Por ejemplo, Apple gana 95.000 millones al año.", "cifra exacta sin aproximador"),
    ("Tiene un beneficio de 25 millones.", "cifra exacta sin aproximador"),
    ("Su margen operativo es del 40%.", "cifra exacta sin aproximador"),
    ("Su deuda es de dos millones de euros.", "cifra exacta sin aproximador"),
    ("Según Bloomberg, la acción subirá.", "«según» sin fuente dada"),
    ("Según el informe anual, la empresa crece.", "atribución a una fuente oficial no dada"),
    ("Tu cartera está demasiado concentrada en tecnología.", "afirmación sobre la cartera del usuario"),
    ("Su cartera está concentrada en tecnología.", "afirmación sobre la cartera del usuario"),
]


@pytest.mark.parametrize("text", ACCEPTED)
def test_correct_educational_answers_are_accepted(text):
    assert _general_text_rejection(text) is None


@pytest.mark.parametrize(("text", "why"), REJECTED)
def test_invented_figures_sources_and_portfolio_claims_still_rejected(text, why):
    assert (_general_text_rejection(text) or "").startswith(why)
