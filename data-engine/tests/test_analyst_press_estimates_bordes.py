"""Bordes del extractor de estimaciones de prensa (analyst_press_estimates).

Complementa a test_analyst_press_estimates.py: divisas marcadas y ambiguas,
fallbacks de métrica y fecha, robots.txt ilegible, filtros del collect,
ramas de store_readings (skips), refresh end-to-end con fetch falso y la
marca de frescura press_estimates_stale.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import AnalystNote, Company, Tenant
from app.models.declared_input_value import DeclaredInputValue
from app.services import analyst_note_service as ans
from app.services import analyst_press_estimates as ape
from app.services import declared_input_service as dis

FIXTURE = Path(__file__).parent / "fixtures" / "analyst_press" / "advanced_television_2026-08-13.html"
URL = "https://www.advanced-television.com/2026/08/13/bank-ast-spacemobile-will-be-a-cash-flow-machine/"
ASTS = SimpleNamespace(ticker="ASTS", name="AST SpaceMobile, Inc.")
HOY = date(2026, 11, 8)


def _article(text: str, published: date = HOY, url: str = "https://x.example/a"):
    return ape.Article(url, "t", published, text)


# -- divisas -------------------------------------------------------------------


def test_marca_de_divisa_junto_al_dolar():
    # start es la posición del importe (los llamadores pasan num_start - 4).
    assert ape.marked_currency("vale US$ 100 million", 5) == "USD"
    assert ape.marked_currency("vale C$ 100 million", 5) == "CAD"
    assert ape.marked_currency("vale HK$ 100 million", 5) == "HKD"
    assert ape.marked_currency("vale $ 100 million", 5) is None
    assert ape.marked_currency("sin importe alguno", 0) is None


def test_resolve_currency_reglas():
    # Con marca escrita, la marca manda sobre cualquier base.
    assert ape.resolve_currency("CAD", "USD") == "CAD"
    assert ape.resolve_currency("AUD", "EUR") == "AUD"
    # A secas: USD si la empresa informa en USD o en divisa que no se escribe «$».
    assert ape.resolve_currency(None, "USD") == "USD"
    assert ape.resolve_currency(None, None) == "USD"
    assert ape.resolve_currency(None, "EUR") == "USD"
    assert ape.resolve_currency(None, "gbp") == "USD"
    # A secas con empresa de otro dólar: ambiguo, None.
    assert ape.resolve_currency(None, "CAD") is None
    assert ape.resolve_currency(None, "AUD") is None


def test_resolve_currency_en_estimacion_con_marca():
    reading = ape.read_article(_article(
        "Cantor Fitzgerald espera revenue de C$120 million in 2027 para AST SpaceMobile."), company=ASTS)
    assert [(e.marked_currency, e.amount) for e in reading.estimates] == [("CAD", Decimal("120000000"))]


# -- métrica y fecha -----------------------------------------------------------


def test_metric_before_fallback_a_la_metrica_de_la_frase():
    # Sin palabra de métrica antes del importe: usa la única métrica de la frase.
    assert ape._metric_before("2027 of $557 million de revenue esperado", 0) == "revenue"
    # Con dos métricas en la frase y ninguna antes: ambiguo, None.
    assert ape._metric_before("2027 of $557 million con revenue y EBITDA al alza", 0) is None
    # Sin métrica en ningún sitio: None.
    assert ape._metric_before("2027 of $557 million a secas", 0) is None


def test_read_article_descarta_importe_sin_metrica():
    reading = ape.read_article(_article(
        "Cantor Fitzgerald espera $90 million in 2027 para AST SpaceMobile."), company=ASTS)
    assert reading.estimates == [] and reading.targets == []


def test_read_article_next_year_usa_el_año_de_publicacion():
    reading = ape.read_article(_article(
        "Cantor Fitzgerald espera revenue de $90 million next year para AST SpaceMobile."), company=ASTS)
    assert [(e.firm, e.metric, e.year, e.amount) for e in reading.estimates] == [
        ("Cantor Fitzgerald", "revenue", 2027, Decimal("90000000"))]


def test_published_from_html_variantes():
    meta = '<html><head><meta property="article:published_time" content="2026-08-13T10:00:00Z"></head></html>'
    assert ape.published_from_html(meta) == date(2026, 8, 13)
    assert ape.published_from_html('{"datePublished": "2026-08-13"}') == date(2026, 8, 13)
    assert ape.published_from_html("<html><head></head></html>") is None


# -- descubrimiento y lectura ----------------------------------------------------


def test_bing_items_bordes():
    rss = (
        "<rss><channel>"
        "<item><title>sin link</title></item>"
        "<item><title>no https</title><link>http://www.bing.com/news/apiclick.aspx?ref=R&amp;url="
        "http%3a%2f%2finseguro.example%2fa&amp;c=1</link></item>"
        "<item><title>fecha mala</title><link>http://www.bing.com/news/apiclick.aspx?ref=R&amp;url="
        "https%3a%2f%2fok.example%2fa&amp;c=1</link><pubDate>no es una fecha</pubDate></item>"
        "</channel></rss>")
    assert ape.bing_items(rss) == [("https://ok.example/a", "fecha mala", None)]
    assert ape.bing_items("") == []


def test_article_text_html_roto_devuelve_vacio():
    assert ape.article_text("") == ""
    assert ape.article_text("<html><body><p>corto</p></body></html>") == ""


def test_robots_sin_fichero_legible_permite():
    async def fetch(url):
        raise ConnectionError("caído")

    assert asyncio.run(ape.Robots().allowed("https://caido.example/a", fetch)) is True


def _fetch_fixture_con_robots_ok(html: bytes):
    async def fetch(url):
        if url.endswith("/robots.txt"):
            return b"", "text/plain", url
        if "bing.com" in url:
            return b"<rss></rss>", "application/xml", url
        return html, "text/html", url

    return fetch


def test_collect_filtra_duplicados_antiguos_y_titulos_sin_cue(monkeypatch):
    monkeypatch.setattr(ape, "MIN_INTERVAL_S", 0)
    html = FIXTURE.read_bytes()
    viejo = HOY - timedelta(days=ape.LOOKBACK_DAYS + 10)
    known = [
        (URL, "Cantor Fitzgerald estimates ASTS", HOY),                       # cuenta y se lee
        (URL, "Cantor Fitzgerald estimates ASTS", HOY),                       # duplicada
        ("https://b.example/old", "Cantor Fitzgerald ASTS", viejo),           # fuera de ventana
        ("https://c.example/jardin", "Gardening tips weekly", HOY),           # título sin cue
    ]
    rep = asyncio.run(ape.collect(ASTS, known_urls=known, fetch=_fetch_fixture_con_robots_ok(html), today=HOY))
    assert rep.articles_seen == 1 and rep.articles_read == 1 and len(rep.readings) == 1


def test_collect_articulo_vacio_y_fetch_caido(monkeypatch):
    monkeypatch.setattr(ape, "MIN_INTERVAL_S", 0)

    async def fetch(url):
        if url.endswith("/robots.txt"):
            return b"", "text/plain", url
        if "bing.com" in url:
            return b"<rss></rss>", "application/xml", url
        if "vacio.example" in url:
            return b"<html><body><p>corto</p></body></html>", "text/html", url
        raise ConnectionError("medio caído")

    known = [
        ("https://vacio.example/a", "Cantor Fitzgerald estimates ASTS", HOY),
        ("https://caido.example/a", "Cantor Fitzgerald estimates ASTS", HOY),
    ]
    rep = asyncio.run(ape.collect(ASTS, known_urls=known, fetch=fetch, today=HOY))
    assert rep.articles_seen == 2 and rep.articles_read == 0 and rep.readings == []
    assert rep.failed == ["caido.example: ConnectionError"]


def test_collect_bing_caido_se_anota_y_la_recogida_sigue(monkeypatch):
    monkeypatch.setattr(ape, "MIN_INTERVAL_S", 0)

    async def fetch(url):
        if url.endswith("/robots.txt"):
            return b"", "text/plain", url
        if "bing.com" in url:
            raise ConnectionError("bing caído")
        return FIXTURE.read_bytes(), "text/html", url

    rep = asyncio.run(ape.collect(ASTS, known_urls=[(URL, "Cantor Fitzgerald estimates", HOY)],
                                  fetch=fetch, today=HOY))
    assert rep.failed == ["bing: ConnectionError", "bing: ConnectionError"] and len(rep.readings) == 1


# -- guardado (BD) ---------------------------------------------------------------


@pytest.fixture()
def tenant_company():
    init_db()
    suffix = uuid4().hex[:6].upper()
    with SessionLocal() as db:
        tenant = Tenant(external_id=f"apeb-{suffix}", name="apeb")
        company = Company(ticker=f"AB{suffix}", name="AST SpaceMobile, Inc.", exchange="NASDAQ", currency="USD",
                          company_type="operating", valuation_model="standard_dcf")
        db.add_all([tenant, company])
        db.commit()
        ids = (company.id, tenant.id, company.ticker)
    yield ids
    with SessionLocal() as db:
        db.execute(delete(DeclaredInputValue).where(DeclaredInputValue.company_id == ids[0]))
        db.execute(delete(AnalystNote).where(AnalystNote.ticker == ids[2]))
        db.execute(delete(Company).where(Company.id == ids[0]))
        db.execute(delete(Tenant).where(Tenant.id == ids[1]))
        db.commit()


def _store(db, company, tenant_id, articles):
    readings = [(a, ape.read_article(a, company=company)) for a in articles]
    return ape.store_readings(db, company, tenant_id, readings)


def test_store_divisa_ambigua_se_salta(tenant_company, monkeypatch):
    monkeypatch.setattr(ape, "_reporting_currency", lambda db, company: "CAD")
    company_id, tenant_id, _ = tenant_company
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        out = _store(db, company, tenant_id, [_article(
            "Clear Street expects AST SpaceMobile revenue of $500 million in 2027.", date(2026, 5, 2))])
        assert out["stored"] == []
        assert any("divisa ambigua" in s and "CAD" in s for s in out["skipped"])


def test_store_no_pisa_una_cifra_mas_reciente(tenant_company):
    company_id, tenant_id, _ = tenant_company
    newer = ape.Article(URL, "t", date(2026, 8, 13), ape.article_text(FIXTURE.read_text()))
    older = _article("Clear Street expects AST SpaceMobile revenue of $500 million in 2027.", date(2026, 5, 2),
                     "https://old.example/a")
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        first = _store(db, company, tenant_id, [newer])
        assert any(s["key"] == "analyst.revenue.fy2027.clear_street" for s in first["stored"])
        second = _store(db, company, tenant_id, [older])
        assert second["stored"] == []
        assert any("más reciente" in s for s in second["skipped"])
        row = db.scalars(select(DeclaredInputValue).where(
            DeclaredInputValue.company_id == company_id,
            DeclaredInputValue.input_key == "analyst.revenue.fy2027.clear_street",
            DeclaredInputValue.superseded_at.is_(None))).one()
        assert row.base == Decimal("557000000") and row.as_of == date(2026, 8, 13)


def test_store_consenso_guarda_estimacion_pero_no_crea_nota(tenant_company):
    company_id, tenant_id, ticker = tenant_company
    article = _article("AST SpaceMobile needs consensus revenue to climb from $167.5 million this year "
                       "to $1.73 billion in 2028.")
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        out = _store(db, company, tenant_id, [article])
        keys = {s["key"] for s in out["stored"]}
        assert keys == {"analyst.revenue.fy2026.consenso_prensa", "analyst.revenue.fy2028.consenso_prensa"}
        assert db.scalars(select(AnalystNote).where(AnalystNote.ticker == ticker)).all() == []


def test_store_objetivo_con_divisa_ambigua_se_degrada(tenant_company):
    company_id, tenant_id, ticker = tenant_company
    article = _article("Cantor Fitzgerald has a $90 price target on AST SpaceMobile.")
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        company.currency = "CAD"  # la acción cotiza en CAD: un «$» a secas es ambiguo
        out = _store(db, company, tenant_id, [article])
        assert any("objetivo Cantor Fitzgerald" in s and "divisa ambigua" in s for s in out["skipped"])
        note = db.scalars(select(AnalystNote).where(AnalystNote.ticker == ticker,
                                                    AnalystNote.firm == "Cantor Fitzgerald")).one()
        assert note.pt_new is None and note.currency is None


def test_store_error_de_validacion_y_de_nota_se_anotan(tenant_company, monkeypatch):
    company_id, tenant_id, _ = tenant_company
    article = _article("Clear Street expects AST SpaceMobile revenue of $500 million in 2027.", date(2026, 5, 2))
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        monkeypatch.setattr(dis.DeclaredInputService, "validate", lambda self, item: ["fallo de validación"])
        out = _store(db, company, tenant_id, [article])
        assert out["stored"] == [] and any("fallo de validación" in s for s in out["skipped"])
    monkeypatch.undo()
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)

        def boom(*args, **kwargs):
            raise ans.AnalystNoteError(["nota rota"])

        monkeypatch.setattr(ans.analyst_note_service, "upsert", boom)
        out = _store(db, company, tenant_id, [article])
        assert any(s["key"] == "analyst.revenue.fy2027.clear_street" for s in out["stored"])
        assert any("nota Clear Street: nota rota" in s for s in out["skipped"])


def test_refresh_recoge_y_guarda_con_fetch_falso(tenant_company, monkeypatch):
    monkeypatch.setattr(ape, "MIN_INTERVAL_S", 0)
    company_id, tenant_id, _ = tenant_company
    rss = ("<rss><channel><item><title>Clear Street on AST</title>"
           "<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;url="
           "https%3a%2f%2fwww.advanced-television.com%2F2026%2F08%2F13%2Fbank-ast&amp;c=1</link>"
           "<pubDate>Thu, 13 Aug 2026 10:00:00 GMT</pubDate></item></channel></rss>")

    async def fetch(url):
        if url.endswith("/robots.txt"):
            return b"", "text/plain", url
        if "bing.com" in url:
            return rss.encode(), "application/xml", url
        return FIXTURE.read_bytes(), "text/html", url

    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        out = ape.refresh_press_estimates(db, company, tenant_id, fetch=fetch, today=HOY)
        assert out["articles_seen"] == 1 and out["articles_read"] == 1 and out["with_estimates"] == 1
        assert any(s["key"] == "analyst.revenue.fy2027.clear_street" for s in out["stored"])
        row = db.scalars(select(DeclaredInputValue).where(
            DeclaredInputValue.company_id == company_id,
            DeclaredInputValue.input_key == "analyst.revenue.fy2027.clear_street",
            DeclaredInputValue.superseded_at.is_(None))).one()
        assert row.base == Decimal("557000000")


# -- frescura ------------------------------------------------------------------


def _nota(tenant_id, ticker, suffix, extras, note_date=HOY):
    return AnalystNote(tenant_id=tenant_id, ticker=ticker, firm="Clear Street", firm_key="clear_street",
                       note_date=note_date, action="reiterate", source_type="news", verification="verificado",
                       dedupe_key=f"apeb-{suffix}", extras=extras)


def test_press_estimates_stale_segun_la_marca(tenant_company):
    company_id, tenant_id, ticker = tenant_company
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        # Sin notas: stale.
        assert ape.press_estimates_stale(db, company, tenant_id, today=HOY) is True
        # Marca de otro kind: no cuenta.
        db.add(_nota(tenant_id, ticker, "otro", {"kind": "otro", "collected_on": HOY.isoformat()}))
        db.flush()
        assert ape.press_estimates_stale(db, company, tenant_id, today=HOY) is True
        # Marca vieja (10 días > STALE_DAYS): stale.
        vieja = (HOY - timedelta(days=10)).isoformat()
        db.add(_nota(tenant_id, ticker, "vieja", {"kind": "analyst_press", "collected_on": vieja}))
        db.flush()
        assert ape.press_estimates_stale(db, company, tenant_id, today=HOY) is True
        # Marca de hoy: fresca.
        db.add(_nota(tenant_id, ticker, "hoy", {"kind": "analyst_press", "collected_on": HOY.isoformat()}))
        db.flush()
        assert ape.press_estimates_stale(db, company, tenant_id, today=HOY) is False
