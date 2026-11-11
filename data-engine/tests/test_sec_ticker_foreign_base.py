"""Listado con sufijo de mercado: el CIK se busca por la línea US del emisor.

Caso real (carril Canadá, 11-nov-2026): un 40-F se indexa en
company_tickers.json por la línea americana y el listado local con sufijo
(.TO) terminaba en «Sin CIK»: un emisor que SÍ presenta a la SEC se quedaba
sin hechos oficiales. Fail closed como el resto de la capa SEC: el ticker
base solo se prueba con sufijo de mercado conocido, match único y razón
social SEC compatible con la de la ficha (un homónimo US del ticker base
nunca recibe los hechos: PRM de PRIM resolvía a Perimeter Solutions).
Tests sintéticos, sin tickers reales en la lógica.
"""

from __future__ import annotations

import asyncio

from app.services.connectors import sec
from app.services.sec_ticker import CikIndex

# «Alfa Recursos Naturales» cotiza en TSX como ALF.TO y presenta 40-F; la SEC
# la indexa por su línea americana ALF.
TABLE = [
    ("ALF", "0001111111", "ALFA RECURSOS NATURALES LTD"),
    ("ZET", "0002222222", "Zeta Industries Inc"),
    ("DUAL-A", "0003333333", "Dual Corp"),
    ("DUAL.A", "0003333333", "Dual Corp"),
]


def test_listado_con_sufijo_resuelve_por_la_linea_us():
    index = CikIndex(TABLE)
    assert index.lookup_foreign_base("ALF.TO", "Alfa Recursos Naturales, S.A.") == "0001111111"
    # Minúsculas y espacios no cambian nada.
    assert index.lookup_foreign_base(" alf.to ", "Alfa Recursos Naturales") == "0001111111"


def test_homonimo_del_base_nunca_recibe_los_hechos():
    # ZET.TO (TSX) cuya base ZET es OTRO emisor en EE. UU.: la razón social no
    # casa y no hay CIK, aunque el ticker base exista en la SEC.
    index = CikIndex(TABLE)
    assert index.lookup_foreign_base("ZET.TO", "Zephyr Energía Renovable plc") is None


def test_sin_nombre_de_ficha_no_hay_fallback():
    index = CikIndex(TABLE)
    assert index.lookup_foreign_base("ALF.TO", None) is None
    assert index.lookup_foreign_base("ALF.TO", "") is None


def test_sufijo_desconocido_o_sin_sufijo_no_hay_fallback():
    index = CikIndex(TABLE)
    assert index.lookup_foreign_base("ALF.XX", "Alfa Recursos Naturales") is None
    assert index.lookup_foreign_base("ALF", "Alfa Recursos Naturales") is None
    assert index.lookup_foreign_base("ALF.TO.EU", "Alfa Recursos Naturales") is None


def test_base_ambigua_falla_cerrada():
    # Dos emisores distintos con la misma forma normalizada del base: nunca se elige.
    table = [("AMB-A", "0000000001", "Amb Uno Inc"), ("AMB.A", "0000000002", "Amb Dos Inc")]
    index = CikIndex(table)
    assert index.lookup_foreign_base("AMB.A.TO", "Amb Uno") is None
    # Un base que no es variante de clase de ninguna entrada no resuelve nada.
    assert index.lookup_foreign_base("AMB.TO", "Amb Uno") is None
    # Mismo CIK dos veces no es ambiguo (clases del mismo emisor).
    index = CikIndex(TABLE)
    assert index.lookup_foreign_base("DUAL.A.TO", "Dual Corp") == "0003333333"


def test_sin_titulo_en_el_indice_no_hay_prueba_de_identidad():
    # Entradas de 2 elementos (sin razón social): nada que contrastar, fail closed.
    index = CikIndex([("ALF", "0001111111")])
    assert index.lookup_foreign_base("ALF.TO", "Alfa Recursos Naturales") is None


def test_cik_for_ticker_pasa_el_nombre_al_fallback():
    async def run():
        client = sec.SECClient()
        client._ticker_index = lambda: _async_index()  # type: ignore[method-assign]
        return await client.cik_for_ticker("ALF.TO", entity_name="Alfa Recursos Naturales")

    async def _async_index():
        return CikIndex(TABLE)

    assert asyncio.run(run()) == "0001111111"


def test_cik_for_ticker_sin_nombre_sigue_fallando_cerrado():
    async def run():
        client = sec.SECClient()
        client._ticker_index = lambda: _async_index()  # type: ignore[method-assign]
        return await client.cik_for_ticker("ALF.TO")

    async def _async_index():
        return CikIndex(TABLE)

    assert asyncio.run(run()) is None
