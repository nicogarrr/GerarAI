"""Una cifra literal de la carta recuperada no tumba la respuesta de doctrina."""

from app.services.chat_synthesis_service import _inferred_general_text_valid, grounded_numbers_in

CARTA = (
    "Rentabilidades desde 02/07/2017: Numantia acumula un +202%, un 13,6% anual compuesto neto de comisiones."
)
RESPUESTA = (
    "En la carta de 2025, Numantia acumulaba un +202% desde su inicio en julio de 2017, "
    "un 13,6% anual compuesto después de comisiones."
)


def _valid(text: str, numbers: frozenset[str]) -> bool:
    return _inferred_general_text_valid(
        text,
        quantitative=True,
        allow_named_attribution=True,
        grounded_numbers=numbers,
    )


def test_cifras_de_la_carta_se_aceptan():
    assert _valid(RESPUESTA, grounded_numbers_in([CARTA]))


def test_sin_la_carta_sigue_exigiendo_aproximador():
    # Mismo texto sin doctrina en contexto: la cifra no tiene respaldo.
    assert not _valid(RESPUESTA, frozenset())


def test_una_cifra_inventada_junto_a_las_de_la_carta_se_rechaza():
    inventada = RESPUESTA + " Este año lleva un 31% de subida."
    assert not _valid(inventada, grounded_numbers_in([CARTA]))


def test_formato_de_cifra_indiferente():
    numbers = grounded_numbers_in(["El float paso de 1.632 millones a 2.000 millones; 13.6% anual."])
    assert "13.6" in numbers
    assert "1.632" in numbers
    # Un digito suelto no legitima nada.
    assert "3" not in grounded_numbers_in(["capitulo 3"])
