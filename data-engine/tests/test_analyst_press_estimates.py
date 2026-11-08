"""Estimaciones de analistas recopiladas de la prensa gratuita y su agregado (fuentes-1, 8-nov-2026).

Caso real: GerarAI no tenía ninguna estimación por año de analista para ASTS.
La nota de Clear Street (ingresos 2027E 557 M$, 2028E 1.910 M$ según la
captura que aportó Nico, que aquí solo sirve para verificar) la cita la prensa:
Advanced Television, 13-ago-2026 («2027 of $557 million, 2028 of $1.9 billion»).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import AnalystNote, Company, Tenant
from app.models.declared_input_value import DeclaredInputValue
from app.services import analyst_consensus as ac
from app.services import analyst_press_estimates as ape

FIXTURE = Path(__file__).parent / "fixtures" / "analyst_press" / "advanced_television_2026-08-13.html"
URL = "https://www.advanced-television.com/2026/08/13/bank-ast-spacemobile-will-be-a-cash-flow-machine/"
ASTS = SimpleNamespace(ticker="ASTS", name="AST SpaceMobile, Inc.")
# Cifras de la captura de la nota de Clear Street (6-nov-2026), solo para verificar.
CAPTURA = {2027: 557, 2028: 1910}


def _article():
    html = FIXTURE.read_text()
    return ape.Article(URL, "Bank: AST SpaceMobile will be a cash-flow machine", date(2026, 8, 13),
                       ape.article_text(html))


def test_clear_street_ingresos_por_año_desde_la_prensa():
    reading = ape.read_article(_article(), company=ASTS)
    got = {(e.firm, e.metric, e.year): e.amount for e in reading.estimates}
    assert got[("Clear Street", "revenue", 2026)] == Decimal("165000000")  # «this year»
    assert got[("Clear Street", "revenue", 2027)] == Decimal("557000000")
    assert got[("Clear Street", "revenue", 2028)] == Decimal("1900000000.0")
    assert got[("Clear Street", "revenue", 2034)] == Decimal("6997000000.000")
    # Verificación contra la captura: 2027 exacto; 2028 es el redondeo de prensa de 1.910 M$.
    assert got[("Clear Street", "revenue", 2027)] / 10**6 == CAPTURA[2027]
    assert abs(float(got[("Clear Street", "revenue", 2028)]) / 1e6 - CAPTURA[2028]) / CAPTURA[2028] < 0.01
    targets = {(e.firm, e.amount) for e in reading.targets}
    assert targets == {("B. Riley Securities", Decimal("85")), ("Piper Sandler", Decimal("98"))}


def test_frases_de_otra_empresa_o_de_consenso():
    text = ("Wall Street analysts expect Firefly to top $440 million this year and reach $1 billion in fiscal 2028.\n\n"
            "At today's price it's about 37x, and that needs consensus revenue to climb from $167.5 million this "
            "year to $1.73 billion in 2028.")
    reading = ape.read_article(ape.Article("https://x.example/a", "t", date(2026, 11, 6), text), company=ASTS)
    got = {(e.firm, e.year): e.amount for e in reading.estimates}
    assert got == {(ape.CONSENSUS_FIRM, 2026): Decimal("167500000.0"), (ape.CONSENSUS_FIRM, 2028): Decimal("1730000000.00")}


def test_precio_objetivo_y_accion():
    text = ("Piper Sandler downgraded AST SpaceMobile stock to Neutral from Overweight and cut its price target to $54. "
            "Clear Street disagreed. It reiterated a Buy rating and a $115 price target on AST SpaceMobile.")
    reading = ape.read_article(ape.Article("https://x.example/b", "t", date(2026, 10, 14), text), company=ASTS)
    assert {(e.firm, e.amount) for e in reading.targets} == {("Piper Sandler", Decimal("54")),
                                                             ("Clear Street", Decimal("115"))}
    assert reading.actions == {"Piper Sandler": "downgrade", "Clear Street": "reiterate"}


def test_rss_de_bing_trae_la_url_del_medio():
    rss = ("<rss><channel><item><title>Clear Street on AST</title><link>http://www.bing.com/news/apiclick.aspx?"
           "ref=FexRss&amp;aid=&amp;url=https%3a%2f%2f247wallst.com%2finvesting%2f2026%2f10%2f14%2fast&amp;c=1</link>"
           "<pubDate>Wed, 14 Oct 2026 14:00:00 GMT</pubDate></item></channel></rss>")
    assert ape.bing_items(rss) == [("https://247wallst.com/investing/2026/10/14/ast", "Clear Street on AST",
                                    date(2026, 10, 14))]


def test_robots_que_prohibe_se_salta_y_se_dice():
    html = FIXTURE.read_bytes()

    async def fetch(url):
        if url.endswith("/robots.txt"):
            body = b"User-agent: *\nDisallow: /2026/" if "advanced-television" in url else b""
            return body, "text/plain", url
        if "bing.com" in url:
            return b"<rss></rss>", "application/xml", url
        return html, "text/html", url

    rep = asyncio.run(ape.collect(ASTS, known_urls=[(URL, "Clear Street estimates", date(2026, 8, 13))],
                                  fetch=fetch, today=date(2026, 11, 8)))
    assert rep.skipped_robots == ["www.advanced-television.com"] and rep.readings == []


def _hist(firm, year, value, day):
    return ac.FirmEstimate(firm, "revenue", year, value, day, f"https://n.example/{firm}/{day}")


def test_agregado_mediana_rango_y_revisiones():
    history = [_hist("Clear Street", 2027, 500.0, date(2026, 5, 1)), _hist("Clear Street", 2027, 557.0, date(2026, 8, 13)),
               _hist("Deutsche Bank", 2027, 610.0, date(2026, 10, 12)), _hist("Roth Capital", 2027, 480.0, date(2026, 9, 1)),
               ac.FirmEstimate(ac.CONSENSUS_FIRM, "revenue", 2027, 609.1, date(2026, 11, 6), "https://c.example")]
    (item,) = ac.aggregate(history, {})
    assert (item["n_firms"], item["low"], item["median"], item["high"]) == (3, 480.0, 557.0, 610.0)
    assert item["revisions"] == [{"firm": "Clear Street", "from": 500.0, "to": 557.0,
                                  "from_date": "2026-05-01", "to_date": "2026-08-13"}]
    assert item["press_consensus"]["value_millions"] == 609.1
    assert item["weighting"]["status"] == "insufficient_history"


def test_backtest_regla_prerregistrada():
    actuals = {2021: 100.0, 2022: 120.0, 2023: 150.0, 2024: 200.0}
    history = []
    for year, real in actuals.items():
        history += [_hist("Precisa", year, real * 1.01, date(year, 6, 1)),
                    _hist("Media", year, real * 1.15, date(year, 6, 1)),
                    _hist("Mala", year, real * 1.40, date(year, 6, 1)),
                    _hist("Tardía", year, real, date(year + 1, 2, 1))]  # después del cierre: no cuenta
    errors = ac.firm_errors(history, actuals)
    assert "Tardía" not in errors and len(errors["Precisa"]) == 4
    check = ac.backtest(history, actuals)
    assert check["status"] == "validated" and check["years"] == 4
    assert check["weighted_median_error"] < check["simple_median_error"]
    short = ac.backtest(history, {2023: 150.0, 2024: 200.0})
    assert short["status"] == "insufficient_history" and short["needed_years"] == 3


@pytest.fixture()
def tenant_company():
    init_db()
    suffix = uuid4().hex[:6].upper()
    with SessionLocal() as db:
        tenant = Tenant(external_id=f"ape-{suffix}", name="ape")
        company = Company(ticker=f"AP{suffix}", name="AST SpaceMobile, Inc.", exchange="NASDAQ", currency="USD",
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


def test_guardado_por_firma_y_año_sin_pisar_lo_más_reciente(tenant_company):
    company_id, tenant_id, ticker = tenant_company
    newer = _article()
    older = ape.Article("https://old.example/a", "t", date(2026, 5, 2),
                        "Clear Street expects AST SpaceMobile revenue of $500 million in 2027.")
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        company = db.get(Company, company_id)
        readings = [(newer, ape.read_article(newer, company=company)), (older, ape.read_article(older, company=company))]
        out = ape.store_readings(db, company, tenant_id, readings)
        db.commit()
        key = ape.estimate_key("revenue", 2027, "Clear Street")
        assert key == "analyst.revenue.fy2027.clear_street"
        row = db.scalars(select(DeclaredInputValue).where(DeclaredInputValue.company_id == company_id,
                                                          DeclaredInputValue.input_key == key,
                                                          DeclaredInputValue.superseded_at.is_(None))).one()
        assert (row.base, row.as_of, row.method, row.status) == (Decimal("557000000"), date(2026, 8, 13), "analyst", "estimado")
        assert row.source_url == URL and "2027 of $557 million" in (row.source_quote or "")
        assert any(s["key"] == key for s in out["stored"])
        notes = db.scalars(select(AnalystNote).where(AnalystNote.ticker == ticker,
                                                     AnalystNote.firm == "Clear Street")).all()
        assert {n.note_date for n in notes} == {date(2026, 8, 13), date(2026, 5, 2)}
        agg = {(i["metric"], i["year"]): i for i in ac.aggregate(ac.history_for(db, company, tenant_id), {})}
        assert agg[("revenue", 2027)]["revisions"][0]["from"] == 500.0
        assert agg[("revenue", 2027)]["median"] == 557.0
