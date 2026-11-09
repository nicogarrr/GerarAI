"""Refuerzo del filtro de mención por frase en extract (hueco de mutante señalado por el auditor).

El mutante que elimina la guarda ``if not own and not _mentions(s, terms): continue`` deja pasar a
una nota de agencia (wire) las frases con término de catalizador que no nombran a la empresa: su
texto y sus importes se cuelan en el resumen. Aquí se aserta la exclusión explícita de la frase
ajena (texto e importe), no solo el contenido de la frase propia.
"""

from datetime import date
from types import SimpleNamespace

from app.services import official_catalysts as oc

ASTS = SimpleNamespace(name="AST SpaceMobile, Inc.", ticker="ASTS", ir_url=None)


def test_wire_excluye_texto_e_importe_de_la_frase_que_no_nombra_a_la_empresa():
    terms = oc.company_terms(ASTS)
    ajena = "Rakuten announced an agreement worth $900 million with a supplier yesterday morning."
    propia = "AST SpaceMobile signed a contract worth $43 million with the Agency."
    [c] = oc.extract(
        ajena + " " + propia,
        terms=terms,
        published=date(2026, 1, 2),
        url="https://www.businesswire.com/x",
        publisher="www.businesswire.com",
        source_kind="wire",
    )
    assert c.summary == propia  # la frase ajena no abre ni acompaña el resumen
    assert "$900 million" not in c.amounts  # ni su importe contamina la lista
    assert c.amount_for_company == "$43 million"


def test_wire_solo_frase_ajena_no_produce_catalizador():
    terms = oc.company_terms(ASTS)
    ajena = "Rakuten announced an agreement worth $900 million with a supplier yesterday morning."
    assert (
        oc.extract(
            ajena,
            terms=terms,
            published=date(2026, 1, 2),
            url="https://www.businesswire.com/x",
            publisher="www.businesswire.com",
            source_kind="wire",
        )
        == []
    )
