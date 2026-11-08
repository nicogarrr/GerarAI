"""Método según el tipo de empresa (tesis v2 sobre toda la watchlist de Nico, 8-nov-2026).

Antes: CB y KKR iban por PER aunque lo que compone en una aseguradora o un holding es el valor contable;
CPT (REIT) salía con ingresos de 13 M$ (la etiqueta «Revenues» acaba en 2016) y un margen del 2.288 %;
KKR quedaba «sin acciones diluidas» con la portada del 10-Q delante; las biotech (RXRX, NAUT, ABCL, IBRX)
y ASTS quedaban sin tesis («not_applicable»); HIMS salía con TIR ponderada «None» porque el escenario
bajista perdía todo y la TIR de una pérdida total no se calculaba.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services import financial_ingestion_service as fis
from app.services.expert_team import thesis_v2 as T
from app.services.shareholder_irr_service import company_kind
from app.valuation import shareholder_irr as engine
from app.valuation import shareholder_irr_rules as rules


def _c(cite_value: float, period: str = "2025-12-31:FY", metric: str = "x") -> dict:
    return {"value": cite_value * 1e6, "period": period, "metric": metric}


def _company(**kw):
    base = {"ticker": "ZZZ", "company_type": "operating", "valuation_model": "unassigned", "factor_tags": [],
            "industry": "Unknown", "special_risks": [], "currency": "USD"}
    return SimpleNamespace(**(base | kw))


def test_valor_contable_compone_al_roe():
    # P/VC 1, ROE 10 %, reparte la mitad: el valor contable crece al 5 % y la TIR es la del ROE sobre el
    # valor contable de cierre (1,05 × 1,05 − 1), exacta.
    sp = engine.StartingPoint(price=100.0, shares_diluted=1.0, revenue=100.0, ebitda=None, net_income=10.0, basis="pb")
    assert abs(sp.multiple - 1.0) < 1e-12 and abs(sp.margin - 0.10) < 1e-12
    d = engine.Drivers(organic_growth=0.05, organic_growth_late=0.05, margin_target=0.10, cash_conversion=0.5,
                       dividend_payout=1.0, buyback_payout=0.0, exit_multiple=1.0)
    res = engine.evaluate(sp, d)
    assert abs(res[10].irr - 0.1025) < 1e-6
    comps = res[10].components
    assert abs(sum(comps.values()) - res[10].irr) < 1e-9
    assert abs(comps["multiplo"]) < 1e-12 and abs(comps["margen"]) < 1e-12


def test_reglas_pb_crecimiento_es_roe_por_retencion():
    sp = engine.StartingPoint(price=150.0, shares_diluted=1.0, revenue=100.0, ebitda=None, net_income=12.0, basis="pb")
    hist = rules.History(years=[2023, 2024, 2025], revenue=[80.0, 90.0, 100.0], earnings=[8.0, 11.0, 12.0],
                         operating_cash_flow=[4.0, 4.4, 6.0], capex=[None] * 3, dividends=[2.0, 2.2, 3.0],
                         buybacks=[2.0, 2.2, 3.0], acquisitions=())
    out = rules.build_scenarios(sp, hist)
    base = out.drivers["base"]
    assert abs(base.organic_growth - base.margin_target * (1 - base.cash_conversion)) < 1e-12
    assert out.drivers["bear"].margin_target <= base.margin_target <= out.drivers["bull"].margin_target
    assert out.drivers["bear"].exit_multiple >= 0.5 and out.drivers["bull"].exit_multiple <= 5.0


def test_perdida_total_tiene_tir_menos_cien():
    assert engine.irr([-10.0, 0.0, 0.0]) == -1.0
    assert engine.irr([-10.0, 0.0, 11.0]) is not None


def test_tipo_por_hechos_cuando_la_ficha_no_clasifica():
    insurer = {"revenue": {2025: _c(59000)}, "earned_premiums": {2025: _c(53000)}, "net_income": {2025: _c(10000)}}
    assert company_kind(_company(), insurer)[0] == "insurer"
    # Una industria conocida que no es seguros manda: las primas de salud no hacen aseguradora a UNH.
    assert company_kind(_company(industry="Health Care"), insurer)[0] == "operating"
    reit = {"revenue": {2016: _c(13)}, "lease_income": {2025: _c(1573)}, "net_income": {2025: _c(384)}}
    assert company_kind(_company(industry="Real Estate"), reit)[0] == "real_estate"
    tiny = {"revenue": {2025: _c(3)}, "net_income": {2025: _c(-80)}}
    assert company_kind(_company(), tiny)[0] == "pre_revenue"
    burner = {m: {2024: _c(v), 2025: _c(v)} for m, v in (
        ("revenue", 300), ("operating_income", -200), ("depreciation_amortization", 20), ("net_income", -210),
        ("operating_cash_flow", -150), ("capital_expenditure", 30))}
    kind, why = company_kind(_company(), burner)
    assert kind == "pre_revenue" and "quema caja" in why
    assert company_kind(_company(company_type="biotech_pre_fcf", factor_tags=["pre_fcf"]), {"revenue": {2025: _c(400)}})[0] == "pre_revenue"


def test_plusvalias_mapeadas_y_version_de_reglas():
    concepts = {c for metric, cs, _ in fis.SEC_METRIC_MAP if metric == "gain_on_sale_real_estate" for c in cs}
    assert "GainLossOnDispositionOfAssets" in concepts
    assert fis.SEC_INGESTION_RULES_VERSION >= 4


def _runway_val():
    sp = {"price": 10.0, "shares_diluted": 100.0, "revenue": 20.0, "ebitda": -150.0, "net_income": -160.0, "cash": 300.0,
          "debt": 50.0, "leases": 0.0, "hybrids": 0.0, "minorities": 0.0, "currency": "USD", "basis": "ev_ebitda",
          "market_cap": 1000.0, "net_debt": -250.0, "enterprise_value": 750.0, "multiple": None, "margin": None,
          "earnings_label": ""}
    rw = {"year": "2025", "cash": 300.0, "debt": 50.0, "operating_cash_flow": -140.0, "capex": 10.0, "free_cash_flow": -150.0,
          "burn": 150.0, "months": 24.0, "dilution_cagr": 0.15, "ev_to_cash": 2.5, "ev_to_revenue": 37.5,
          "formulas": {"consumo": "c", "meses": "m", "dilucion": "d"}, "sources": {}}
    return {"status": "not_meaningful", "reason": "sin beneficio", "starting_point": sp, "runway": rw,
            "method": {"chosen": "caja_runway", "kind": "pre_revenue", "kind_reason": "quema caja",
                       "kind_method": "caja", "discarded": {}}, "citations": {}, "warnings": []}


def test_preingresos_tienen_tabla_de_caja_y_umbrales():
    val = _runway_val()
    ctx = T.ThesisContext("ZZZ", "Zeta", val, [], [], T.kill_switches(val, []), None, [])
    keys = {s["key"]: s for s in ctx.switches}
    assert keys["runway"]["status"] == "ok" and keys["dilucion_anual"]["status"] == "saltado"
    tb = T.tables(ctx)
    rows = {r[0]: r[1] for r in tb["escenarios"]["rows"]}
    assert rows["Meses de margen (runway)"] == "24" and rows["Consumo anual de caja"].startswith("150")
    m = T.thesis_markers(ctx)
    assert m["caja.meses"] == "24 meses" and m["metodo.tipo"].startswith("empresa sin beneficio")
    assert "Caja, consumo y dilución" in [r[0] for r in tb["metodos"]["rows"]][0]
