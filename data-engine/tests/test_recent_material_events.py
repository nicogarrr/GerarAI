"""Hechos materiales recientes en la tesis (todas las empresas).

Caso real (prod, 3-nov-2026, ASTS): el pipeline de noticias tenía Brasil
(26-oct, comunicado), el handoff con AT&T (2-nov, comunicado), SpaceX y Boost
Mobile (2-nov) y Chile (3-nov), pero la tesis cogía 5 noticias ordenadas por
«materialidad» y salieron titulares de opinión del 8 al 20 de octubre.
"""
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, NewsEvent
from app.services.recent_material_events import (
    KIND_NEWS,
    KIND_PRESS,
    KIND_SEC,
    collect_recent_events,
    items_label,
    news_kind,
    recent_events_markdown,
    select_recent_events,
)
from app.services.thesis_evidence_service import ThesisEvidenceService
from app.services.thesis_service import ThesisService

NOW = datetime.now(UTC)


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker="ASTX", name="AST SpaceMobile", ir_url=None):
    c = Company(ticker=ticker, name=name, exchange="NASDAQ", currency="USD", sector="Telecom",
                industry="Satellite", company_type="pre_revenue", valuation_model="unassigned",
                special_sources=[], special_risks=[], factor_tags=[], ir_url=ir_url)
    db.add(c)
    db.commit()
    return c


def _news(db, c, days, title, source, m, url=None, **meta):
    db.add(NewsEvent(company_id=c.id, date=ago(days), title=title, source=source,
                     url=url or f"https://example.test/{abs(hash(title))}", materiality_score=m,
                     metadata_=meta or None))


def _seed_asts_like(db, c):
    # Opinión vieja con «materialidad» 10: antes se comía los 5 huecos.
    for i, d in enumerate((14, 21, 23, 25, 26, 27, 28)):
        _news(db, c, d, f"Opinion piece number {i}: is the stock priced for perfection {i}", "Yahoo Finance", 10)
    _news(db, c, 22, "ASTS Investors Have Opportunity to Lead AST SpaceMobile Securities Fraud Lawsuit",
          "PR Newswire", 10)
    # Brasil: comunicado + copias en medios.
    _news(db, c, 8.4, "AST SpaceMobile Advances Brazil Expansion with Anatel's Approval for S-band Spectrum",
          "Business Wire", 7, url="http://www.businesswire.com/news/home/brazil")
    _news(db, c, 8.3, "AST SpaceMobile secures Brazil spectrum authorization", "Investing.com", 5)
    _news(db, c, 7, "AST SpaceMobile wins regulatory approvals to launch in Brazil", "Telecompaper", 7)
    # Ruido reciente de poca materialidad.
    for i in range(8):
        _news(db, c, 0.2 + i * 0.1, f"Stocktwits chatter {i} retail sentiment shifts", "Stocktwits", 3)
    # Muchas noticias medias recientes que no son los hechos pedidos.
    for i in range(10):
        _news(db, c, 0.5 + i * 0.3, f"Market wrap {i}: space names {['rally','slide','drift','bounce','fade','jump','sink','spike','dip','climb'][i]} today", "Benzinga", 5)
    # SpaceX quiere comprar Boost Mobile.
    _news(db, c, 1.2, "AST SpaceMobile Sinks 10% as SpaceX Rises on Reported Talks to Buy Boost Mobile",
          "Yahoo Finance", 6)
    # Primer handoff (comunicado) y su cobertura.
    _news(db, c, 1.1, "AT&T and AST SpaceMobile: Engineering the Connected World, One Handoff at a Time",
          "Business Wire", 7, url="http://www.businesswire.com/news/home/handoff")
    _news(db, c, 0.9, "AT&T and AST SpaceMobile complete ground-to-satellite network handoff", "StreetInsider", 6)
    # Chile.
    _news(db, c, 0.4, "AST SpaceMobile wins access to Chile", "Advanced Television", 6)
    # 13G: participación, no hecho de la empresa.
    _news(db, c, 3, "Declaración de participación (SCHEDULE 13G)", "SEC", 6,
          url="https://www.sec.gov/13g", connector="sec", form="SCHEDULE 13G")
    db.commit()


