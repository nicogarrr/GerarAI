"""Companies House: cadena de PSC demasiado larga y cifras iXBRL mixtas.

Dobles minimos sin red (el estilo replay de la API real vive en
test_companies_house.py). Aqui se fija que una filial cuya cadena de
controladoras supera el maximo de saltos NO se usa: queda en `unverified`
con el motivo, y que una cifra ilegible no se lleva por delante las demas
metricas del mismo documento.

NO prueba (declarado): la API real, cadenas que SI llegan al holding
(cubiertas con replay en test_companies_house.py), ni homonimos.
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


class _DobleCadenaLarga:
    """Holding verificable por nombre exacto y una candidata (pista) cuya
    cadena de PSC sube 5 controladoras sin llegar nunca al holding."""

    requests_used = 1

    async def search_companies(self, query, items=10):
        if ev.normalize_name(query) == ev.normalize_name("Acme Holdings Ltd"):
            return [{"company_number": "00000001", "title": "Acme Holdings Ltd",
                     "company_status": "active"}]
        return [{"company_number": "00000100", "title": "Filial Remota Ltd",
                 "company_status": "active"}]

    async def persons_with_significant_control(self, number):
        # 00000100 -> 00000101 -> ... -> 00000104 (4 saltos agotan el maximo
        # sin llegar al holding); el PSC de 00000104 ya no se consulta.
        saltos = {
            "00000100": _psc_uk("Cadena Uno Ltd", "00000101"),
            "00000101": _psc_uk("Cadena Dos Ltd", "00000102"),
            "00000102": _psc_uk("Cadena Tres Ltd", "00000103"),
            "00000103": _psc_uk("Cadena Cuatro Ltd", "00000104"),
        }
        return [saltos[number]] if number in saltos else []

    async def officers(self, number):
        return []


def test_cadena_psc_mas_de_max_saltos_queda_sin_verificar():
    unverified = []
    members, reason = asyncio.run(ev.discover_group(
        _DobleCadenaLarga(), holding_name="Acme Holdings Ltd",
        hints=["Filial Remota"], unverified=unverified,
    ))
    assert [m.number for m in members] == ["00000001"]
    assert reason == "ok"
    (descartada,) = unverified
    assert descartada["company_number"] == "00000100"
    assert descartada["company_name"] == "Filial Remota Ltd"
    assert "más de" in descartada["why"]
    assert "saltos" in descartada["why"]


def test_figures_ixbrl_metrica_valida_sobrevive_a_la_invalida(monkeypatch):
    """Revenue ilegible se omite, pero el patrimonio neto del MISMO documento
    entra con valor exacto, divisa y cierre (fail closed por metrica, no por
    documento)."""
    from app.services.connectors import esef_ixbrl

    monkeypatch.setattr(esef_ixbrl, "parse_ixbrl_facts", lambda _bio: {
        "facts": {
            "frs-core:Revenue": {"iso4217:GBP": [
                {"val": "no-es-numero", "end": "2025-12-31"},
            ]},
            "frs-core:Equity": {"iso4217:GBP": [
                {"val": "250000000", "instant": "2025-12-31"},
            ]},
        },
    })
    (patrimonio,) = ev.figures_from_ixbrl(b"<html/>")
    assert patrimonio["metric"] == "net_assets"
    assert patrimonio["value"] == 250000000.0
    assert patrimonio["value_millions"] == 250.0
    assert patrimonio["currency"] == "GBP"
    assert patrimonio["period_end"] == "2025-12-31"
