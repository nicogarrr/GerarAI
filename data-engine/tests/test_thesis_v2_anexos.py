"""Los nombres de anexos de la SEC («EX-99.1», «EX-13») son nombres de documento, no cifras.

Antes, la tesis de BN citaba «(BN 6-K EX-99.1 2026-10-16)»: el detector contaba «-99.1» como número
libre y el recorte lo dejaba en «EX2026-10-16», una cita rota que luego volvía a contar como cifra.
"""
from app.services.expert_team import thesis_v2 as T


def test_anexo_sec_no_es_numero_libre():
    assert T.loose_numbers("Según el comunicado (BN 6-K EX-99.1 2026-10-16), la compañía") == []
    assert T.loose_numbers("el anexo EX-13 del 10-K y el EX-99 del 8-K") == []


def test_recorte_no_rompe_el_nombre_del_anexo():
    texto = "Según el comunicado (BN 6-K EX-99.1 2026-10-16), la compañía"
    assert T.strip_loose(texto) == texto
    assert "EX-13" in T.strip_loose("el anexo EX-13 del 10-K")


def test_una_cifra_al_lado_del_anexo_sigue_contando():
    assert T.loose_numbers("el EX-99.1 dice que vendió 450 unidades") == ["450"]
