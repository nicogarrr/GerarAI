"""Ruta de valoración de preingresos / quema caja (9-nov-2026, «ASTS sin TIR ni nada»).

Antes: una empresa clasificada como «sin beneficio (preingresos o quema caja)» salía con TIR N/D, múltiplo
N/D y «0 comparables calculados» (el servicio devolvía antes de buscar comparables). Ahora: runway en
trimestres, dilución histórica y proyectada hasta el break-even al precio actual, y TIR por escenarios desde
ingresos a 3–5 años (firmas, consenso de prensa, guía o cartera contratada) × EV/ventas de comparables
maduros con la misma fórmula, menos la dilución. Un input que falta deja ESE escenario N/D con su motivo.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import pre_revenue_valuation as svc
from app.services.expert_team import thesis_v2 as T
from app.valuation import pre_revenue_irr as R

TODAY = date(2026, 11, 9)


def _anchor(year=2028, base=1730.0, low=None, high=None, source="consenso_prensa"):
    return R.RevenueAnchor(year, base, low, high, source, f"{source} {year}", {"url": "https://x/y"})


def _scen(**kw):
    args = dict(today=TODAY, price=32.33, shares=256.0, cash=4588.0, debt=2972.0, minorities=504.0, hybrids=0.0,
                fcf=-1136.0, dilution_hist=0.675, anchor=_anchor(), anchor_missing=None,
                peers={"p25": 1.64, "median": 3.01, "p75": 6.94, "n": 17.0}, peers_missing=None, last_fy=2025)
    return R.scenarios(**(args | kw))


def test_runway_en_trimestres_y_motivos():
    assert R.runway(400.0, -400.0)["quarters"] == pytest.approx(4.0)
    assert R.runway(400.0, 50.0)["quarters"] is None and R.runway(400.0, 50.0)["quarterly_burn"] == 0.0
    assert R.runway(None, -10.0)["missing"] == "sin caja en el filing"
    assert R.runway(10.0, None, missing="sin capex")["missing"] == "sin capex"


def test_ancla_la_mas_lejana_de_3_a_5_anos_y_por_orden_de_fuente():
    anchors = [_anchor(2026, 170.0), _anchor(2028, 1730.0, source="consenso_prensa"),
               _anchor(2028, 1500.0, 1200.0, 1900.0, source="analistas"), _anchor(2031, 9999.0)]
    a, why = R.choose_anchor(anchors, 2025)
    assert why is None and a.year == 2028 and a.source == "analistas"  # 2026 está fuera; 2031 > +5
    a, _ = R.choose_anchor([_anchor(2029, 900.0, source="guia"), _anchor(2028, 800.0)], 2025)
    assert a.year == 2029 and a.source == "guia"
    a, _ = R.choose_anchor([_anchor(2028, 18.7, source="backlog")], 2025)
    assert a.source == "backlog"
    a, why = R.choose_anchor([_anchor(2026, 170.0)], 2025)
    assert a is None and "sin consenso de ingresos 2028–2030" in why and "cartera contratada" in why


def test_cuantiles_con_interpolacion():
    st = R.peer_stats([R.PeerMultiple(t, None, ev, 1.0) for t, ev in (("A", 1.0), ("B", 2.0), ("C", 3.0), ("D", 4.0))])
    assert st is not None
    assert st["median"] == 2.5 and st["p25"] == pytest.approx(1.75) and st["p75"] == pytest.approx(3.25)
    assert R.peer_stats([R.PeerMultiple("A", None, -5.0, 1.0)]) is None


def test_escenarios_ordenados_y_formula_a_mano():
    s = _scen()
    assert s["bear"]["irr"] < s["base"]["irr"] < s["bull"]["irr"]
    base = s["base"]
    n = R.years_to(TODAY, 2028)
    cum = 1136.0 * n * 0.5
    assert base["cumulative_burn"] == pytest.approx(cum)
    assert base["funding_need"] == 0.0 and base["dilution"] == 0.0  # la caja cubre el consumo + colchón
    equity = 1730.0 * 3.01 + (4588.0 - cum) - 2972.0 - 504.0
    assert base["equity"] == pytest.approx(equity)
    assert base["irr"] == pytest.approx((equity / 256.0 / 32.33) ** (1 / n) - 1)
    # Sin rango propio, ±50 % sobre el ancla.
    assert s["bear"]["revenue"] == pytest.approx(865.0) and s["bull"]["revenue"] == pytest.approx(2595.0)


def test_bajista_sin_hueco_no_diluye_y_con_hueco_toma_la_historica_sin_sumar_caja():
    # v2 (e): con el consumo financiado (hueco 0) no hay dilución en ningún escenario.
    s = _scen()
    bear = s["bear"]
    n = R.years_to(TODAY, 2028)
    assert bear["funding_need"] == 0 and bear["dilution"] == 0 and bear["dilution_from"] == "hueco de financiación"
    # Con hueco, el bajista toma como mínimo la dilución histórica compuesta, y las acciones de más no suman caja.
    s = _scen(cash=1000.0)
    bear = s["bear"]
    assert bear["funding_need"] > 0 and bear["dilution_from"] == "dilución histórica compuesta"
    assert bear["dilution"] == pytest.approx(1.675 ** n - 1)
    assert bear["cash_end"] == pytest.approx(1000.0 + bear["funding_need"] - 1136.0 * n)


def test_hueco_de_financiacion_al_precio_actual():
    s = _scen(cash=100.0, fcf=-200.0, dilution_hist=None, debt=0.0, minorities=0.0, price=10.0, shares=50.0)
    n = R.years_to(TODAY, 2028)
    need = 200.0 * n * 0.5 + 100.0 - 100.0  # consumo acumulado + 6 meses de colchón − caja
    assert s["base"]["funding_need"] == pytest.approx(need)
    assert s["base"]["dilution"] == pytest.approx(need / 10.0 / 50.0)
    assert s["base"]["cash_end"] == pytest.approx(100.0)  # queda exactamente el colchón


def test_input_que_falta_da_nd_con_motivo_y_la_dilucion_sigue():
    s = _scen(anchor=None, anchor_missing="sin consenso de ingresos 2028–2030")
    for k in R.SCENARIOS:
        assert s[k]["irr"] is None and s[k]["missing"].startswith("sin consenso de ingresos 2028")
        assert s[k]["dilution"] is not None  # el resto de la ficha se muestra igual
    s = _scen(peers=None, peers_missing="menos de 3 comparables maduros")
    assert s["base"]["irr"] is None and "comparables maduros" in s["base"]["missing"]
    s = _scen(price=None)
    assert s["base"]["missing"] == "sin precio" and "dilution" not in s["base"]


def test_capital_negativo_es_perdida_total():
    s = _scen(debt=50000.0)
    assert s["base"]["irr"] == -1.0


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, queue):
        self.queue = list(queue)
        self.info = {"tenant_id": 1}

    def scalars(self, _stmt):
        return _Rows(self.queue.pop(0))

    def rollback(self):
        pass


def _co(i, ticker, **kw):
    return SimpleNamespace(id=i, ticker=ticker, name=ticker, cik=None, sector=kw.get("sector", "Comms"),
                           industry=kw.get("industry", "Satellite"), company_type="operating")


def test_comparables_caen_a_capas_mas_anchas_y_lo_dicen(monkeypatch):
    # Una sola consulta (la base con ingresos FY); industria y sector se filtran sobre ella, ordenada por tamaño.
    target = _co(1, "TGT")
    peers_svc = [_co(2, "P1")]
    base = [_co(2, "P1"), _co(3, "P2", industry="Other"), _co(4, "P3", industry="Other", sector="Other"),
            _co(5, "PRE", industry="Other", sector="Other")]
    mature = {"P1": 2.0, "P2": 4.0, "P3": 6.0}

    def fake_mult(_db, peer, _today, memo, *_excluded):
        return R.PeerMultiple(peer.ticker, None, mature[peer.ticker] * 100.0, 100.0) if peer.ticker in mature else None

    from app.services import peer_comparison_service as pcs

    monkeypatch.setattr(svc, "_mature_multiple", fake_mult)
    monkeypatch.setattr(pcs.PeerComparisonService, "_find_peers", lambda self, db, c, n: (peers_svc, "x", {}))
    monkeypatch.setattr(pcs.PeerComparisonService, "_latest_market_caps_usd", lambda self, db, ids: {})
    monkeypatch.setattr(pcs, "_same_issuer", lambda a, b: False)
    got, layer, missing, tried = svc.mature_peers(_FakeDB([base]), target, TODAY)
    assert missing is None and layer.startswith("toda la base no financiera")
    assert sorted(p.ticker for p in got) == ["P1", "P2", "P3"]
    assert [t["maduros"] for t in tried] == [1, 1, 2, 3]
    # Con tres maduros en el sector, se queda en el sector.
    base3 = [_co(2, "P1"), _co(3, "P2", industry="Other"), _co(4, "P3", industry="Other")]
    got, layer, _m, _t = svc.mature_peers(_FakeDB([base3]), target, TODAY)
    assert layer == "mismo sector (Comms)" and len(got) == 3


def _val_with_pre():
    sp = {"price": 32.33, "shares_diluted": 256.0, "revenue": 71.0, "ebitda": -374.0, "net_income": -342.0,
          "cash": 4588.0, "debt": 2972.0, "leases": 0.0, "hybrids": 0.0, "minorities": 504.0, "currency": "USD",
          "basis": "ev_ebitda", "market_cap": 8276.0, "net_debt": -1616.0, "enterprise_value": 7163.0,
          "multiple": None, "margin": None, "sources": {}, "earnings_label": ""}
    rw = {"year": "2025", "cash": 4588.0, "debt": 2972.0, "operating_cash_flow": -72.0, "capex": -1065.0,
          "free_cash_flow": -1136.0, "burn": 1136.0, "months": 48.5, "dilution_cagr": 0.675, "ev_to_cash": 1.6,
          "ev_to_revenue": 101.0, "formulas": {"consumo": "c", "meses": "m", "dilucion": "d"}, "sources": {}}
    scen = _scen()
    pre = {"runway": {"quarters": 16.2, "missing": None}, "scenarios": scen, "formulas": R.FORMULAS,
           "revenue_anchor": {"year": 2028, "label": "consenso citado en prensa, ingresos 2028",
                              "cite": {"url": "https://example.com/a", "as_of": "2026-11-06"}},
           "peer_stats": {"p25": 1.64, "median": 3.01, "p75": 6.94, "n": 17.0},
           "peer_layer": "toda la base no financiera (sin comparables suficientes del sector)",
           "peers": [{"ticker": "AAA", "multiple": 3.0}]}
    return {"status": "not_meaningful", "reason": "sin beneficio", "starting_point": sp, "runway": rw,
            "pre_revenue": pre, "peers": [{"ticker": "AAA", "name": "Aaa", "multiple": 3.0}],
            "method": {"chosen": "caja_runway", "kind": "pre_revenue", "kind_reason": "quema caja",
                       "kind_method": "caja", "discarded": {}}, "citations": {}, "warnings": []}


def test_ficha_pinta_runway_dilucion_y_tir_por_escenario():
    val = _val_with_pre()
    ctx = T.ThesisContext("ASTS", "AST", val, [], [], T.kill_switches(val, []), None, [])
    tb = T.tables(ctx)
    note = tb["escenarios"]
    rows = {r[0]: r[1] for r in note["rows"]}
    assert "TIR por escenarios" in note["title"]
    assert rows["Runway (trimestres)"] == "16,2"
    assert rows["Ingresos 2028 (bajista / base / alcista)"] == "865 M$ / 1.730 M$ / 2.595 M$"
    assert rows["EV/ventas de comparables maduros (p25 / mediana / p75)"] == "1,6x / 3,0x / 6,9x"
    assert rows["TIR anual base hasta 2028"].endswith("%") and rows["TIR anual bajista hasta 2028"].startswith("−")
    assert len(note["links"]) == len(note["rows"])
    med = next(r for r in tb["partida"]["rows"] if r[0] == "Mediana de comparables")
    assert med[1] == "3,0x EV/ventas" and "capa: toda la base" in med[2]
    m = T.thesis_markers(ctx)
    assert m["caja.trimestres"] == "16,2 trimestres" and m["preing.base.tir"].endswith("%")


def test_ficha_sin_ancla_muestra_nd_con_motivo_y_el_resto():
    val = _val_with_pre()
    val["pre_revenue"]["scenarios"] = _scen(anchor=None, anchor_missing="sin consenso de ingresos 2028–2030")
    val["pre_revenue"]["revenue_anchor"] = None
    val["pre_revenue"]["revenue_anchor_missing"] = "sin consenso de ingresos 2028–2030"
    ctx = T.ThesisContext("RRR", "R", val, [], [], T.kill_switches(val, []), None, [])
    rows = {r[0]: r[1] for r in T.tables(ctx)["escenarios"]["rows"]}
    assert rows["TIR anual base hasta 2028"] == "N/D (sin consenso de ingresos 2028–2030)"
    assert rows["Runway (trimestres)"] == "16,2"
    assert "N/D" not in rows["Dilución proyectada hasta el break-even (bajista / base / alcista)"]


def test_sin_ruta_de_preingresos_la_ficha_no_cambia():
    val = _val_with_pre()
    del val["pre_revenue"]
    ctx = T.ThesisContext("ZZZ", "Z", val, [], [], T.kill_switches(val, []), None, [])
    note = T.tables(ctx)["escenarios"]
    assert len(note["rows"]) == 9 and "TIR" not in note["title"]


def test_v2_crecimiento_muy_superior_a_los_maduros_prolonga_hasta_el_ano_5():
    peers = {"p25": 2.0, "median": 4.0, "p75": 6.0, "n": 4.0, "growth_p50": 0.10, "growth_p75": 0.15, "growth_n": 4.0}
    rev, year, trace = R.exit_revenue(1000.0, anchor_year=2028, last_fy=2025, last_revenue=100.0, peers=peers)
    g = (1000.0 / 100.0) ** (1 / 3) - 1
    assert year == 2030 and trace["growth_company"] == pytest.approx(g)
    g29 = g + (0.10 - g) / 2
    assert rev == pytest.approx(1000.0 * (1 + g29) * 1.10)
    assert "estimación propia" in trace["fade"]
    # Creciendo como los maduros, el múltiplo se aplica al año del ancla.
    rev, year, _t = R.exit_revenue(115.0, anchor_year=2028, last_fy=2025, last_revenue=100.0, peers=peers)
    assert (rev, year) == (115.0, 2028)
    # Ancla ya en el año 5 y crecimiento muy superior: N/D, no un múltiplo sin sentido.
    rev, year, _t = R.exit_revenue(1000.0, anchor_year=2030, last_fy=2025, last_revenue=10.0, peers=peers)
    assert rev is None
    s = R.scenarios(today=TODAY, price=10.0, shares=100.0, cash=1000.0, debt=0.0, minorities=0.0, hybrids=0.0,
                    fcf=-10.0, dilution_hist=None, anchor=R.RevenueAnchor(2030, 1000.0, None, None, "consenso_prensa", "x", {}),
                    anchor_missing=None, peers=peers, peers_missing=None, last_fy=2025, last_revenue=10.0)
    assert s["base"]["irr"] is None and "el múltiplo maduro no aplica" in s["base"]["missing"]
