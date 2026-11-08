"""Minoritarios: con beneficio ATRIBUIBLE, los flujos consolidados van a la parte del accionista (BN 40-F).

Cifras de Brookfield Corp. FY2025 (40-F, ifrs-full, millones de USD): beneficio atribuible a la dominante
1.307 (ProfitLossAttributableToOwnersOfParent), a minoritarios 1.928 (total 3.235).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import financial_ingestion_service as fis
from app.services import shareholder_irr_service as svc
from app.valuation.attributable import FROM_EARNINGS, FROM_EQUITY, attributable_share, attributable_shares


def test_parte_del_accionista():
    share, how = attributable_share(net_income_parent=1307.0, net_income_minority=1928.0,
                                    equity_parent=None, equity_minority=None) or (None, None)
    assert share == pytest.approx(1307 / 3235) and how == FROM_EARNINGS
    # pérdidas de minoritarios (parte > 1): se usa el patrimonio
    assert attributable_share(net_income_parent=100.0, net_income_minority=-40.0, equity_parent=40_000.0,
                              equity_minority=120_000.0) == (pytest.approx(0.25), FROM_EQUITY)
    assert attributable_share(net_income_parent=100.0, net_income_minority=None, equity_parent=None,
                              equity_minority=None) is None
    filled = attributable_shares([1.0, 2.0, 3.0], [None, 2.0, None], [None] * 3, [None] * 3)
    assert [x[0] if x else None for x in filled] == [0.5, 0.5, 0.5]
    assert attributable_shares([1.0], [None], [None], [None]) == [None]


def test_minoritarios_ifrs_mapeados_y_version_de_reglas():
    ifrs = {m: c for m, c, _ in fis.SEC_IFRS_METRIC_MAP}
    assert ifrs["minority_interest"] == ["NoncontrollingInterests"]
    assert ifrs["net_income_minority"] == ["ProfitLossAttributableToNoncontrollingInterests"]
    sec = {m: c for m, c, _ in fis.SEC_METRIC_MAP}
    assert sec["net_income_minority"] == ["NetIncomeLossAttributableToNoncontrollingInterest"]
    esef = {m: c for m, c, _ in fis.ESEF_METRIC_MAP}
    assert esef["minority_interest"] == ["ifrs-full:NoncontrollingInterests"]
    assert fis.SEC_INGESTION_RULES_VERSION >= 7 and fis.ESEF_INGESTION_RULES_VERSION >= 5


def _cite(v, year, metric, unit="USD"):
    return {"value": v * 1_000_000, "unit": unit, "period": f"{year}-12-31:FY", "metric": metric,
            "source_type": "SEC", "is_reported": True}


def test_holding_con_minoritarios_por_per_usa_flujos_atribuibles(monkeypatch):
    years = [2023, 2024, 2025]
    data = {
        "revenue": [93_000.0, 86_000.0, 75_000.0],
        "net_income": [1_100.0, 641.0, 1_307.0],
        "net_income_minority": [3_000.0, 1_400.0, 1_928.0],
        "operating_cash_flow": [6_300.0, 5_900.0, 7_200.0],
        "capital_expenditure": [2_000.0, 2_100.0, 2_300.0],
        "shares_diluted": [1_650.0, 1_640.0, 1_650.0],
    }
    annual = {m: {y: _cite(v, y, m) for y, v in zip(years, vals, strict=True)} for m, vals in data.items()}
    annual["shares_diluted"] = {y: {**c, "unit": "shares"} for y, c in annual["shares_diluted"].items()}
    point = {"cash_and_equivalents": _cite(12_000.0, 2025, "cash"), "total_debt": _cite(250_000.0, 2025, "debt")}
    monkeypatch.setattr(svc, "company_facts", lambda db, company: (annual, point))
    import app.services.user_sotp_service as us

    monkeypatch.setattr(us, "_price", lambda db, company: (45.0, "USD", "2026-03-31"))
    company = SimpleNamespace(ticker="BN", currency="USD", sector="Financial Services", industry="Asset Management",
                              company_type="", sic_code=6282)
    sp, hist, warnings, cites = svc.starting_point(None, company, today=date(2026, 4, 1))  # type: ignore[arg-type]
    assert sp.basis == "pe", cites["method"]
    share = 1307 / 3235
    # Antes: flujo de 7.200 (consolidado) frente a un beneficio de 1.307 (atribuible): conversión ×5,5.
    assert hist.operating_cash_flow[-1] == pytest.approx(7_200.0 * share)
    assert hist.capex[-1] == pytest.approx(2_300.0 * share)
    assert cites["attributable_share"]["years"]["2025"]["share"] == pytest.approx(share)
    assert any("minoritarios" in w for w in warnings)


def _ifrs_payload(rows):
    """companyfacts ifrs-full mínimo (40-F): rows = (concept, start, end, val, unit)."""
    facts: dict = {"ifrs-full": {}}
    for concept, start, end, val, unit in rows:
        node = facts["ifrs-full"].setdefault(concept, {"units": {}})
        r = {"end": end, "val": val, "filed": f"{int(end[:4]) + 1}-03-01", "form": "40-F"}
        if start:
            r["start"] = start
        node["units"].setdefault(unit, []).append(r)
    return {"facts": facts}




def test_arnes_pit_lleva_los_flujos_a_la_parte_del_accionista():
    from app.valuation import irr_pit_backtest as bt

    rows = []
    for y, ni, nci, ocf in ((2023, 1_100, 3_000, 6_300), (2024, 641, 1_400, 5_900), (2025, 1_307, 1_928, 7_200)):
        s, e = f"{y}-01-01", f"{y}-12-31"
        rows += [("Revenue", s, e, 80_000e6, "USD"), ("ProfitLossAttributableToOwnersOfParent", s, e, ni * 1e6, "USD"),
                 ("ProfitLossAttributableToNoncontrollingInterests", s, e, nci * 1e6, "USD"),
                 ("CashFlowsFromUsedInOperatingActivities", s, e, ocf * 1e6, "USD"),
                 ("AdjustedWeightedAverageShares", s, e, 1_650e6, "shares")]
    facts = bt.facts_from_companyfacts(_ifrs_payload(rows))
    t = date(2026, 6, 30)
    inp = bt.build_inputs(bt.as_of(facts, t), t=t, price=45.0, splits=[], financial=True, currency="USD")
    assert inp.start.basis == "pe"
    assert inp.history.operating_cash_flow[-1] == pytest.approx(7_200 * 1307 / 3235)
