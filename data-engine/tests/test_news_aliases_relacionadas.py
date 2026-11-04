"""Capa 2 de vínculo noticia → empresa: relaciones («relacionada» vs «sobre»).

Fixture: tests/fixtures/news_links/asts_v1.json. Una noticia de un socio,
competidor, regulador o del sector de ASTS, sin hablar de ASTS, queda
vinculada a ASTS como «relacionada» si ninguna empresa es «sobre»; si otra
empresa es «sobre» (Starlink → SPCX), ASTS queda anotada en metadata.
"""

from sqlalchemy import select

from app.models.entities import Company, NewsEvent
from app.schemas.api import NewsFeedItem
from app.services.company_aliases import LINK_ABOUT, LINK_RELATED
from app.services.materiality_service import UNRELATED_NEWS_MAX_MATERIALITY
from app.services.news_service import NewsService
from tests.test_news_aliases_asts import _cases, db  # noqa: F401  (fixture)


def _asts_kind(db, text):  # noqa: F811
    primary, related = NewsService().detect_company_links(db, text)
    if primary is not None and primary.company.ticker == "ASTS":
        return primary.link_type
    if any(r.company.ticker == "ASTS" for r in related):
        return "anotada"
    return None


def test_recall_y_precision_asts(db):  # noqa: F811
    sobre = [_asts_kind(db, t) for t in _cases("sobre")]
    rel = [_asts_kind(db, t) for t in _cases("relacionada")]
    neg = [_asts_kind(db, t) for t in _cases("ninguna")]
    assert sobre.count(LINK_ABOUT) == 23 and len(sobre) == 24
    assert rel.count(LINK_RELATED) == 12 and rel.count("anotada") == 4 and len(rel) == 16
    assert neg == [None] * len(neg)
    # Ninguna noticia «sobre» ASTS se degrada a «relacionada».
    assert LINK_RELATED not in sobre


def test_relacion_exige_contexto(db):  # noqa: F811
    assert _asts_kind(db, "Verizon expands direct-to-cell satellite plans to rural customers") == LINK_RELATED
    assert _asts_kind(db, "Verizon to cut 13,000 jobs in cost overhaul") is None
    assert _asts_kind(db, "FCC fines broadcaster over indecency complaint") is None


def test_dice_por_que_es_relacionada(db):  # noqa: F811
    primary, related = NewsService().detect_company_links(
        db, "Ligado Networks emerges from bankruptcy with new L-band plan"
    )
    assert primary is not None and related == []
    assert primary.as_metadata() == {"ticker": "ASTS", "tipo": "relacionada", "via": "espectro:Ligado"}


def test_sobre_otra_empresa_deja_asts_anotada(db):  # noqa: F811
    primary, related = NewsService().detect_company_links(
        db, "Starlink direct-to-cell service now covers one million T-Mobile users"
    )
    assert primary is not None and primary.company.ticker == "SPCX" and primary.link_type == LINK_ABOUT
    assert [r.as_metadata() for r in related] == [
        {"ticker": "ASTS", "tipo": "relacionada", "via": "competidor:Starlink"}
    ]


def test_lo_vinculado_por_ticker_no_cambia(db):  # noqa: F811
    service = NewsService()
    for text in _cases("sobre") + _cases("relacionada") + _cases("ninguna"):
        company, level = service._detect_by_ticker(db, text)
        primary, _related = service.detect_company_links(db, text)
        if level > 0:
            assert (primary.company if primary else None) is company


def test_ingesta_relacionada_sin_revision_de_tesis(db):  # noqa: F811
    service = NewsService()
    item = NewsFeedItem(
        title="FCC approves supplemental coverage from space framework",
        text="The rules let satellite operators use terrestrial spectrum to reach phones directly.",
        source="Reuters",
        url="https://news.example/fcc-scs",
    )
    result = service.ingest_news_items(db, [item], default_source="feed")
    assert result.created == 1
    event = db.scalar(select(NewsEvent))
    asts = db.scalar(select(Company).where(Company.ticker == "ASTS"))
    assert event.company_id == asts.id
    assert event.metadata_["vinculo"] == {"ticker": "ASTS", "tipo": "relacionada", "via": "regulador:FCC"}
    assert "relacionadas" not in event.metadata_
    assert event.materiality_score <= UNRELATED_NEWS_MAX_MATERIALITY
    assert result.events[0].requires_update is False
    assert any("vínculo relacionada" in r for r in result.events[0].materiality_reasons)


def test_ingesta_sobre_por_ticker_anota_relacionadas(db):  # noqa: F811
    service = NewsService()
    item = NewsFeedItem(
        title="AT&T to offer satellite-to-smartphone service in 2026, CFO says",
        text="",
        source="Reuters",
        url="https://news.example/att-sat",
    )
    service.ingest_news_items(db, [item], default_source="feed")
    event = db.scalar(select(NewsEvent))
    att = db.scalar(select(Company).where(Company.ticker == "T"))
    assert event.company_id == att.id
    assert "vinculo" not in event.metadata_
    assert event.metadata_["relacionadas"] == [{"ticker": "ASTS", "tipo": "relacionada", "via": "socio:AT&T"}]
