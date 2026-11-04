"""Personas con varias empresas (Elon Musk): con contexto de Tesla es «sobre»
TSLA; sin contexto de ninguna empresa, «relacionada» (ceo); con contexto de
otra empresa (SpaceX, xAI, X, Neuralink, DOGE/política), no se vincula a TSLA.
Fixture: tests/fixtures/news_links/musk_v1.json."""

import json
from pathlib import Path

import pytest

from app.services.company_aliases import LINK_ABOUT, LINK_RELATED
from app.services.news_service import NewsService
from tests.test_news_aliases_asts import db  # noqa: F401  (fixture)

FIXTURE = Path(__file__).parent / "fixtures" / "news_links" / "musk_v1.json"


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["casos"]


def _tsla_kind(db, text):  # noqa: F811
    primary, related = NewsService().detect_company_links(db, text)
    if primary is not None and primary.company.ticker == "TSLA":
        return primary.link_type, primary.via
    if any(r.company.ticker == "TSLA" for r in related):
        return "anotada", None
    return None, None


@pytest.mark.parametrize("caso", _cases(), ids=lambda c: c["texto"][:40])
def test_musk(db, caso):  # noqa: F811
    kind, via = _tsla_kind(db, caso["texto"])
    assert kind == caso["espera"]
    if kind == LINK_RELATED:
        assert via.startswith("ceo:")
    if kind == LINK_ABOUT:
        assert via.startswith("persona:")


def test_musk_al_menos_diez_titulares_y_los_tres_casos():
    esperas = [c["espera"] for c in _cases()]
    assert len(esperas) >= 10
    assert {LINK_ABOUT, LINK_RELATED, None} <= set(esperas)


def test_persona_sin_contexto_no_actua_en_la_capa_de_alias(db):  # noqa: F811
    """La regla «relacionada:ceo» es capa 2: la capa 1 sola no vincula a Musk sin contexto."""
    service = NewsService()
    assert service.detect_company_link(db, "Elon Musk becomes the first person worth $500 billion") is None
