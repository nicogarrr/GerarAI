"""TIR del accionista: caja, deuda, amortización, plusvalías o capex ausentes de todas las fuentes son N/D
con su motivo, nunca 0 («que no se pierda ningún dato»). Un 0 declarado por el emisor sí es un dato."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import shareholder_irr_service as svc
from app.valuation import shareholder_irr as engine
from app.valuation import shareholder_irr_rules as rules

YEARS = [2022, 2023, 2024]


def _cite(v, year, metric, unit="USD"):
    return {"value": v, "unit": unit, "period": f"{year}-12-31:FY", "metric": metric,
            "source_type": "SEC", "is_reported": True}


def _serie(metric, values):
    return {y: _cite(v * 1e6, y, metric) for y, v in zip(YEARS, values, strict=True) if v is not None}


def _empresa(monkeypatch, annual, point, **kw):
    monkeypatch.setattr(svc, "company_facts", lambda db, company: (annual, point))
    import app.services.user_sotp_service as us

    monkeypatch.setattr(us, "_price", lambda db, company: (20.0, "USD", "2025-03-31"))
    company = SimpleNamespace(ticker="XYZ", currency="USD", sector=kw.get("sector", "Industrials"),
                              industry=kw.get("industry", "Machinery"), company_type="", sic_code=kw.get("sic", 3560))
    return svc.starting_point(None, company, today=date(2025, 4, 1))  # type: ignore[arg-type]


def _operativa(**over):
    annual = {
        "revenue": _serie("revenue", (900.0, 1000.0, 1100.0)),
        "operating_income": _serie("operating_income", (90.0, 100.0, 120.0)),
        "depreciation_amortization": _serie("depreciation_amortization", (30.0, 32.0, 35.0)),
        "net_income": _serie("net_income", (60.0, 70.0, 80.0)),
        "shares_diluted": {y: _cite(100e6, y, "shares_diluted", "shares") for y in YEARS},
        "operating_cash_flow": _serie("operating_cash_flow", (100.0, 110.0, 130.0)),
        "capital_expenditure": _serie("capital_expenditure", (-40.0, -45.0, -50.0)),
    }
    annual.update(over)
    return annual


def test_sin_deuda_en_ninguna_fuente_es_nd_no_cero(monkeypatch):
    # antes: «deuda sin dato: se toma 0 y se avisa» y la deuda neta salía −150 (caja − 0)
    with pytest.raises(ValueError, match="sin deuda"):
        _empresa(monkeypatch, _operativa(), {"cash_and_equivalents": _cite(150e6, 2024, "cash")})


def test_deuda_cero_declarada_si_es_un_dato(monkeypatch):
    point = {"cash_and_equivalents": _cite(150e6, 2024, "cash"), "total_debt": _cite(0.0, 2024, "total_debt")}
    sp, _hist, warnings, cites = _empresa(monkeypatch, _operativa(), point)
    assert sp.debt == 0.0 and sp.net_debt == pytest.approx(-150.0)
    assert cites["total_debt"]["value"] == 0.0  # el 0 lleva su fuente
    assert not any("deuda sin dato" in w for w in warnings)


def test_sin_caja_es_nd_no_cero(monkeypatch):
    # antes: caja = 0 y la deuda neta era toda la deuda
    with pytest.raises(ValueError, match="sin caja"):
        _empresa(monkeypatch, _operativa(), {"total_debt": _cite(300e6, 2024, "total_debt")})


def test_capex_ausente_no_infla_la_conversion():
    sp = engine.StartingPoint(price=20.0, shares_diluted=100.0, revenue=1100.0, ebitda=155.0, net_income=80.0,
                              cash=150.0, debt=300.0, currency="USD", basis="ev_ebitda")
    hist = rules.History(years=YEARS, revenue=[900.0, 1000.0, 1100.0], earnings=[120.0, 132.0, 155.0],
                         operating_cash_flow=[100.0, 110.0, 130.0], capex=[None, None, None])
    out = rules.build_scenarios(sp, hist)
    # antes: conversión = flujo operativo / EBITDA (capex = 0) ≈ 0,83; ahora N/D, avisado, y no se inventa
    assert out.trace["conversion"]["ultimos"] == []
    assert any("capex N/D en 2022, 2023, 2024" in w for w in out.warnings)


def test_runway_sin_capex_es_nd_con_motivo():
    sp = engine.StartingPoint(price=2.0, shares_diluted=100.0, revenue=0.0, ebitda=-50.0, net_income=-60.0,
                              cash=120.0, debt=0.0, currency="USD", basis="ev_ebitda")
    hist = rules.History(years=YEARS, revenue=[0.0, 0.0, 0.0], earnings=[-40.0, -45.0, -50.0],
                         operating_cash_flow=[-30.0, -35.0, -40.0], capex=[None, None, None])
    rw = svc.runway(sp, hist, {"annual": {}})
    # antes: consumo = 40 (capex 0) y 36 meses de margen
    assert rw["free_cash_flow"] is None and rw["months"] is None
    assert rw["missing"] == "sin capex"


def _reit(gains):
    return _operativa(**{
        "net_income": _serie("net_income", (40.0, 45.0, 50.0)),
        "depreciation_amortization": _serie("depreciation_amortization", (60.0, 62.0, 65.0)),
        "gain_on_sale_real_estate": _serie("gain_on_sale_real_estate", gains),
        "lease_income": _serie("lease_income", (900.0, 1000.0, 1100.0)),
    })


def test_ffo_sin_plusvalias_en_ninguna_fuente_es_nd(monkeypatch):
    point = {"cash_and_equivalents": _cite(50e6, 2024, "cash"), "total_debt": _cite(800e6, 2024, "total_debt")}
    kw = {"sector": "Real Estate", "industry": "Real Estate", "sic": 6798}
    _sp, _hist, warnings, cites = _empresa(monkeypatch, _reit((5.0, 4.0, None)), point, **kw)
    # antes: FFO 2024 = 50 + 65 − 0 = 115 «puede estar inflado»; ahora N/D con el input que falta
    assert cites["method"]["chosen"] != "tir_ffo"
    assert any("FFO 2024 N/D (sin plusvalías por ventas de inmuebles" in w for w in warnings)


def test_ffo_con_plusvalias_cero_declaradas_si_se_calcula(monkeypatch):
    point = {"cash_and_equivalents": _cite(50e6, 2024, "cash"), "total_debt": _cite(800e6, 2024, "total_debt")}
    kw = {"sector": "Real Estate", "industry": "Real Estate", "sic": 6798}
    sp, _hist, warnings, cites = _empresa(monkeypatch, _reit((5.0, 4.0, 0.0)), point, **kw)
    assert cites["method"]["chosen"] == "tir_ffo"
    assert sp.net_income == pytest.approx(115.0)
    assert not any("FFO" in w and "N/D" in w for w in warnings)
