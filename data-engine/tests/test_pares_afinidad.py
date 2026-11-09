"""Comparables afines por negocio dentro del grupo SIC (regla «afinidad-negocio-v1») y preingresos por ejercicios
publicados («preingresos-ejercicios-v1»), 9-nov-2026.

- El SIC junta satélites con equipos de red y defensa (NOK, UI, TDY, DRS como pares de ASTS): la afinidad compara
  la descripción de negocio del informe anual en la SEC (TF-IDF dentro del grupo, coseno) y la capa afín va
  antes que la capa SIC.
- L3Harris salía «preingresos» porque su último ejercicio (año de 52/53 semanas, cierre 2-ene-2026) tenía
  beneficio cargado y no ingresos: un ejercicio sin dato no es un ejercicio sin ingresos, y los ejercicios se
  cuentan por su mes nominal (el cierre del 2-ene-2026 es el ejercicio 2025).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services import business_affinity as ba
from app.services import pre_revenue_valuation as svc
from app.services import shareholder_irr_service as irr
from app.valuation import pre_revenue_irr as R

TODAY = date(2026, 11, 9)

FILLER = " ".join(["Our operations are described below."] * 200)


def _doc(body: str) -> str:
    return ("<html><body><table><tr><td>Item 1. Business</td><td>2</td></tr><tr><td>Item 1A. Risk Factors</td>"
            f"<td>20</td></tr></table><p>ITEM 1. B<span>USINESS</span></p><p>{body}</p>"
            "<p>See Item 1A. Risk Factors for more.</p>"
            f"<p>{FILLER}</p><p>Item 1A. Risk Factors</p><p>Risks text that is not business.</p></body></html>")


def test_business_section_skips_index_and_inline_cross_references():
    text = ba.plain_text(_doc("We build satellites for direct-to-cellular broadband."))
    sec = ba.business_section(text)
    assert sec is not None and "direct-to-cellular" in sec       # el índice (corto) no gana
    assert "See Item 1A" in sec                                   # una referencia en mitad del texto no corta
    assert "Risks text" not in sec                                # el encabezado real sí corta


def test_describe_uses_latest_annual_report_and_falls_back_to_whole_document():
    subs = ('{"filings":{"recent":{"form":["8-K","10-K"],"accessionNumber":["1","0001-26-000002"],'
            '"primaryDocument":["a.htm","k.htm"],"filingDate":["2026-03-01","2026-02-20"]}}}')
    got = {}

    def get(url):
        got.setdefault("urls", []).append(url)
        return subs if "submissions" in url else _doc("Satellites spectrum constellation launch.")

    d = ba.describe(1780312, "AST SpaceMobile", get)
    assert d["form"] == "10-K" and d["source"].endswith("/1780312/000126000002/k.htm")
    assert "satellites" in d["tokens"] and "spacemobile" not in d["tokens"]   # sin el propio nombre
    assert len(got["urls"]) == 2                                             # dos peticiones a la SEC
    # 20-F con índice de referencias cruzadas (sin encabezado de negocio): documento entero.
    d2 = ba.describe(1, None, lambda u: subs.replace("10-K", "20-F") if "submissions" in u
                     else "<p>" + "networks optical mobile " * 400 + "</p>")
    assert d2["scope"].startswith("documento completo") and "optical" in d2["tokens"]
    assert ba.describe(1, None, lambda u: '{"filings":{"recent":{}}}')["missing"] == "sin 10-K ni 20-F en la SEC"


SAT = "satellite constellation spectrum orbit launch broadband cellular coverage gateway terminals"
NET = "networks optical routers switching enterprise wifi firmware chipsets backhaul cloud"
DEF = "defense contracts navy missile sensors government radar tactical appropriations budget"


def test_affine_sets_rank_business_neighbours_first():
    docs = {1: (SAT + " direct").split() * 3, 2: (SAT + " maritime").split() * 3, 3: (SAT + " aviation").split() * 3,
            4: NET.split() * 3, 5: (NET + " wifi").split() * 3, 6: DEF.split() * 3, 7: (DEF + " radar").split() * 3}
    sets = ba.affine_sets(docs)
    assert ba.keep_count(6) == 6 and ba.keep_count(60) == 15 and ba.keep_count(200) == ba.MAX_KEEP
    top = [k for k, _s in sets[1]]
    assert set(top[:2]) == {2, 3}                                  # los satélites, antes que redes o defensa
    assert all(s > 0 for _k, s in sets[1]) and 4 not in top[:2] and 6 not in top[:2]
    co = SimpleNamespace(factor_tags=["space", "sic:4899", "afin:9:0.5000"])
    assert ba.tag_affine(co, [(2, 0.31), (3, 0.3)])
    assert co.factor_tags == ["space", "sic:4899", "afin:2:0.3100", "afin:3:0.3000"]
    assert ba.affine_from_tags(co) == {2: 0.31, 3: 0.3} and not ba.tag_affine(co, [(2, 0.31), (3, 0.3)])


def _co(i, ticker, sic_code, cik, tags=()):
    return SimpleNamespace(id=i, ticker=ticker, name=ticker, cik=str(cik), sector="x", industry="x",
                           exchange="NASDAQ", factor_tags=[f"sic:{sic_code}", *tags], company_type="operating")


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, _q):
        return SimpleNamespace(all=lambda: list(self.rows))

    def rollback(self):
        return None


def _patch(monkeypatch, caps, mult):
    from app.services import peer_comparison_service as pcs

    monkeypatch.setattr(pcs.PeerComparisonService, "_find_peers", lambda self, db, c, n: ([], "x", {}))
    monkeypatch.setattr(pcs.PeerComparisonService, "_latest_market_caps_usd", lambda self, db, ids: caps)
    monkeypatch.setattr(pcs, "_same_issuer", lambda a, b: False)
    monkeypatch.setattr(svc, "_mature_multiple",
                        lambda _db, p, _t, memo, excluded=None: R.PeerMultiple(p.ticker, None, mult[p.ticker] * 100, 100.0))


def test_affine_tier_goes_before_sic_tier_and_keeps_size_band(monkeypatch):
    target = _co(1, "ASTS", 4899, 100, tags=["afin:103:0.25", "afin:104:0.22", "afin:105:0.20", "afin:106:0.19"])
    rows = [_co(3, "GSAT", 4899, 103), _co(4, "VSAT", 3663, 104), _co(5, "IRDM", 4899, 105),
            _co(6, "KVHI", 3663, 106),                                   # afín pero 200 veces más pequeña
            _co(7, "NOK", 3663, 107), _co(8, "UI", 3663, 108), _co(9, "TDY", 3812, 109)]
    caps = {1: 20e9, 3: 10e9, 4: 13e9, 5: 7e9, 6: 0.1e9, 7: 37e9, 8: 35e9, 9: 30e9}
    _patch(monkeypatch, caps, {"GSAT": 39.0, "VSAT": 2.9, "IRDM": 7.7, "KVHI": 0.6, "NOK": 1.9, "UI": 10.7,
                               "TDY": 4.9})
    got, layer, missing, tried = svc.mature_peers(_FakeDB([target, *rows]), target, TODAY, [])
    assert missing is None and "de negocio afín" in layer and svc.AFFINITY_RULE in layer
    assert [p.ticker for p in got] == ["GSAT", "VSAT", "IRDM"]      # sin NOK/UI/TDY ni la diminuta KVHI
    assert tried[0]["capa"] == layer


def test_without_affinity_tags_the_sic_tier_is_unchanged(monkeypatch):
    target = _co(1, "ASTS", 4899, 100)
    rows = [_co(3, "GSAT", 4899, 103), _co(7, "NOK", 3663, 107), _co(9, "TDY", 3812, 109)]
    _patch(monkeypatch, {1: 20e9, 3: 10e9, 7: 37e9, 9: 30e9}, {"GSAT": 39.0, "NOK": 1.9, "TDY": 4.9})
    got, layer, _m, _t = svc.mature_peers(_FakeDB([target, *rows]), target, TODAY, [])
    assert "afín" not in layer and layer.endswith("las 12 de capitalización más cercana")
    assert sorted(p.ticker for p in got) == ["GSAT", "NOK", "TDY"]


def _cite(v, end):
    return {"value": v * 1e6, "period": f"{end}:FY"}


def test_fiscal_year_by_nominal_month():
    assert irr._fiscal_year("2026-01-02:FY") == 2025       # 52/53 semanas: ejercicio 2025
    assert irr._fiscal_year("2025-01-03:FY") == 2024
    assert irr._fiscal_year("2025-12-28:FY") == 2025
    assert irr._fiscal_year("2023-01-01:FY") == 2022 and irr._fiscal_year("2023-12-31:FY") == 2023  # ya no chocan
    assert irr._fiscal_year("x:FY") is None


def test_missing_revenue_in_last_year_is_not_pre_revenue():
    co = SimpleNamespace(industry="Aerospace & defense", sector="Industrials", ticker="X", company_type="operating",
                         valuation_model="", factor_tags=[])
    annual = {"revenue": {2023: _cite(19419, "2023-12-29"), 2024: _cite(21325, "2025-01-03")},
              "net_income": {2023: _cite(1227, "2023-12-29"), 2024: _cite(1502, "2025-01-03"),
                             2025: _cite(1606, "2026-01-02")}}
    kind, why = irr.company_kind(co, annual)
    assert kind == "operating", why
    # Un solo ejercicio bajo tras uno alto no basta; dos bajos, sí.
    one_low = {"revenue": {2024: _cite(900, "2024-12-31"), 2025: _cite(20, "2025-12-31")}}
    assert irr.company_kind(co, one_low)[0] == "operating"
    two_low = {"revenue": {2024: _cite(30, "2024-12-31"), 2025: _cite(20, "2025-12-31")}}
    assert irr.company_kind(co, two_low) == ("pre_revenue", "ingresos de 2024 y 2025 por debajo de 50 M")
    none = {"net_income": {2025: _cite(-80, "2025-12-31")}}
    assert irr.company_kind(co, none) == ("pre_revenue", "sin ingresos publicados en ningún ejercicio")