def test_thesis_news_prefers_recent_events_over_old_high_materiality(db):
    c = _company(db)
    _seed_asts_like(db, c)
    news = ThesisEvidenceService()._collect_news(db, c)
    titles = [i["title"] for i in news["items"]]
    joined = " | ".join(titles)
    assert "Brazil" in joined
    assert "Chile" in joined
    assert "Boost Mobile" in joined
    assert "Handoff" in joined or "handoff" in joined
    # Comunicado como representante de la historia, una sola vez.
    assert sum("Brazil" in t for t in titles) == 1
    assert any(i["source"] == "Business Wire" and "Brazil" in i["title"] for i in news["items"])
    # Ni despachos de abogados ni opinión vieja por delante de lo nuevo.
    assert not any("Lawsuit" in t for t in titles)
    dates = [i["date"] for i in news["items"]]
    assert dates == sorted(dates, reverse=True)
    assert not any("Opinion piece" in t for t in titles[:5])


def test_news_falls_back_to_materiality_when_window_is_empty(db):
    c = _company(db)
    _news(db, c, 200, "Old but only news about the company expanding", "Reuters", 8)
    db.commit()
    news = ThesisEvidenceService()._collect_news(db, c)
    assert [i["title"] for i in news["items"]] == ["Old but only news about the company expanding"]


def test_collect_recent_events_dates_sources_recency_rule_and_gaps(db):
    c = _company(db)
    _seed_asts_like(db, c)
    db.add(Document(company_id=c.id, title="ASTX 10-Q filed", source_type="SEC",
                    source_url="https://www.sec.gov/10q", published_at=ago(30), metadata_={"form": "10-Q"}))
    db.add(Document(company_id=c.id, title="ASTX 8-K filed", source_type="SEC",
                    source_url="https://www.sec.gov/8k-old", published_at=ago(35),
                    metadata_={"form": "8-K", "items": "1.01,9.01"}))
    db.add(Document(company_id=c.id, title="ASTX 8-K filed", source_type="SEC",
                    source_url="https://www.sec.gov/8k", published_at=ago(14),
                    metadata_={"form": "8-K", "items": "5.02"}))
    # El mismo 8-K también entra como noticia del pipeline: cuenta una vez.
    _news(db, c, 14, "ASTX 8-K presentado ante la SEC", "SEC", 9, url="https://www.sec.gov/8k", connector="sec")
    db.commit()

    block = collect_recent_events(db, c, now=NOW)
    items = block["items"]
    assert block["status"] == "ok"
    assert all(i.get("date") and i.get("source") for i in items)
    assert [i["date"] for i in items] == sorted((i["date"] for i in items), reverse=True)
    sec = [i for i in items if i["kind"] == KIND_SEC]
    assert len([i for i in sec if i["url"] == "https://www.sec.gov/8k"]) == 1
    assert any("5.02 salida o nombramiento de directivos" in (i["title"] or "") for i in sec)
    assert not any("13G" in (i["title"] or "") for i in items)
    for wanted in ("Brazil", "Chile", "Boost Mobile", "Handoff"):
        assert any(wanted.lower() in (i["title"] or "").lower() for i in items), wanted
    # Regla de vigencia: lo posterior al 10-Q se marca; el 8-K de hace 35 días no.
    assert block["latest_periodic_report"]["form"] == "10-Q"
    old_8k = next(i for i in items if i["url"] == "https://www.sec.gov/8k-old")
    assert old_8k["after_latest_report"] is False
    chile = next(i for i in items if "Chile" in i["title"])
    assert chile["after_latest_report"] is True
    # Lo que no se encontró se declara, no se inventa.
    ir = next(s for s in block["sources_checked"] if s["source"] == "Página de inversores")
    assert ir["found"] == 0 and "no tiene URL" in ir["note"]


def test_markdown_section_has_date_kind_source_and_sources_checked(db):
    c = _company(db)
    _seed_asts_like(db, c)
    db.add(Document(company_id=c.id, title="ASTX 10-Q filed", source_type="SEC",
                    source_url="https://www.sec.gov/10q", published_at=ago(30), metadata_={"form": "10-Q"}))
    db.commit()
    block = collect_recent_events(db, c, now=NOW)
    md = ThesisService()._news_markdown({"news": {}, "recent_events": block})
    assert "### Hechos recientes (últimos 45 días, de más nuevo a más antiguo)" in md
    assert f"Último informe periódico: 10-Q del {ago(30).date().isoformat()}" in md
    chile_line = next(line for line in md.splitlines() if "Chile" in line)
    assert chile_line.startswith(f"- {ago(0.4).date().isoformat()} · noticia · Advanced Television:")
    assert "posterior al último informe" in chile_line
    brazil_line = next(line for line in md.splitlines() if "Brazil Expansion" in line)
    assert " · comunicado · Business Wire:" in brazil_line
    assert "Fuentes consultadas:" in md and "SEC (8-K/6-K): 0 (ningún 8-K/6-K" in md


