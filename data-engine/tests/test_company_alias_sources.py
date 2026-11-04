"""Alias de empresa desde datos, para todas las empresas (petición de Nico, 4-nov-2026).

«No hagas un arreglo para este caso concreto, sino así con todas las
empresas»: nada de listas por ticker. Las respuestas de Wikidata grabadas el
4-nov-2026 (tests/fixtures/company_aliases/wikidata_v1.json, recortadas)
alimentan el mismo código que corre en producción; cada test comprueba un
comportamiento.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.data.company_master import COMPANY_MASTER
from app.models.entities import Base, Company, Tenant
from app.services import company_alias_sources as cas
from app.services.company_aliases import load_alias_file
from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.news_service import NewsService, _ticker_evidence_level
from app.services.ticker_news_lane import (
    VERIFIED_ALIASES,
    google_alias_feed_url,
    google_lanes,
    label_google,
)

FIXTURE = Path(__file__).parent / "fixtures" / "company_aliases" / "wikidata_v1.json"
NOW = datetime(2026, 11, 4, 2, 0, tzinfo=UTC)

COMPANIES = {
    "AAPL": SimpleNamespace(ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", isin=None, id=None),
    "META": SimpleNamespace(ticker="META", name="Meta Platforms, Inc.", exchange="NASDAQ", isin=None, id=None),
    "IBE": SimpleNamespace(ticker="IBE", name="Iberdrola, S.A.", exchange="BME", isin="ES0144580Y14", id=None),
    "ASTS": SimpleNamespace(ticker="ASTS", name="AST SpaceMobile, Inc.", exchange="NASDAQ", isin=None, id=None),
    "SPCX": SimpleNamespace(
        ticker="SPCX", name="Space Exploration Technologies Corp.", exchange="NASDAQ", isin=None, id=None
    ),
    "NKE": SimpleNamespace(ticker="NKE", name="NIKE, Inc.", exchange="NYSE", isin=None, id=None),
}
OOKLA = "Testing the limits of Starlink’s D2D text and data performance in the U.S. - Ookla"


def _replay():
    answers = json.loads(FIXTURE.read_text(encoding="utf-8"))["respuestas"]

    def get(url, params):
        key = json.dumps([url, params], sort_keys=True)
        if key not in answers:
            raise AssertionError(f"consulta no grabada: {key[:200]}")
        return answers[key]

    return get


@pytest.fixture(scope="module")
def records():
    get = _replay()
    catalog = cas.catalog_terms(COMPANIES.values())
    return {t: cas.build_record(c, get=get, catalog=catalog, now=NOW) for t, c in COMPANIES.items()}


def _alias(record, term):
    return next((a for a in record.aliases if a.termino == term), None)


def _query(url: str | None) -> str:
    assert url is not None
    return parse_qs(urlsplit(url).query)["q"][0]


# --- una empresa por comportamiento -----------------------------------------


def test_spcx_starlink_sale_de_datos_y_entra_en_el_feed_de_7_dias(records):
    spcx = records["SPCX"]
    assert spcx.qid == "Q193701"
    # «SpaceX» es la etiqueta del propio elemento (el nombre legal no lo dice)
    # y «Starlink» la serie de satélites que fabrica: nada escrito a mano.
    spacex = _alias(spcx, "SpaceX")
    assert spacex is not None and spacex.tipo == "nombre"
    starlink = _alias(spcx, "Starlink")
    assert starlink is not None and not starlink.requiere
    terms = cas.search_terms(spcx, company_name=COMPANIES["SPCX"].name)
    assert terms[:2] == ["SpaceX", "Starlink"] and len(terms) <= cas.MAX_SEARCH_TERMS
    q = _query(google_alias_feed_url(COMPANIES["SPCX"], terms=terms))
    assert q.startswith('"SpaceX" OR "Starlink"') and q.endswith(" when:7d")
    # El titular de Ookla del 3-nov (solo dice «Starlink») pasa el filtro del feed.
    result = ConnectorResult(source="rss", items=[
        ConnectorItem(source="Google News", title=OOKLA, summary="", ticker="SPCX"),
        ConnectorItem(source="Google News", title="Mobile carriers expand 5G - Light Reading", summary="", ticker="SPCX"),
    ])
    kept = label_google(result, COMPANIES["SPCX"], _ticker_evidence_level, spcx.aliases).items
    assert [(i.title, i.source) for i in kept] == [
        ("Testing the limits of Starlink’s D2D text and data performance in the U.S.", "Ookla")
    ]


def test_asts_bluebird_solo_con_contexto_de_satelites(records):
    asts = records["ASTS"]
    assert asts.qid == "Q112659289"
    bluebird = _alias(asts, "BlueBird")
    # Serie de satélites «BlueBird 1…13» → «BlueBird»; homónimo con peso
    # propio (el pájaro), así que exige contexto, y el contexto sale de los
    # datos de ASTS («artificial satellite» → «satellite»), no de una lista.
    assert bluebird is not None and bluebird.requiere
    assert "satellite" in bluebird.requiere and "AST SpaceMobile" in bluebird.requiere
    assert cas.alias_hit("BlueBird satellite launch slips to December", asts.aliases) is bluebird
    assert cas.alias_hit("BlueBird sightings rise across Ohio this spring", asts.aliases) is None
    # Sin términos con peso propio y sin ambigüedad, ASTS no tiene feed de marca.
    assert cas.search_terms(asts, company_name=COMPANIES["ASTS"].name) == []


def test_aapl_iphone(records):
    aapl = records["AAPL"]
    iphone = _alias(aapl, "iPhone")
    assert iphone is not None and iphone.qid == "Q2766" and iphone.fuente == "wikidata"
    assert iphone.etiqueta == cas.VERIFIED and not iphone.requiere
    assert cas.alias_hit("iPhone 18 demand beats estimates in China", aapl.aliases) is iphone
    assert cas.search_terms(aapl, company_name="Apple Inc.")[0] == "iPhone"
    # «Mac» (3 letras) no pasa la longitud mínima.
    assert _alias(aapl, "Mac") is None


def test_meta_instagram_y_whatsapp(records):
    meta = records["META"]
    instagram, whatsapp = _alias(meta, "Instagram"), _alias(meta, "WhatsApp")
    assert instagram is not None and not instagram.requiere
    assert whatsapp is not None and not whatsapp.requiere
    assert cas.search_terms(meta, company_name=COMPANIES["META"].name) == ["Facebook", "Instagram", "WhatsApp"]
    # «Messenger» nombra también a otras cosas con peso propio: exige contexto.
    messenger = _alias(meta, "Messenger")
    assert messenger is not None and messenger.requiere
    assert cas.alias_hit("Messenger adds group calls for Instagram users", meta.aliases) is not None
    assert cas.alias_hit("Messenger probe images of Mercury released", meta.aliases) is None
    # Las personas siempre exigen contexto.
    zuck = _alias(meta, "Mark Zuckerberg")
    assert zuck is not None and zuck.tipo == "persona" and zuck.requiere


def test_ibe_filiales_de_iberdrola(records):
    ibe = records["IBE"]
    assert ibe.qid == "Q1437502"  # resuelto por ISIN
    names = {a.termino for a in ibe.aliases}
    assert {"Scottish Power", "Avangrid", "Iberdrola Renovables", "Neoenergia"} <= names
    # Centrales y presas que Iberdrola opera no son marcas.
    assert not any("Dam" in n or "Power Plant" in n for n in names)
    assert cas.alias_hit("Avangrid wins offshore wind contract in New York", ibe.aliases) is not None
    assert "Scottish Power" in cas.search_terms(ibe, company_name=COMPANIES["IBE"].name)


def test_empresa_sin_entrada_a_mano(records):
    # NKE no está en company_aliases.json ni en la semilla del carril por
    # ticker: todo sale de sus datos.
    assert "NKE" not in load_alias_file()["empresas"] and "NKE" not in VERIFIED_ALIASES
    nke = records["NKE"]
    assert nke.qid == "Q483915"
    converse = _alias(nke, "Converse")
    assert converse is not None and converse.requiere  # «converse» también es otra cosa
    assert cas.alias_hit("Converse footwear sales slow in China", nke.aliases) is converse
    assert cas.alias_hit("Converse County sheriff race heats up", nke.aliases) is None
    assert cas.alias_hit("Umbro signs kit deal with Everton", nke.aliases) is not None
    assert cas.search_terms(nke, company_name=COMPANIES["NKE"].name)


# --- guardas comunes ---------------------------------------------------------


def _cand(term, kind="marca", weight=10, etiqueta=cas.VERIFIED):
    return cas.AliasTerm(term, kind, "wikidata", etiqueta, None, weight)


def test_guardas_longitud_palabras_corrientes_siglas_y_otra_empresa():
    catalog = cas.catalog_terms([SimpleNamespace(ticker="GOOGL", name="Alphabet Inc.")])
    aliases, _ = cas.finalize(
        "XYZ", "Xyz Holdings Inc.",
        [_cand("Mac"), _cand("Store"), _cand("ABC"), _cand("Alphabet"), _cand("xyz.com"),
         _cand("Zorblax"), _cand("Bob", "persona"), _cand("Ana Ruiz", "persona")],
        [], catalog_terms=catalog, homonyms={"zorblax": 0},
    )
    names = {a.termino: a for a in aliases}
    assert set(names) == {"Zorblax", "Ana Ruiz"}
    assert not names["Zorblax"].requiere and names["Ana Ruiz"].requiere


def test_guardas_tope_por_empresa_y_de_personas():
    cands = [_cand(f"Brandname{chr(65 + i)}x", weight=100 - i) for i in range(20)]
    cands += [_cand(f"Person Number{chr(65 + i)}", "persona", weight=500) for i in range(5)]
    aliases, _ = cas.finalize("XYZ", "Xyz Inc.", cands, [], homonyms={})
    assert len(aliases) == cas.MAX_LINK_ALIASES
    assert sum(a.tipo == "persona" for a in aliases) == cas.MAX_PEOPLE


def test_palabra_suelta_sin_comprobar_exige_contexto():
    aliases, context = cas.finalize("XYZ", "Xyz Robotics Inc.", [_cand("Falcon"), _cand("WidgetPro")], ["industrial robot"])
    falcon, widget = aliases
    assert falcon.termino == "Falcon" and falcon.requiere and "robot" in falcon.requiere
    assert not widget.requiere  # mayúscula interna: rasgo de marca


def test_inferido_del_informe_anual_lleva_etiqueta_y_contexto_y_no_busca():
    text = (
        "Our ZetaLink® platform connects devices. ZetaLink customers grew. "
        "The AquaCore system and AquaCore modules ship worldwide."
    )
    inferred = cas.infer_from_text(text, fuente="sec_10k", company_name="Quorvia Devices Inc.")
    assert {a.termino for a in inferred} >= {"ZetaLink", "AquaCore"}
    assert all(a.etiqueta == cas.INFERRED for a in inferred)
    company = SimpleNamespace(ticker="QRV", name="Quorvia Devices Inc.", exchange="NYSE", isin=None, id=None)

    def offline(url, params):
        raise OSError("sin red")

    record = cas.build_record(company, get=offline, text=text, text_source="sec_10k", now=NOW)
    assert record.error and "sec_10k" in record.fuentes
    assert record.aliases and all(a.requiere for a in record.aliases)
    assert "Quorvia" in record.aliases[0].requiere
    assert cas.search_terms(record, company_name=company.name) == []
    # Sin ningún término de contexto posible, lo que exige contexto se descarta.
    bare = cas.build_record(
        SimpleNamespace(ticker="XYZ", name="Xyz Inc.", exchange="NYSE", isin=None, id=None),
        get=offline, text=text, text_source="sec_10k", now=NOW,
    )
    assert bare.aliases == []


def test_feed_de_marca_ventana_7_dias_y_tope():
    company = SimpleNamespace(ticker="XYZ", name="Xyz Inc.")
    q = _query(google_alias_feed_url(company, terms=["Alpha One", "Beta Two", "Gamma Three", "Delta Four"]))
    assert q == '"Alpha One" OR "Beta Two" OR "Gamma Three" when:7d'
    assert google_alias_feed_url(company, terms=[]) is None
    lanes = dict(google_lanes(company, priority=False, brand_terms=["Alpha One"]))
    assert set(lanes) == {"google-en", "google-en-marca"}
    assert [lane for lane, _ in google_lanes(company, priority=False)] == ["google-en"]


# --- caché en tenants.metadata y vínculo de noticias ---------------------------


def _company(ticker, name):
    return Company(
        ticker=ticker, name=name, exchange="NASDAQ", currency="USD", sector="Tech", industry="Tech",
        company_type="holding", valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=7, external_id="t7", metadata_={"language": "es"}))
        seen = set()
        for row in COMPANY_MASTER:
            if row["ticker"] not in seen:
                seen.add(row["ticker"])
                session.add(_company(row["ticker"], row["name"]))
        if "NKE" not in seen:
            session.add(_company("NKE", "NIKE, Inc."))
        session.commit()
        session.info["tenant_id"] = 7
        yield session


def test_cache_en_tenants_metadata_con_caducidad(db, records):
    cas.store(db, [records["NKE"], records["META"]])
    tenant = db.get(Tenant, 7)
    assert tenant.metadata_["language"] == "es"  # no pisa otras claves
    cached = cas.load_cached(db)
    assert set(cached) == {"NKE", "META"}
    assert cached["NKE"].aliases == records["NKE"].aliases
    assert cached["NKE"].is_fresh(NOW + timedelta(days=29))
    assert not cached["NKE"].is_fresh(NOW + timedelta(days=31))
    # ensure_aliases no vuelve a la red con la caché al día.
    def boom(url, params):
        raise AssertionError("no debía consultar")

    nke = SimpleNamespace(ticker="NKE", name="NIKE, Inc.", id=None)
    assert cas.ensure_aliases(db, [nke], get=boom, now=NOW)["NKE"].qid == "Q483915"


def test_ensure_aliases_refresca_lo_caducado_con_tope(db):
    calls = []

    def fake_fetch(company, get=None, *, catalog_terms=None, check_homonyms=True):
        calls.append(company.ticker)
        return cas.AliasRecord(ticker=company.ticker, qid="Q1", aliases=[_cand("Zorblax")], fuentes=["wikidata"])

    companies = [SimpleNamespace(ticker=f"T{i}", name=f"T{i} Inc.", id=None) for i in range(6)]
    original = cas.fetch_wikidata
    cas.fetch_wikidata = fake_fetch
    try:
        out = cas.ensure_aliases(db, companies, max_fetch=2, now=NOW, catalog={})
    finally:
        cas.fetch_wikidata = original
    assert calls == ["T0", "T1"] and {"T0", "T1"} <= set(out)


def test_noticia_sin_ticker_se_liga_por_alias_de_datos(db, records):
    service = NewsService()
    # Sin caché: Umbro no dice nada de NKE.
    primary, _ = service.detect_company_links(db, "Umbro signs kit deal with Everton for 2027")
    assert primary is None or primary.company.ticker != "NKE"
    cas.store(db, [records["NKE"], records["META"]])
    primary, _ = service.detect_company_links(db, "Umbro signs kit deal with Everton for 2027")
    assert primary is not None and primary.company.ticker == "NKE"
    assert "Q" in primary.via or "wikidata" in primary.via
    # Ambiguo sin contexto: no se liga.
    primary, _ = service.detect_company_links(db, "Converse County sheriff race heats up")
    assert primary is None or primary.company.ticker != "NKE"


def test_solo_se_consulta_wikidata_y_con_agente_de_contacto():
    assert cas._wikidata_only("https://query.wikidata.org/sparql?query=x")
    assert cas._wikidata_only("https://www.wikidata.org/w/api.php?action=x")
    assert not cas._wikidata_only("http://169.254.169.254/latest/meta-data")
    assert "https://" in cas.USER_AGENT  # Wikimedia limita los agentes sin contacto
