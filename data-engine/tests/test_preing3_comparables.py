"""Comparables por grupo de industria SIC (regla «comparables-sic-v1», 9-nov-2026): ASTS (SIC 4899) se compara
con espacio y satélite (3663, 3760–3769, 3812, 4899) por capitalización cercana, no con SNAP/PINS/META/GOOGL;
una privada (SpaceX) sale «N/D (privada, sin cotización)» y nunca da múltiplo; la ingesta descubre las
cotizadas del grupo por código SIC en la SEC, sin lista de tickers."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services import industry_peer_ingest as ipi
from app.services import pre_revenue_valuation as svc
from app.services import sic_classification as sic
from app.valuation import pre_revenue_irr as R

TODAY = date(2026, 11, 9)


def test_sic_group_and_tag():
    for code in (4899, 3663, 3761, 3812):
        assert sic.industry_group(code)[0] == "espacio y satélite"
    assert sic.industry_group(7370) is None and sic.industry_group(None) is None
    assert sic.group_label(sic.industry_group(4899)) == "espacio y satélite (SIC 3663, 3760–3769, 3812, 4899)"
    co = SimpleNamespace(factor_tags=["space", "sic:1234"], industry="Satellite telecom")
    assert sic.tag_sic(co, 4899) and co.factor_tags == ["space", "sic:4899"]
    assert not sic.tag_sic(co, 4899)
    assert sic.company_sic(co) == 4899
    assert sic.company_sic(SimpleNamespace(factor_tags=[], industry="Services-computer (SIC 7370)")) == 7370


ATOM = "<feed>" + "".join(f"<entry><cik>{c:010d}</cik></entry>" for c in (1780312, 1819994, 999)) + "</feed>"
TICKERS = {"fields": ["cik", "name", "ticker", "exchange"],
           "data": [[1780312, "AST SpaceMobile", "ASTS", "Nasdaq"], [1819994, "Rocket Lab", "RKLB", "Nasdaq"],
                    [999, "Pink Co", "PINK", "OTC"]]}


def test_ingest_discovers_listed_issuers_by_sic_code():
    assert ipi.parse_ciks(ATOM) == [1780312, 1819994, 999]
    calls: list[str] = []

    def get(url):
        calls.append(url)
        return ATOM if "SIC=4899&" in url else "<feed></feed>"

    got = ipi.group_candidates(((4899, 4899), (3760, 3761)), get, TICKERS)
    assert [r["ticker"] for r in got] == ["ASTS", "RKLB"]          # el OTC (no regulado) no entra
    assert all(r["sic"] == 4899 for r in got)
    assert len(calls) == 3 and all("output=atom" in u for u in calls)


def _co(i, ticker, sic_code=None, exchange="NASDAQ", cik="1", sector="Communication Services", industry="x"):
    return SimpleNamespace(id=i, ticker=ticker, name=ticker, cik=cik, sector=sector, industry=industry,
                           exchange=exchange, factor_tags=[f"sic:{sic_code}"] if sic_code else [],
                           company_type="operating")


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, _q):
        return SimpleNamespace(all=lambda: list(self.rows))

    def rollback(self):
        return None


def test_group_tier_by_nearest_cap_and_private_peer_excluded(monkeypatch):
    from app.services import peer_comparison_service as pcs

    target = _co(1, "ASTS", 4899)
    space = [_co(2, "RKLB", 3760), _co(3, "IRDM", 4899), _co(4, "VSAT", 4899), _co(5, "GSAT", 4899),
             _co(6, "QCOM", 3663)]
    social = [_co(7, "META", 7370), _co(8, "PINS", 7370), _co(9, "SNAP", 7370)]
    spacex = _co(10, "SPACEX", None, exchange="PRIVATE", cik=None)
    caps = {1: 12e9, 2: 25e9, 3: 3e9, 4: 4e9, 5: 6e9, 6: 180e9, 7: 1.6e12, 8: 20e9, 9: 15e9}
    mult = {"RKLB": 30.0, "IRDM": 5.0, "VSAT": 1.6, "GSAT": 10.0, "QCOM": 4.0, "META": 8.0, "PINS": 5.0,
            "SNAP": 2.6}
    monkeypatch.setattr(pcs.PeerComparisonService, "_find_peers", lambda self, db, c, n: ([spacex, *social[:2]], "x", {}))
    monkeypatch.setattr(pcs.PeerComparisonService, "_latest_market_caps_usd", lambda self, db, ids: caps)
    monkeypatch.setattr(pcs, "_same_issuer", lambda a, b: False)
    monkeypatch.setattr(svc, "GROUP_NEAREST", 4)

    def fake_mult(_db, peer, _today, memo, excluded=None):
        if peer.ticker == "SPACEX":  # la ruta real: sin cotización ni CIK → excluida
            return svc.__wrapped_mature__(_db, peer, _today, memo, excluded)
        return R.PeerMultiple(peer.ticker, None, mult[peer.ticker] * 100.0, 100.0)

    monkeypatch.setattr(svc, "__wrapped_mature__", svc._mature_multiple, raising=False)
    monkeypatch.setattr(svc, "_mature_multiple", fake_mult)
    excluded: list = []
    got, layer, missing, _tried = svc.mature_peers(_FakeDB([*space, *social, spacex]), target, TODAY, excluded)
    assert missing is None and layer.startswith("mismo grupo de industria: espacio y satélite")
    # Las 4 de capitalización más cercana a 12 000 M: GSAT 6, VSAT 4, RKLB 25, IRDM 3 (QCOM, 180 000 M, fuera).
    assert sorted(p.ticker for p in got) == ["GSAT", "IRDM", "RKLB", "VSAT"]
    assert not {"SNAP", "PINS", "META", "GOOGL"} & {p.ticker for p in got}
    assert excluded == [{"ticker": "SPACEX", "name": "SPACEX", "motivo": "N/D (privada, sin cotización)"}]


def test_private_peer_never_gives_a_multiple():
    excluded: dict = {}
    memo: dict = {}
    spacex = _co(10, "SPACEX", None, exchange="PRIVATE", cik=None)
    assert svc._mature_multiple(None, spacex, TODAY, memo, excluded) is None
    assert excluded == {10: "N/D (privada, sin cotización)"}
    assert svc._unlisted_reason(_co(11, "X", exchange="NASDAQ"), ValueError("sin precio")) == \
        "N/D (sin precio de mercado guardado)"
    assert svc._unlisted_reason(_co(11, "X"), ValueError("sin ingresos")) is None
