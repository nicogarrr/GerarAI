"""Filers IFRS de la SEC (40-F/20-F) sin minoritarios: beneficio, patrimonio y deuda.

Antes: CNQ (40-F, CAD) solo etiqueta ifrs-full ProfitLoss / Equity / Borrowings; el mapa pedía lo
atribuible a la dominante y no había deuda total, así que la TIR salía «sin beneficio positivo» y
«deuda sin dato: se toma 0». Con minoritarios (BN) el respaldo no debe activarse.
"""
from __future__ import annotations

from app.services import financial_ingestion_service as F


def _concepts(m, metric):
    return {k: c for k, c, _u in m}[metric]


def test_sin_minoritarios_usa_profitloss_y_equity_de_respaldo():
    m = F.sec_ifrs_metric_map_for({"ProfitLoss": {"units": {}}, "Equity": {"units": {}}})
    assert _concepts(m, "net_income") == ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"]
    assert _concepts(m, "total_equity") == ["EquityAttributableToOwnersOfParent", "Equity"]
    assert _concepts(m, "total_debt") == ["Borrowings"]


def test_con_minoritarios_no_hay_respaldo():
    m = F.sec_ifrs_metric_map_for({"ProfitLoss": {}, "NoncontrollingInterests": {"units": {"USD": [{}]}}})
    assert _concepts(m, "net_income") == ["ProfitLossAttributableToOwnersOfParent"]
    assert _concepts(m, "total_equity") == ["EquityAttributableToOwnersOfParent"]


def test_borrowings_es_el_total_sin_componer():
    e = {"val": 16617e6, "end": "2025-12-31", "accn": "a", "form": "40-F", "filed": "2026-03-01", "fy": 2025, "fp": "FY"}
    out = F._merge_for_metric({"Borrowings": {"2025-12-31": e}}, "total_debt")
    assert float(out["2025-12-31"]["val"]) == 16617e6


def test_reglas_sec_versionadas():
    assert F.SEC_INGESTION_RULES_VERSION >= 5


def test_atribuible_distinto_del_total_es_minoritarios_aunque_no_se_etiqueten():
    """BN 40-F: no etiqueta conceptos de minoritarios, pero su beneficio atribuible (1.307 M) no es el
    total (3.235 M): hay minoritarios y Equity (con ellos) no puede ser el patrimonio del accionista."""
    def fy(v):
        return {"units": {"USD": [{"fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "val": v}]}}
    bn = {"ProfitLoss": fy(3_235_000_000), "ProfitLossAttributableToOwnersOfParent": fy(1_307_000_000), "Equity": fy(1)}
    assert _concepts(F.sec_ifrs_metric_map_for(bn), "total_equity") == ["EquityAttributableToOwnersOfParent"]
    igual = {"ProfitLoss": fy(5), "ProfitLossAttributableToOwnersOfParent": fy(5), "Equity": fy(1)}
    assert _concepts(F.sec_ifrs_metric_map_for(igual), "total_equity")[-1] == "Equity"
