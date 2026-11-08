"""Acciones etiquetadas en miles sin declararlo (FRPH 10-K: 9.609 en vez de 9,6 millones)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import shareholder_irr_service as svc
from app.valuation.share_units import rescale_shares


def test_reescala_solo_con_referencia_independiente_mil_veces_mayor():
    shares, why = rescale_shares(0.009609, 9.52)  # millones: 9.609 acciones frente a 9,52 M de portada
    assert shares == pytest.approx(9.609) and why and "miles" in why
    assert rescale_shares(9.609, 9.52) == (9.609, None)  # coherente: no se toca
    assert rescale_shares(0.009609, None, 9.7)[0] == pytest.approx(9.609)  # beneficio / BPA como referencia
    assert rescale_shares(0.5, 9.52) == (0.5, None)  # ×19: fuera de la banda, no es un problema de miles


def _cite(v, year, metric, unit="USD"):
    return {"value": v, "unit": unit, "period": f"{year}-12-31:FY", "metric": metric,
            "source_type": "SEC", "is_reported": True}


def test_starting_point_con_acciones_en_miles(monkeypatch):
    years = [2022, 2023, 2024]
    annual = {
        "revenue": {y: _cite(v * 1e6, y, "revenue") for y, v in zip(years, (37.0, 41.0, 42.0), strict=True)},
        "operating_income": {y: _cite(v * 1e6, y, "operating_income") for y, v in zip(years, (6.0, 7.0, 7.5), strict=True)},
        "depreciation_amortization": {y: _cite(v * 1e6, y, "da") for y, v in zip(years, (9.0, 9.5, 10.0), strict=True)},
        "net_income": {y: _cite(v * 1e6, y, "net_income") for y, v in zip(years, (4.5, 6.0, 5.4), strict=True)},
        "shares_diluted": {y: _cite(9_609.0, y, "shares_diluted", "shares") for y in years},
        "eps_diluted": {y: _cite(v, y, "eps_diluted", "USD/shares") for y, v in zip(years, (0.47, 0.63, 0.56), strict=True)},
    }
    point = {"cash_and_equivalents": _cite(150e6, 2024, "cash")}
    monkeypatch.setattr(svc, "company_facts", lambda db, company: (annual, point))
    import app.services.user_sotp_service as us

    monkeypatch.setattr(us, "_price", lambda db, company: (29.0, "USD", "2025-03-31"))
    company = SimpleNamespace(ticker="FRPH", currency="USD", sector="Real Estate", industry="Real Estate Services",
                              company_type="", sic_code=6531)
    sp, _hist, warnings, cites = svc.starting_point(None, company, today=date(2025, 4, 1))  # type: ignore[arg-type]
    # antes: 0,0096 millones de acciones → capitalización de 279.000 $ en vez de ~279 M $
    assert sp.shares_diluted == pytest.approx(9.609)
    assert cites["shares_scale"]["factor"] == 1000
    assert any("miles" in w for w in warnings)
