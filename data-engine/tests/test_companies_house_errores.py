"""Companies House: caminos de error y cache del uso sincrono.

Sin red y sin respuestas grabadas: el cliente es un doble minimo (los caminos
felices con replay viven en test_companies_house.py). Aqui solo se fijan los
contratos de fallo: presupuesto agotado -> error, fallo puntual en las cuentas
de una sociedad -> partial conservando lo hecho, excepcion inesperada -> la
herramienta nunca tumba al experto (dict de error), y la cache por proceso.

NO prueba (declarado): la API real, el formato de las respuestas, la cadena
PSC larga, ni las cifras iXBRL validas (en test_companies_house.py).
"""

from __future__ import annotations

import asyncio
import time

from app.services import companies_house_evidence as ev
from app.services.connectors import companies_house as ch


class _Doble:
    """Cliente minimo: busca el holding por nombre exacto y sin administradores."""

    def __init__(self):
        self.requests_used = 1
        self.llamadas = {"search": 0, "officers": 0, "filing_history": 0}

    async def search_companies(self, query, items=10):
        self.llamadas["search"] += 1
        return [{"company_number": "00000001", "title": query,
                 "company_status": "active"}]

    async def officers(self, number):
        self.llamadas["officers"] += 1
        return []


class _DobleSinPresupuesto(_Doble):
    async def search_companies(self, query, items=10):
        self.llamadas["search"] += 1
        raise ch.CompaniesHouseBudgetExceeded("presupuesto agotado")


class _DobleCuentasCaidas(_Doble):
    async def filing_history(self, number, category=None, items=10):
        self.llamadas["filing_history"] += 1
        raise ch.CompaniesHouseError("gateway 502")


class _DobleInesperado(_Doble):
    async def search_companies(self, query, items=10):
        self.llamadas["search"] += 1
        raise ValueError("payload inesperado")


def test_group_accounts_sin_presupuesto_es_error_declarado():
    """El presupuesto agotado no se traga ni tumba: status error con el tipo
    de la excepcion, sin miembros y con el gasto real del cliente."""
    doble = _DobleSinPresupuesto()
    result = asyncio.run(
        ev.group_accounts(doble, holding_name="Acme Holdings Ltd")
    )
    assert result["status"] == "error"
    assert result["reason"] == "CompaniesHouseBudgetExceeded"
    assert result["members"] == []
    assert result["requests_used"] == 1


def test_group_accounts_cuentas_caidas_es_partial_y_conserva_lo_hecho():
    """El holding se verifico pero sus cuentas fallan: status partial con el
    tipo de la excepcion; no se inventan cifras."""
    doble = _DobleCuentasCaidas()
    result = asyncio.run(
        ev.group_accounts(doble, holding_name="Acme Holdings Ltd")
    )
    assert result["status"] == "partial"
    assert result["reason"] == "CompaniesHouseError"
    assert result["members"] == []
    assert doble.llamadas["search"] == 1
    assert doble.llamadas["filing_history"] == 1


def test_collect_group_accounts_cache_hit_no_llama_al_cliente(monkeypatch):
    """Un resultado fresco en cache se devuelve tal cual, sin tocar la API."""
    nombre = ev.normalize_name("Acme Holdings Ltd")
    key = (nombre, (), ())
    cacheado = {"status": "ok", "reason": "ok", "members": [],
                "requests_used": 7, "unverified": []}
    monkeypatch.setitem(ev._CACHE, key, (time.monotonic(), cacheado))
    doble = _Doble()
    assert ev.collect_group_accounts("Acme Holdings Ltd", [], client=doble) is cacheado
    assert doble.llamadas["search"] == 0


def test_collect_group_accounts_excepcion_inesperada_no_tumba_ni_se_cachea():
    """Un fallo que no es de la API (payload roto) vuelve como dict de error
    (_run_sync: la herramienta nunca tumba al experto) y NO se cachea: la
    siguiente llamada lo intenta de nuevo."""
    doble = _DobleInesperado()
    primero = ev.collect_group_accounts("Otra Ltd", [], client=doble)
    assert primero["status"] == "error"
    assert primero["reason"] == "ValueError"
    assert primero["members"] == []
    segundo = ev.collect_group_accounts("Otra Ltd", [], client=doble)
    assert segundo["status"] == "error"
    assert doble.llamadas["search"] == 2


def test_figures_ixbrl_valor_no_decimal_se_omite(monkeypatch):
    """Una cifra ilegible no rompe la lectura: la metrica se omite y el resto
    del documento seguiria entrando (fail closed por metrica)."""
    from app.services.connectors import esef_ixbrl

    monkeypatch.setattr(esef_ixbrl, "parse_ixbrl_facts", lambda _bio: {
        "facts": {"frs-core:Revenue": {"iso4217:GBP": [
            {"val": "no-es-numero", "end": "2025-12-31"},
        ]}},
    })
    assert ev.figures_from_ixbrl(b"<html/>") == []