def test_markdown_without_events_is_honest_pending():
    md = recent_events_markdown({"items": [], "sources_checked": [], "detail": "sin hechos fechados en los últimos 45 días"})
    assert "Pendiente: sin hechos fechados en los últimos 45 días" in md
    assert "no localizado" in md


def test_primary_sources_keep_a_slot_when_news_floods_the_window():
    flood = [
        {"date": ago(i * 0.05), "title": f"{w}{i} {w[::-1]}{i}x zq{i}", "source": "Yahoo",
         "kind": KIND_NEWS, "materiality": 9}
        for i, w in enumerate(f"word{n}alpha" for n in range(40))
    ]
    pr = {"date": ago(20), "title": "Company signs definitive agreement with carrier", "source": "Business Wire",
          "kind": KIND_PRESS}
    events = select_recent_events([*flood, pr], now=NOW, limit=12)
    assert len(events) == 12
    assert any(e["source"] == "Business Wire" for e in events)
    assert [e["date"] for e in events] == sorted((e["date"] for e in events), reverse=True)


def test_events_without_date_or_outside_window_are_dropped():
    events = select_recent_events(
        [
            {"date": None, "title": "No date at all here", "source": "X", "kind": KIND_PRESS},
            {"date": ago(400), "title": "Very old press release", "source": "Business Wire", "kind": KIND_PRESS},
        ],
        now=NOW,
    )
    assert events == []


def test_kind_and_item_labels():
    assert news_kind("Business Wire", None, None) == KIND_PRESS
    assert news_kind("Google News", "https://www.globenewswire.com/x", None) == KIND_PRESS
    assert news_kind("SEC", None, None) == KIND_SEC
    assert news_kind("Yahoo Finance", None, {"assessment": {"source_tier": "tier_5_data_provider"}}) == KIND_NEWS
    assert items_label("2.02,9.01") == "2.02 resultados; 9.01 anexos"
    assert items_label("") is None


def test_collect_stored_exposes_recent_events_without_network(db, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("sin red")

    for name in ("_fetch_cik", "_fetch_company_facts", "_fetch_filings", "_fetch_earnings", "_fetch_ir"):
        monkeypatch.setattr(ThesisEvidenceService, name, boom, raising=False)
    c = _company(db)
    _seed_asts_like(db, c)
    out = ThesisEvidenceService().collect_stored(db, c)
    block = out["sources"]["recent_events"]
    assert block["status"] == "ok"
    assert any("Chile" in i["title"] for i in block["items"])


# -- extremo a extremo: la tesis seguida (sin red) lleva la sección --------------
try:
    from tests.test_thesis_auto_ingest import _seed_evidence_rows  # type: ignore[import-not-found]
    from tests.test_tracked_stored_evidence import NEWS_TITLE, _tracked_generate, tracked_env  # noqa: F401
except ImportError:  # pragma: no cover - ejecucion desde data-engine/tests
    from test_thesis_auto_ingest import _seed_evidence_rows  # type: ignore
    from test_tracked_stored_evidence import NEWS_TITLE, _tracked_generate, tracked_env  # type: ignore  # noqa: F401


def test_tracked_thesis_has_dated_sourced_recent_events(tracked_env):  # noqa: F811
    _seed_evidence_rows()
    *_rest, markdown, _fp = _tracked_generate()
    assert tracked_env == []
    section = markdown.split("## 10. Noticias y catalizadores", 1)[1].split("## 11.", 1)[0]
    assert "### Hechos recientes (últimos 45 días, de más nuevo a más antiguo)" in section
    line = next(row for row in section.splitlines() if NEWS_TITLE in row)
    assert re.match(r"^- \d{4}-\d{2}-\d{2} · (noticia|comunicado|SEC|página de inversores) · .+: ", line)
    assert "Fuentes consultadas:" in section
    assert "Últimas noticias materiales" not in section
