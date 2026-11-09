"""Companies House: limite de saltos de la cadena PSC y controladora homonima del holding.

Dobles minimos sin red (el replay de la API real vive en test_companies_house.py).
Cierra las dos salvedades del lote anterior (PR #5008): (1) un spy (contador de
llamadas por sociedad en el doble) demuestra que con el maximo por defecto el 5o
salto NO se consulta, y (2) la MISMA cadena de 5 saltos si entra al ampliar el
maximo, demostrando que el doble llega al holding. Ademas: una controladora cuyo
nombre coincide con el del holding y tiene numero UK propio entra como raiz del
grupo, y _add_chain no pisa a un miembro ya presente en la cadena.

NO prueba (declarado): la API real, el formato de las respuestas, homonimos que
solo comparten la palabra propia, ni el carril persona-del-holding.
"""

from __future__ import annotations

import asyncio

from app.services import companies_house_evidence as ev


def _psc_uk(nombre: str, registro: str) -> dict:
    return {
        "kind": "corporate-entity-person-with-significant-control",
        "name": nombre,
        "identification": {"country_registered": "ENGLAND",
                           "registration_number": registro},
    }


class _DobleCadena:
    """Holding por nombre exacto (00000001) y una candidata (pista) cuya cadena
    de PSC sube 00000100 -> 00000101 -> ... -> 00000104; el PSC de 00000104
    apunta al holding. Cuenta las consultas de PSC por sociedad (spy)."""

    requests_used = 1

    def __init__(self):
        self.llamadas_psc: dict[str, int] = {}

    async def search_companies(self, query, items=10):
        if ev.normalize_name(query) == ev.normalize_name("Acme Holdings Ltd"):
            return [{"company_number": "00000001", "title": "Acme Holdings Ltd",
                     "company_status": "active"}]
        return [{"company_number": "00000100", "title": "Filial Remota Ltd",
                 "company_status": "active"}]

    async def persons_with_significant_control(self, number):
        self.llamadas_psc[number] = self.llamadas_psc.get(number, 0) + 1
        saltos = {
            "00000100": _psc_uk("Cadena Uno Ltd", "00000101"),
            "00000101": _psc_uk("Cadena Dos Ltd", "00000102"),
            "00000102": _psc_uk("Cadena Tres Ltd", "00000103"),
            "00000103": _psc_uk("Cadena Cuatro Ltd", "00000104"),
            "00000104": _psc_uk("Acme Holdings Ltd", "00000001"),
        }
        return [saltos[number]] if number in saltos else []

    async def officers(self, number):
        return []


def test_quinto_salto_no_se_consulta_con_el_maximo_por_defecto():
    """Con MAX_CHAIN_HOPS=4 la candidata queda sin verificar y el PSC del 5o
    salto (00000104) NUNCA se consulta: el doble lleva la cuenta."""
    doble = _DobleCadena()
    unverified = []
    members, reason = asyncio.run(ev.discover_group(
        doble, holding_name="Acme Holdings Ltd",
        hints=["Filial Remota"], unverified=unverified,
    ))
    assert [m.number for m in members] == ["00000001"]
    assert reason == "ok"
    (descartada,) = unverified
    assert descartada["company_number"] == "00000100"
    assert "más de" in descartada["why"] and "saltos" in descartada["why"]
    assert doble.llamadas_psc.get("00000104", 0) == 0
    for pisada in ("00000100", "00000101", "00000102", "00000103"):
        assert doble.llamadas_psc[pisada] == 1


def test_la_misma_cadena_entra_al_ampliar_el_maximo(monkeypatch):
    """El tope es el unico motivo del descarte: con el maximo ampliado la misma
    cadena llega al holding (registro ya verificado) y la candidata entra al
    grupo con su profundidad real."""
    monkeypatch.setattr(ev, "MAX_CHAIN_HOPS", 6)
    doble = _DobleCadena()
    members, reason = asyncio.run(ev.discover_group(
        doble, holding_name="Acme Holdings Ltd", hints=["Filial Remota"],
    ))
    assert reason == "ok"
    por_numero = {m.number: m for m in members}
    assert "00000100" in por_numero
    assert por_numero["00000100"].depth == 5
    assert por_numero["00000100"].parent == "00000101"
    assert doble.llamadas_psc["00000104"] == 1


class _DobleControladora:
    """Sin nombre exacto para el holding; la candidata (pista) tiene como PSC
    una sociedad CON el nombre del holding y numero UK propio, todavia no
    verificada: entra como raiz del grupo y la candidata cuelga de ella."""

    requests_used = 1

    async def search_companies(self, query, items=10):
        if ev.normalize_name(query) == ev.normalize_name("Filial Acme"):
            return [{"company_number": "00000100", "title": "Filial Acme Ltd",
                     "company_status": "active"}]
        return []

    async def persons_with_significant_control(self, number):
        if number == "00000100":
            return [_psc_uk("Acme Holdings Ltd", "00000099")]
        return []

    async def officers(self, number):
        return []


def test_controladora_con_nombre_del_holding_y_registro_entra_como_raiz():
    members, reason = asyncio.run(ev.discover_group(
        _DobleControladora(), holding_name="Acme Holdings Ltd",
        hints=["Filial Acme"],
    ))
    assert reason == "ok"
    por_numero = {m.number: m for m in members}
    assert set(por_numero) == {"00000099", "00000100"}
    raiz = por_numero["00000099"]
    assert raiz.depth == 0
    assert "controladora con el nombre del holding" in raiz.via
    filial = por_numero["00000100"]
    assert filial.depth == 1
    assert filial.parent == "00000099"
    assert "pista" in filial.via


def test_add_chain_no_pisa_miembro_ya_presente():
    """Si un eslabon de la cadena ya era miembro, se conserva su via y su
    profundidad y el nuevo cuelga de el (no se duplica ni se reescribe)."""
    walk = ev._Walk(client=object(), token="ACME", target="ACME HOLDINGS LTD")
    top = ev.GroupMember("00000009", "Acme Holdings Ltd", 0, "raiz")
    previa = ev.GroupMember("00000050", "Ya Estaba Ltd", 1, "via original",
                            parent="00000009")
    walk.members = {m.number: m for m in (top, previa)}
    ev._add_chain(walk, [("00000060", "Nieto Ltd"), ("00000050", "Ya Estaba Ltd")],
                  top, "prueba")
    assert walk.members["00000050"].via == "via original"
    assert walk.members["00000050"].depth == 1
    nuevo = walk.members["00000060"]
    assert nuevo.depth == 2
    assert nuevo.parent == "00000050"
    assert "prueba" in nuevo.via
