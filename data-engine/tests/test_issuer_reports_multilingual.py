"""Financial reports linked by Spanish-speaking issuers must be discoverable."""

import pytest

from app.services.issuer_reports import pick_ir_reports

BASE = "https://ir.gcc.com/en/inversionistas/media"


@pytest.mark.parametrize("name", ["Reporte-anual-2025-en.pdf", "integrated-report-2025.pdf"])
def test_annual_report_variants_are_recognized(name):
    reports = pick_ir_reports(f'<a href="/{name}">Download</a>', BASE)
    assert len(reports) == 1
    assert reports[0].kind == "annual" and reports[0].date == "2025"


def test_actual_gcc_link_forms_find_current_reports_not_2019_archive():
    html = (
        '<a href="https://cdn.investorcloud.net/gcc/InformacionFinanciera/InformacionTrimestral/GCC-3T2026-en.pdf">Earnings release</a>'
        '<a href="https://investorcloud.s3.amazonaws.com/gcc/InformacionFinanciera/InformacionAnual/GCC-integrated-report-2025-.pdf">Integrated Report</a>'
        '<a href="https://cdn.investorcloud.net/gcc/InformacionFinanciera/InformacionAnual/GCC-Reporte-anual-2025-en.pdf">Annual Regulatory filing CNBV</a>'
        '<a href="https://cdn.investorcloud.net/gcc/InformacionFinanciera/Presentaciones/GCC-2019-05-27-1T19.pdf">Q1 2019 Results</a>'
    )
    reports = {report.kind: report for report in pick_ir_reports(html, BASE)}
    assert reports["annual"].date == "2025"
    assert reports["annual"].url.endswith("GCC-integrated-report-2025-.pdf")
    assert reports["periodic"].url.endswith("GCC-3T2026-en.pdf")
    assert reports["periodic"].date == "2026"


@pytest.mark.parametrize("filename", ["ESG-integrated-report-2026.pdf", "sustainability-integrated-report-2026.pdf",
                                      "presentation-3T2026.pdf", "notice-annual-report-2026.pdf"])
def test_non_financial_exclusions_still_win(filename):
    assert pick_ir_reports(f'<a href="/{filename}">Download</a>', BASE) == []


@pytest.mark.parametrize("outcome", ["resolved", "unresolved", "empty", "nsm_error"])
def test_uk_discovery_keeps_nsm_and_registry_fallback(monkeypatch, outcome):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services import esef_live, issuer_reports
    from app.services.connectors import esef, fca_nsm

    http = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(esef, "gleif_http_client", lambda: http)
    monkeypatch.setattr(esef, "EsefClient", lambda: object())
    identity = None if outcome == "unresolved" else SimpleNamespace(lei="test-lei")
    monkeypatch.setattr(esef_live, "resolve_issuer", AsyncMock(return_value=(identity, "identity-test")))
    filing = SimpleNamespace(filing_type="Final Results", document_format="Plain text",
                             submitted_date="2026-03-01", url="https://example.test/results", company="Test PLC")
    nsm = SimpleNamespace(list_filings_for_lei=AsyncMock(return_value=[filing] if outcome == "resolved" else []))
    if outcome == "nsm_error":
        nsm.list_filings_for_lei.side_effect = fca_nsm.NsmError("offline")
    monkeypatch.setattr(fca_nsm, "NsmClient", lambda **kwargs: nsm)
    ch = issuer_reports.ReportLink("annual", "https://example.test/accounts", "Accounts", "2025", "Companies House")
    fallback = AsyncMock(return_value=ch)
    monkeypatch.setattr(issuer_reports, "companies_house_report", fallback)
    links, reason = asyncio.run(issuer_reports.discover_reports(SimpleNamespace(ticker="TEST.L", name="Test PLC")))
    assert len(links) == 1 and links[0].kind == "annual"
    http.aclose.assert_awaited_once()
    if outcome == "resolved":
        assert reason == "ok" and links[0].url.endswith("results")
        fallback.assert_not_awaited()
    else:
        assert links[0] == ch and reason.startswith("companies_house")
        fallback.assert_awaited_once()
