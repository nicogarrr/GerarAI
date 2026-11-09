"""Companies House: pistas de filiales, personas del holding y descubrimiento.

Dobles minimos sin red (el replay de la API real vive en test_companies_house.py).
Se fijan: holding sin nombre normalizable; pistas invalidas, duplicadas o por
encima del maximo; candidatas sin numero o ya verificadas; administrador sin
enlace de nombramientos; alias verificados como pistas y como personas; la cache
de alias caida se avisa en notas y no tumba; pistas desde impulsores de valor con
dedupe; y el emisor sin nombre exacto.

NO prueba (declarado): la API real, la base de datos (db va a None y los servicios
que la usan van doblados), ni la valoracion (ValueDriverService va doblado: solo se
comprueba que sus nombres de segmentos/activos llegan como pistas, nunca cifras).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services import companies_house_evidence as ev
from app.services import company_alias_sources as cas


class _DobleBusqueda:
    """Holding por nombre exacto (00000001); el resto de busquedas, prefijadas.
    Cuenta las busquedas (spy)."""

    requests_used = 1

    def __init__(self, otras=None):
        self.llamadas_search = 0
        self._otras = otras or {}

    async def search_companies(self, query, items=10):
        self.llamadas_search += 1
        if ev.normalize_name(query) == ev.normalize_name("Acme Holdings Ltd"):
            return [{"company_number": "00000001", "title": "Acme Holdings Ltd",
                     "company_status": "active"}]
        return list(self._otras.get(ev.normalize_name(query), []))

    async def persons_with_significant_control(self, number):
        return []

    async def officers(self, number):
        return []

    async def officer_appointments(self, path):
        raise AssertionError("no debe llamarse: el administrador no tiene enlace")


def test_holding_sin_nombre_normalizable_no_busca_y_se_declara():
    """«!!!» no normaliza a nada: sin busqueda, sin miembros y motivo declarado;
    las no verificadas se recogen si se pasa la lista y se omiten si no."""
    doble = _DobleBusqueda()
    sin_lista, motivo = asyncio.run(ev.discover_group(doble, holding_name="!!!"))
    assert sin_lista == []
    assert motivo.startswith("sin_sociedad_britanica")
    recogidas = []
    con_lista, motivo2 = asyncio.run(
        ev.discover_group(doble, holding_name="!!!", unverified=recogidas))
    assert con_lista == []
    assert motivo2.startswith("sin_sociedad_britanica")
    assert recogidas == []
    assert doble.llamadas_search == 0


def test_pistas_invalidas_o_repetidas_no_se_buscan():
    """Vacias, de menos de 3 letras, iguales al holding o repetidas se saltan
    sin gastar busquedas."""
    doble = _DobleBusqueda()
    members, reason = asyncio.run(ev.discover_group(
        doble, holding_name="Acme Holdings Ltd",
        hints=["", "AB", "Acme Holdings Ltd", "Filial Remota", "Filial Remota"],
    ))
    assert [m.number for m in members] == ["00000001"]
    assert reason == "ok"
    assert doble.llamadas_search == 2  # holding + la unica pista valida


def test_pistas_por_encima_del_maximo_cortan_el_gasto():
    """A partir de MAX_HINTS pistas distintas no se busca mas."""
    doble = _DobleBusqueda()
    pistas = [f"Empresa Numero {i} Ltd" for i in range(15)]
    members, _ = asyncio.run(ev.discover_group(
        doble, holding_name="Acme Holdings Ltd", hints=pistas))
    assert [m.number for m in members] == ["00000001"]
    assert doble.llamadas_search == 1 + ev.MAX_HINTS


def test_candidata_sin_numero_o_ya_verificada_se_salta():
    """La candidata sin numero y la que ya era miembro no repiten trabajo; la
    que no llega al grupo por PSC queda en unverified con el motivo."""
    otras = {ev.normalize_name("Filial Remota"): [
        {"title": "Filial Remota Fantasma Ltd", "company_status": "active"},
        {"company_number": "00000001", "title": "Filial Remota Holding Ltd",
         "company_status": "active"},
        {"company_number": "00000100", "title": "Filial Remota Ltd",
         "company_status": "active"},
    ]}
    doble = _DobleBusqueda(otras)
    unverified = []
    members, reason = asyncio.run(ev.discover_group(
        doble, holding_name="Acme Holdings Ltd",
        hints=["Filial Remota"], unverified=unverified,
    ))
    assert [m.number for m in members] == ["00000001"]
    assert reason == "ok"
    (descartada,) = unverified
    assert descartada["company_number"] == "00000100"
    assert "no llega al grupo" in descartada["why"]


def test_administrador_sin_enlace_de_nombramientos_no_expande():
    """Un administrador en activo sin link de appointments se salta (el doble
    falla si se le pide la cita)."""
    doble = _DobleBusqueda()

    async def officers(number):
        return [{"name": "Jane Doe", "links": {}}]

    doble.officers = officers
    members, reason = asyncio.run(
        ev.discover_group(doble, holding_name="Acme Holdings Ltd"))
    assert [m.number for m in members] == ["00000001"]
    assert reason == "ok"


def _empresa(ticker="ZZZ", company_id=7):
    return SimpleNamespace(ticker=ticker, id=company_id)


def test_subsidiary_hints_sin_cache_de_alias_avisa_en_notas(monkeypatch):
    """La cache de alias caida no tumba las pistas: se anota el motivo en las
    notas y se sigue (aqui sin impulsores: lista vacia)."""
    def _caida(db):
        raise RuntimeError("sqlite caida")

    monkeypatch.setattr(cas, "load_cached", _caida)
    notas = []
    assert ev.subsidiary_hints(None, _empresa(), None, notas) == []
    assert len(notas) == 1
    assert "caché de alias" in notas[0]


def test_subsidiary_hints_desde_impulsores_con_dedupe(monkeypatch):
    """Sin alias verificados, las pistas salen de los impulsores de valor
    (segmentos/activos/opciones), sin duplicados ni nombres en blanco."""
    from app.services import value_driver_service as vds

    monkeypatch.setattr(cas, "load_cached", lambda db: {})

    class _FalsoVDS:
        def current(self, db, *, company_id, tenant_id):
            assert company_id == 7 and tenant_id == 5
            return {
                "a": SimpleNamespace(name="Segmento Norte", category="linea_negocio"),
                "b": SimpleNamespace(name="Segmento Norte", category="activo"),
                "c": SimpleNamespace(name="Dato Interno", category="interna"),
                "d": SimpleNamespace(name="   ", category="opcion"),
            }

    monkeypatch.setattr(vds, "ValueDriverService", _FalsoVDS)
    assert ev.subsidiary_hints(None, _empresa(), 5, []) == ["Segmento Norte"]


def test_holding_people_solo_personas_verificadas(monkeypatch):
    """Solo cuentan las personas con etiqueta verificada; filiales y rumores no."""
    record = SimpleNamespace(aliases=[
        SimpleNamespace(tipo="persona", etiqueta=cas.VERIFIED, termino="Prem Watsa"),
        SimpleNamespace(tipo="filial", etiqueta=cas.VERIFIED, termino="Filial X"),
        SimpleNamespace(tipo="persona", etiqueta="rumor", termino="Persona Rumor"),
    ])
    monkeypatch.setattr(cas, "load_cached", lambda db: {"ZZZ": record})
    assert ev.holding_people(None, _empresa()) == ["Prem Watsa"]


def test_holding_people_sin_cache_devuelve_vacio(monkeypatch):
    def _caida(db):
        raise KeyError("sin tabla")

    monkeypatch.setattr(cas, "load_cached", _caida)
    assert ev.holding_people(None, _empresa()) == []


def test_issuer_annual_accounts_sin_nombre_exacto_devuelve_none():
    """Hay sociedades parecidas pero ninguna con el nombre exacto: None."""
    doble = _DobleBusqueda({ev.normalize_name("Acme Holdings Ltd"): [
        {"company_number": "00000002", "title": "Acme Holdings Remota Ltd",
         "company_status": "active"},
    ]})

    async def search(query, items=10):
        return [{"company_number": "00000002", "title": "Acme Holdings Remota Ltd",
                 "company_status": "active"}]

    doble.search_companies = search
    assert asyncio.run(
        ev.issuer_annual_accounts(doble, "Acme Holdings Ltd")) is None
