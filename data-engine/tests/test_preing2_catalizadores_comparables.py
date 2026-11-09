"""Catalizadores oficiales, sector por SIC y orden por capitalización (carril preing-2, reglas pre-registradas)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.services import official_catalysts as oc
from app.services import sic_classification as sic
from app.services.expert_team.thesis_v2 import catalyst_table

FIXTURE = Path(__file__).parent / "fixtures" / "catalysts" / "rakuten_press_2026_1109_01.html"
RAKUTEN_URL = "https://corp.rakuten.co.jp/news/press/2026/1109_01.html"
ASTS = SimpleNamespace(name="AST SpaceMobile, Inc.", ticker="ASTS", ir_url="https://investors.ast-science.com")


def _rakuten():
    html = FIXTURE.read_bytes()
    text, h1, flat = oc.page_text(html)
    return html, text, h1, flat


def test_counterparty_press_release_is_official_and_dated_from_the_page():
    html, text, h1, flat = _rakuten()
    assert oc.official_kind(RAKUTEN_URL, text=flat) == "corporativa"  # sala de prensa y la editora se nombra
    assert oc.page_date(flat, h1, RAKUTEN_URL, html) == date(2026, 11, 9)  # no la del acuerdo (6-11) ni la del buscador


def test_rakuten_jv_and_grant_without_amount_for_ast():
    html, text, h1, flat = _rakuten()
    cats = oc.extract(text, terms=oc.company_terms(ASTS), published=date(2026, 11, 9), url=RAKUTEN_URL,
                      publisher="corp.rakuten.co.jp", source_kind="corporativa")
    by = {c.kind: c for c in cats}
    assert {"jv", "subvencion"} <= set(by)
    assert "最大1,480億円" in by["subvencion"].amounts  # citado tal cual
    assert "51％" in by["jv"].summary and "49％" in by["jv"].summary  # literal, sin traducir
    # La subvención es para «Rakuten AST» (la JV), no para AST: importe para la empresa N/D.
    assert all(c.amount_for_company is None and c.amount_reason == oc.ND_AMOUNT for c in cats)


def test_media_is_never_official():
    for url in ("https://www.nikkei.com/article/DGXZQO1", "https://k-tai.watch.impress.co.jp/docs/news/1.html",
                "https://finance.yahoo.com/news/press-release-x.html"):
        assert oc.official_kind(url, text="Rakuten nikkei impress yahoo") is None
    assert oc.official_kind("https://www.businesswire.com/news/home/1/en/x", text="") == "wire"
    assert oc.official_kind("https://investors.ast-science.com/news-releases/x", ir_hosts=["investors.ast-science.com"]) == "ir"


def test_attributable_amount_needs_the_company_by_its_own_name():
    terms = oc.company_terms(ASTS)
    yes = "AST SpaceMobile was awarded a contract valued at $43 million by the Space Development Agency."
    no = "Rakuten AST will receive up to $970 million in subsidies under the grant."
    for text, expected in ((yes, "$43 million"), (no, None)):
        [c] = oc.extract(text, terms=terms, published=date(2026, 1, 2), url="https://www.businesswire.com/x",
                         publisher="www.businesswire.com", source_kind="wire")
        assert c.amount_for_company == expected
    assert oc.amount_value("最大1,480億円") == 1.48e11
    assert oc.amount_value("$1.2 billion") == 1.2e9


def test_catalyst_table_rows_carry_date_source_and_nd():
    rows = [{"date": "2026-11-09", "kind_label": "subvención o adjudicación", "publisher": "corp.rakuten.co.jp",
             "summary": "literal", "amounts": ["最大1,480億円"], "amount_for_company": None,
             "amount_reason": oc.ND_AMOUNT, "url": RAKUTEN_URL}]
    t = catalyst_table(rows)
    assert t["rows"][0][-1] == "importe para la empresa N/D (no publicado)"
    assert t["links"] == [RAKUTEN_URL]
    assert catalyst_table([])["rows"] == []


def test_sic_sector_calibrated_by_the_base_then_declared_table():
    calib = sic.calibration([(7370, "Communication Services"), (7370, None), (2834, "Health Care")])
    assert calib == {7370: "Communication Services", 2834: "Health Care"}
    got = sic.classify(7370, "SERVICES-COMPUTER PROGRAMMING, DATA PROCESSING, ETC.", calib)
    assert got["sector"] == "Communication Services"
    assert got["industry"] == "Services-computer programming, data processing, etc. (SIC 7370)"
    assert sic.classify(3674, "SEMICONDUCTORS & RELATED DEVICES", {})["sector"] == "Information Technology"
    assert sic.declared_sector(9999) is None


def test_sic_never_overwrites_curated_and_industry_sector_wins():
    curated = SimpleNamespace(sector="Communication Services", industry="Satellite telecom")
    assert sic.apply(curated, 4899, "COMMUNICATIONS SERVICES, NEC", {}) == {}
    unh = SimpleNamespace(sector="Unknown", industry="Health Care")  # industria de Finnhub ya presente
    assert sic.apply(unh, 6324, "HOSPITAL & MEDICAL SERVICE PLANS", {})["sector"] == "Health Care"
    blank = SimpleNamespace(sector="Unknown", industry="Unknown")
    assert sic.apply(blank, 5070, "WHOLESALE-HARDWARE", {})["sector"] == "Industrials"


def test_broad_peer_layers_are_ranked_by_market_cap(monkeypatch):
    from app.services import pre_revenue_valuation as prv
    from app.services.peer_comparison_service import PeerComparisonService

    cos = [SimpleNamespace(id=i, ticker=t) for i, t in ((1, "AAA"), (2, "BBB"), (3, "CCC"), (4, "DDD"))]
    monkeypatch.setattr(PeerComparisonService, "_latest_market_caps_usd",
                        lambda self, db, ids: {1: 10.0, 2: 500.0, 4: 80.0})
    assert [c.ticker for c in prv.by_market_cap(SimpleNamespace(rollback=lambda: None), cos)] == ["BBB", "DDD", "AAA", "CCC"]
