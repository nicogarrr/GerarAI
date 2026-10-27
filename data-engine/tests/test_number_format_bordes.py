"""Bordes del formato compacto es-ES (fase 2 de la auditoría de fórmulas).

Fuente: ECMA-402 ``Intl.NumberFormat`` con ``notation: "compact"``: la escala
se decide sobre la cifra ya redondeada, y un negativo que redondea a cero se
muestra sin signo.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.services.number_format import format_compact_es, format_number_es


def test_999_999_999_es_1_mil_millones_no_1000_millones():
    """A mano: 999.999.999/1e6 = 999,999999 → a 2 decimales 1.000,00 M, que
    es 1 mil M. Antes salía «1.000 M»."""
    assert format_compact_es(999_999_999) == "1 mil M"
    assert format_compact_es(-999_999_999) == "-1 mil M"
    assert format_compact_es(999_995_000) == "1 mil M"
    # Justo por debajo del redondeo se queda en millones.
    assert format_compact_es(999_994_999) == "999,99 M"


def test_999_999_999_9_es_1_millon():
    """A mano: 999.999,999 redondea a 1.000.000,00 → «1 M»."""
    assert format_compact_es(Decimal("999999.999")) == "1 M"
    assert format_compact_es(999_999) == "999.999"


def test_negativo_que_redondea_a_cero_no_lleva_signo():
    """-0,001 a 2 decimales es 0: «0», no «-0»."""
    assert format_number_es(-0.001) == "0"
    assert format_number_es(Decimal("-0.004")) == "0"
    assert format_compact_es(-0.001) == "0"
    assert format_number_es(-0.006) == "-0,01"
    assert format_number_es(-12.5) == "-12,5"


@pytest.mark.parametrize("seed", range(200))
def test_la_escala_nunca_muestra_1000_de_la_escala_inferior(seed):
    """Propiedad: ninguna cifra compacta empieza por «1.000 » en M (eso es
    1 mil M), y el número sin escala nunca llega a 1.000.000."""
    rng = random.Random(seed)
    value = Decimal(repr(rng.uniform(0.9, 1.1))) * Decimal(10) ** rng.choice([6, 9])
    text = format_compact_es(value)
    assert text is not None
    assert not text.startswith("1.000 M")
    assert not text.startswith("1.000.000")
