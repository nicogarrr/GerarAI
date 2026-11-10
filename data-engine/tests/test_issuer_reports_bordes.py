"""Descubrimiento IR y errores de Companies House con respuestas locales."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import companies_house_evidence, public_fetch
from app.services import issuer_reports as svc
from app.services.connectors import companies_house


def test_ir_ausente_error_sin_pdf_y_redireccion(monkeypatch):
    company = SimpleNamespace(ticker="TEST.TO", ir_url="")
    assert asyncio.run(svc.discover_reports(company)) == (
        [],
        "sin_ir_url: la ficha no tiene la web de inversores",
    )
    company.ir_url = "https://example.test/ir"
    fetch = AsyncMock(side_effect=ValueError("offline"))
    monkeypatch.setattr(public_fetch, "fetch_public_url_async", fetch)
    assert asyncio.run(svc.discover_reports(company)) == ([], "ir_inaccesible: ValueError")
    fetch.side_effect = None
    fetch.return_value = (b"<p>no documents</p>", {}, "")
    assert asyncio.run(svc.discover_reports(company)) == ([], "ir_sin_informes_pdf")
    fetch.return_value = (
        b'<a href="annual-report-2026.pdf">Annual Report 2026</a>',
        {},
        "https://cdn.test/reports/",
    )
    links, reason = asyncio.run(svc.discover_reports(company))
    assert reason == "ok" and len(links) == 1
    assert links[0].url == "https://cdn.test/reports/annual-report-2026.pdf"
    assert links[0].date == "2026"
    fetch.assert_awaited_with(company.ir_url, timeout=30)


@pytest.mark.parametrize("outcome", ["error", "empty", "no_url"])
def test_companies_house_errores_y_sin_documento_cierran_cliente(monkeypatch, outcome):
    client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(companies_house, "client_from_settings", lambda **kwargs: client)
    if outcome == "error":
        read = AsyncMock(side_effect=companies_house.CompaniesHouseError("offline"))
    else:
        read = AsyncMock(return_value=None if outcome == "empty" else {"company_name": "Test"})
    monkeypatch.setattr(companies_house_evidence, "issuer_annual_accounts", read)
    assert asyncio.run(svc.companies_house_report(SimpleNamespace(name="Test"))) is None
    client.aclose.assert_awaited_once()
    read.assert_awaited_once_with(client, "Test")


def test_ir_descarta_sin_fecha_y_extensiones_no_pdf():
    links = svc.pick_ir_reports(
        '<a href="annual-report.pdf">Annual Report</a>'
        '<a href="annual-report-2026.html">Annual 2026</a>'
        '<a href="javascript:annual-report-2026.pdf">Annual 2026</a>'
        '<a href="annual-report-2025.pdf">AR</a>',
        "https://example.test/",
    )
    assert len(links) == 1
    assert links[0].title == "annual report 2025" and links[0].date == "2025"


def test_unico_pdf_sin_fecha_se_rechaza():
    assert svc.pick_ir_reports('<a href="annual-report.pdf">Annual Report</a>', "https://example.test/") == []
