"""Filers IFRS de la SEC (40-F/20-F) sin minoritarios: beneficio, patrimonio y deuda.

Antes: CNQ (40-F, CAD) solo etiqueta ifrs-full ProfitLoss / Equity / Borrowings; el mapa pedía lo
atribuible a la dominante y no había deuda total, así que la TIR salía «sin beneficio positivo» y
«deuda sin dato: se toma 0». Con minoritarios (BN) el respaldo no debe activarse.
"""
from __future__ import annotations

from app.services import financial_ingestion_service as F


def _concepts(m, metric):
    return {k: c for k, c, _u in m}[metric]


def _fy(v, end="2025-12-31"):
    return {"units": {"CAD": [{"fp": "FY", "start": end[:4] + "-01-01", "end": end, "val": v}]}}


def test_sin_etiqueta_de_minoritarios_no_prueba_que_no_haya():
    """CNQ 40-F: solo ProfitLoss/Equity. Antes (#4775) se tomaban como atribuibles; la ausencia de la
    etiqueta NCI no prueba NCI = 0: el total se guarda como total y lo atribuible queda no verificable."""
    cnq = {"ProfitLoss": _fy(10_820e6), "Equity": _fy(44_366e6)}
    m = F.sec_ifrs_metric_map_for(cnq)
    assert _concepts(m, "net_income") == ["ProfitLossAttributableToOwnersOfParent"]
    assert _concepts(m, "total_equity") == ["EquityAttributableToOwnersOfParent"]
    assert _concepts(m, "net_income_total") == ["ProfitLoss"]
    assert _concepts(m, "total_equity_total") == ["Equity"]
    assert _concepts(m, "total_debt") == ["Borrowings"]
    signal, why = F.ifrs_nci_signal(cnq)
    assert signal == "sin_senal" and "atribuible no verificable" in why


def test_minoritarios_etiquetados_a_cero_son_senal_positiva():
    m = F.sec_ifrs_metric_map_for({"ProfitLoss": _fy(5), "Equity": _fy(9), "NoncontrollingInterests": _fy(0)})
    assert _concepts(m, "net_income") == ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"]
    assert _concepts(m, "total_equity") == ["EquityAttributableToOwnersOfParent", "Equity"]
    assert "total_equity_total" not in {k for k, _c, _u in m}


def test_con_minoritarios_no_hay_respaldo():
    m = F.sec_ifrs_metric_map_for({"ProfitLoss": {}, "NoncontrollingInterests": {"units": {"USD": [{}]}}})
    assert _concepts(m, "net_income") == ["ProfitLossAttributableToOwnersOfParent"]
    assert _concepts(m, "total_equity") == ["EquityAttributableToOwnersOfParent"]


def test_borrowings_es_el_total_sin_componer():
    e = {"val": 16617e6, "end": "2025-12-31", "accn": "a", "form": "40-F", "filed": "2026-03-01", "fy": 2025, "fp": "FY"}
    out = F._merge_for_metric({"Borrowings": {"2025-12-31": e}}, "total_debt")
    assert float(out["2025-12-31"]["val"]) == 16617e6


def test_reglas_sec_versionadas():
    assert F.SEC_INGESTION_RULES_VERSION >= 13  # 13: ProfitLoss/Equity atribuibles solo con señal positiva


def test_atribuible_distinto_del_total_es_minoritarios_aunque_no_se_etiqueten():
    """BN 40-F: no etiqueta conceptos de minoritarios, pero su beneficio atribuible (1.307 M) no es el
    total (3.235 M): hay minoritarios y Equity (con ellos) no puede ser el patrimonio del accionista."""
    def fy(v):
        return {"units": {"USD": [{"fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "val": v}]}}
    bn = {"ProfitLoss": fy(3_235_000_000), "ProfitLossAttributableToOwnersOfParent": fy(1_307_000_000), "Equity": fy(1)}
    assert _concepts(F.sec_ifrs_metric_map_for(bn), "total_equity") == ["EquityAttributableToOwnersOfParent"]
    igual = {"ProfitLoss": fy(5), "ProfitLossAttributableToOwnersOfParent": fy(5), "Equity": fy(1)}
    assert _concepts(F.sec_ifrs_metric_map_for(igual), "total_equity")[-1] == "Equity"


def test_tir_dice_atribuible_no_verificable_con_solo_el_total(monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    import app.services.user_sotp_service as us
    from app.services import shareholder_irr_service as svc

    def c(v, y, metric, unit="CAD"):
        return {"value": v, "unit": unit, "period": f"{y}-12-31:FY", "metric": metric, "source_type": "SEC", "is_reported": True}

    ys = [2023, 2024, 2025]
    annual = {
        "revenue": {y: c(v * 1e6, y, "revenue") for y, v in zip(ys, (36_000.0, 35_000.0, 38_000.0), strict=True)},
        "operating_income": {y: c(v * 1e6, y, "operating_income") for y, v in zip(ys, (11_000.0, 10_000.0, 12_000.0), strict=True)},
        "depreciation_amortization": {y: c(v * 1e6, y, "da") for y, v in zip(ys, (6_000.0, 6_200.0, 6_500.0), strict=True)},
        "net_income_total": {y: c(v * 1e6, y, "net_income_total") for y, v in zip(ys, (8_200.0, 6_100.0, 10_820.0), strict=True)},
        "shares_diluted": {y: c(2_100e6, y, "shares_diluted", "shares") for y in ys},
    }
    point = {"cash_and_equivalents": c(673e6, 2025, "cash"), "total_debt": c(16_617e6, 2025, "total_debt")}
    monkeypatch.setattr(svc, "company_facts", lambda db, company: (annual, point))
    monkeypatch.setattr(us, "_price", lambda db, company: (45.0, "CAD", "2026-11-06"))
    company = SimpleNamespace(ticker="CNQ", currency="CAD", sector="Energy", industry="Oil & Gas E&P",
                              company_type="", sic_code=1311)
    sp, _h, warnings, cites = svc.starting_point(None, company, today=date(2026, 11, 8))  # type: ignore[arg-type]
    # antes (#4775): el total 10.820 M entraba como beneficio del accionista; ahora es N/D con motivo
    assert sp.net_income is None
    assert any("atribuible no verificable" in w for w in warnings)
    assert cites["attributable_unverified"]["reason"] == "atribuible no verificable"
