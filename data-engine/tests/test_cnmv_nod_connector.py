"""Conector CNMV NOD: parser del listado real, degradacion honesta y paginacion."""

from datetime import date
from pathlib import Path

import httpx
import pytest

from app.services.connectors import cnmv_nod

FIXTURE = (
    Path(__file__).parent / "fixtures" / "cnmv" / "nod_results_2026-11.html"
).read_text(encoding="utf-8")


def test_parse_real_listing_page():
    entries, total_pages = cnmv_nod._parse_page(FIXTURE)
    assert total_pages == 1
    assert len(entries) == 2

    first = entries[0]
    assert first.filing_date == date(2026, 11, 17)
    assert first.issuer_name == "EBRO FOODS, S.A."
    assert first.nif == "A47412333"
    assert first.declarant == "EMPRESAS COMERCIALES E INDUSTRIALES VALENCIANAS, S.L."
    assert first.motive == "Persona Estrechamente Vinculada"
    assert first.registry_number == "2026145125"
    assert first.document_url.startswith("https://www.cnmv.es/webservices/verdocumento/ver?e=")

    second = entries[1]
    assert second.issuer_name == "EDREAMS ODIGEO, S.A."
    assert second.nif == "A02850956"
    assert second.declarant == "Dana Philip Dunne"
    assert second.motive == "Persona con Responsabilidad de Dirección"
    assert second.registry_number == "2026145426"


def test_empty_results_page_returns_nothing():
    entries, total_pages = cnmv_nod._parse_page(
        "<html><body>No se han encontrado resultados</body></html>"
    )
    assert entries == []
    assert total_pages == 0


def test_drifted_page_raises_instead_of_inventing():
    with pytest.raises(cnmv_nod.CNMVNODParseError):
        cnmv_nod._parse_page(
            "<html><body>Número de registro: 1</body></html>"  # marcador sin bloques
        )


def test_block_without_registry_number_raises():
    broken = FIXTURE.replace("Número de registro: 2026145125", "Registro anterior")
    with pytest.raises(cnmv_nod.CNMVNODParseError):
        cnmv_nod._parse_page(broken)


def test_fetch_entries_paginates_with_plain_gets(monkeypatch):
    monkeypatch.setattr(cnmv_nod, "_throttle", lambda: None)
    calls: list[dict] = []
    page_one = FIXTURE.replace("Página 1 de 1", "Página 1 de 2")
    page_two = (
        "<html><body><span>Página 2 de 2</span><ul>"
        + FIXTURE[FIXTURE.find('<li id="') : FIXTURE.find("</ul>")]
        + "</ul></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if request.url.params.get("page") == "1":
            return httpx.Response(200, text=page_two)
        return httpx.Response(200, text=page_one)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetched = cnmv_nod.fetch_entries(date(2026, 11, 17), date(2026, 11, 18), client=client)
    entries = fetched.entries
    assert len(entries) == 3  # 2 de la pagina 1 + 1 de la pagina 2
    assert fetched.total_pages == 2
    assert fetched.fetched_pages == 2
    assert fetched.truncated is False
    assert calls[0] == {"fechad": "17/11/2026", "fechah": "18/11/2026"}
    assert calls[1]["page"] == "1"
    assert {e.registry_number for e in entries} == {
        "2026145125",
        "2026145426",
    } | {entries[2].registry_number}
