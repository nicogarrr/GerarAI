"""Equipo de expertos: cifras legibles y sin nombres de campos internos.

Prueba real 2026-11-03 (cerebro-real-2, OpenCode Go, equipo encendido en
local): los expertos copiaban los datos en crudo («Los ingresos pasaron de
43978000000 a 51200000000», «de 43,978,000,000 a 51,200,000,000», «precio
actual de 69.0») y el de valoración explicaba «publishable=false porque falta
el input net_debt». El contrato de salida que reciben todos los expertos pide
ahora importes en millones con su moneda y formato del idioma, y decir con
palabras lo que falta. El validador de citas ya acepta esos cambios de escala
(«51.200 millones» ↔ 51200000000).
"""

import pytest

from app.services.expert_team.experts import OUTPUT_CONTRACT


def test_spanish_contract_asks_for_readable_figures_and_plain_words():
    text = OUTPUT_CONTRACT["es"]
    assert "51.200 millones" in text and "51200000000" in text
    assert "moneda" in text
    assert "publishable" in text and "net_debt" in text  # como ejemplos de lo que NO se escribe


def test_english_contract_asks_for_readable_figures_and_plain_words():
    text = OUTPUT_CONTRACT["en"]
    assert "51.2 billion" in text and "51200000000" in text
    assert "currency" in text
    assert "publishable" in text and "net_debt" in text


@pytest.mark.parametrize("lang", ["es", "en"])
def test_contract_keeps_the_json_and_citation_rules(lang):
    text = OUTPUT_CONTRACT[lang]
    assert '"claims"' in text and "ev-N" in text
