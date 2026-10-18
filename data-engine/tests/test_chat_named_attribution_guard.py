"""Sin doctrina recuperada, no se pone prosa en boca de inversores famosos (canarios en ambos sentidos)."""

import pytest

from app.services.chat_synthesis_service import _inferred_general_text_valid

REJECT = [
    # Texto real devuelto por Groq en la verificacion en vivo del 2026-10-17 (sin doctrina en contexto).
    "Warren\u202fBuffett ha reiterado en varias ocasiones que el concepto de “margen de seguridad” es fundamental para la inversión de valor.",
    "Buffett enfatiza que el margen de seguridad no es una cifra exacta, sino una medida cualitativa.",
    "En términos generales, él lo describe como la diferencia entre el precio y el valor. Buffett subraya la calidad del negocio.",
    "Munger señaló que conviene evitar el apalancamiento excesivo.",
    "Graham sostiene que el inversor debe exigir un colchón frente al error.",
    "Para Buffett el margen es clave. Él lo describe como un colchón.",
    "Howard Marks explica que el riesgo no es la volatilidad.",
    "Buffett ha dicho que prefiere negocios simples.",
]
ACCEPT = [
    "El margen de seguridad es la diferencia entre el precio pagado y el valor intrínseco estimado. No tengo un fragmento concreto de un autor para atribuírselo.",
    "Un colchón amplio protege frente a errores de cálculo; no es una cifra exacta.",
    "Berkshire Hathaway es la empresa que dirige Buffett.",
    "El inversor describe sus riesgos con calma.",
]


@pytest.mark.parametrize("text", REJECT)
def test_unsourced_named_attribution_is_rejected(text):
    assert not _inferred_general_text_valid(text)


@pytest.mark.parametrize("text", ACCEPT)
def test_general_text_without_attribution_is_accepted(text):
    assert _inferred_general_text_valid(text)


@pytest.mark.parametrize("text", REJECT[:3])
def test_attribution_allowed_when_doctrine_of_that_author_is_in_context(text):
    # Doctrina DEL autor nombrado (su apellido sirve): la atribucion es valida.
    assert _inferred_general_text_valid(
        text, allow_named_attribution=True, allowed_investors=frozenset({"buffett"}),
    )


@pytest.mark.parametrize("text", REJECT[:3])
def test_attribution_rejected_when_doctrine_is_from_another_author(text):
    # Doctrina de OTRO autor (p. ej. cartas de un fondo): "segun Buffett"
    # sigue siendo una atribucion sin fuente de ese autor.
    assert not _inferred_general_text_valid(
        text, allow_named_attribution=True, allowed_investors=frozenset({"marks"}),
    )
