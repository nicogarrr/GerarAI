"""Filers IFRS de la SEC: los pasivos por arrendamiento (NIIF 16) entran en la deuda del EV.

Antes (main): el mapa IFRS de la SEC no traía arrendamientos, así que CNQ (40-F 2025: 373 + 2.733 =
3.106 M CAD) y BN (solo el total, LeaseLiabilities 9.201 M USD) salían con arrendamientos 0 en la TIR,
y BN, que reporta en USD, ni siquiera se trataba como IFRS.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import financial_ingestion_service as fis
from app.services import shareholder_irr_service as svc


def test_mapa_ifrs_sec_trae_arrendamientos():
    ifrs = {m: c for m, c, _ in fis.SEC_IFRS_METRIC_MAP}
    assert ifrs["lease_liabilities"] == ["LeaseLiabilities"]
    assert ifrs["lease_liabilities_current"] == ["CurrentLeaseLiabilities"]
    assert ifrs["lease_liabilities_noncurrent"] == ["NoncurrentLeaseLiabilities"]
    assert fis.SEC_INGESTION_RULES_VERSION >= 11


def _cite(v, year, metric, unit="USD"):
    return {"value": v * 1_000_000, "unit": unit, "period": f"{year}-12-31:FY", "metric": metric,
            "source_type": "SEC", "is_reported": True}


def _sp(monkeypatch, point_extra, currency):
    years = [2023, 2024, 2025]
    data = {
        "revenue": [36_000.0, 35_600.0, 38_762.0],
        "net_income": [8_200.0, 6_100.0, 10_820.0],
        "operating_income": [11_000.0, 9_000.0, 12_000.0],
        "depreciation_amortization": [5_000.0, 5_500.0, 6_000.0],
        "operating_cash_flow": [12_000.0, 14_000.0, 15_106.0],
        "capital_expenditure": [-5_000.0, -5_500.0, -6_676.0],
        "shares_diluted": [2_200.0, 2_150.0, 2_098.0],
    }
    annual = {m: {y: _cite(v, y, m, currency) for y, v in zip(years, vals, strict=True)} for m, vals in data.items()}
    annual["shares_diluted"] = {y: {**c, "unit": "shares"} for y, c in annual["shares_diluted"].items()}
    point = {"cash_and_equivalents": _cite(673.0, 2025, "cash", currency),
             "total_debt": _cite(16_617.0, 2025, "debt", currency), **point_extra}
    monkeypatch.setattr(svc, "company_facts", lambda db, company: (annual, point))
    import app.services.user_sotp_service as us

    monkeypatch.setattr(us, "_price", lambda db, company: (45.0, currency, "2026-03-31"))
    monkeypatch.setattr(us, "convert_amount", lambda amount, frm, to, *a, **k: amount, raising=False)
    company = SimpleNamespace(ticker="CNQ", currency=currency, sector="Energy", industry="Oil & Gas E&P",
                              company_type="", sic_code=1311)
    return svc.starting_point(None, company, today=date(2026, 4, 1))  # type: ignore[arg-type]


def test_partes_corriente_y_no_corriente(monkeypatch):
    sp, _hist, _w, cites = _sp(monkeypatch, {
        "lease_liabilities_current": _cite(373.0, 2025, "lease_liabilities_current"),
        "lease_liabilities_noncurrent": _cite(2_733.0, 2025, "lease_liabilities_noncurrent")}, "USD")
    assert sp.leases == pytest.approx(3_106.0)
    assert cites["ifrs16_leases_in_debt"] is True


def test_solo_total_declarado(monkeypatch):
    sp, _hist, _w, cites = _sp(monkeypatch, {"lease_liabilities": _cite(9_201.0, 2025, "lease_liabilities")}, "USD")
    assert sp.leases == pytest.approx(9_201.0)
    assert cites["lease_liabilities"]["value"] == 9_201_000_000


def test_us_gaap_sin_arrendamientos_ifrs_no_cambia(monkeypatch):
    sp, _hist, _w, cites = _sp(monkeypatch, {}, "USD")
    assert sp.leases == 0.0
    assert cites["ifrs16_leases_in_debt"] is False
