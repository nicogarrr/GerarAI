"""Ancla iXBRL exacta de una cifra presentada (verificado en vivo el 8-nov-2026 en POOL,
META, AMZN, MSFT, WSO y AAPL: el id existe, es único y lleva a la cifra)."""
from __future__ import annotations

from datetime import date

from app.services.own_consensus import actuals_from_facts
from app.services.sec_fact_anchor import contexts, find_anchor, period_bounds, source_link

DOC = "https://www.sec.gov/Archives/edgar/data/945841/000119312526435644/pool-20260930.htm"
HTML = """
<xbrli:context id="c-1"><xbrli:entity><xbrli:identifier>945841</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="c-2"><xbrli:entity><xbrli:identifier>945841</xbrli:identifier>
<xbrli:segment><xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">x:PoolMember</xbrldi:explicitMember>
</xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>
</xbrli:context>
<xbrli:context id="c-3"><xbrli:entity><xbrli:identifier>945841</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>
</xbrli:context>
<td><ix:nonFraction unitRef="usd" contextRef="c-2" decimals="-3" name="us-gaap:Revenues" id="f-seg" scale="3"
 format="ixt:num-dot-decimal">900,000</ix:nonFraction></td>
<td><ix:nonFraction unitRef="usd" contextRef="c-3" decimals="-3" name="us-gaap:Revenues" id="f-9m" scale="3"
 format="ixt:num-dot-decimal">4,465,909</ix:nonFraction></td>
<td>$<ix:nonFraction unitRef="usd" contextRef="c-1" decimals="-3" name="us-gaap:Revenues" id="F_0d57"
 scale="3" format="ixt:num-dot-decimal">1,504,957</ix:nonFraction></td>
<td>(<ix:nonFraction unitRef="usd" contextRef="c-1" decimals="-3" name="us-gaap:OperatingIncomeLoss" id="f-oi"
 scale="3" sign="-" format="ixt:num-dot-decimal">1,200</ix:nonFraction>)</td>
"""


def test_contexts_tell_dimensional_from_plain() -> None:
    ctx = contexts(HTML)
    assert ctx["c-1"].start == date(2026, 7, 1) and not ctx["c-1"].dimensional
    assert ctx["c-2"].dimensional is True


def test_anchor_is_the_plain_quarter_with_the_same_value() -> None:
    a = find_anchor(HTML, concepts=("us-gaap:Revenues",), end=date(2026, 9, 30), start=date(2026, 7, 1),
                    value=1504957000, doc_url=DOC)
    assert a is not None and a.element_id == "F_0d57" and a.url == DOC + "#F_0d57"
    assert find_anchor(HTML, concepts=("us-gaap:Revenues",), end=date(2026, 9, 30), start=date(2026, 7, 1),
                       value=1504000000, doc_url=DOC) is None  # otro valor: no es esa cifra


def test_source_link_reported_vs_derived() -> None:
    link = source_link(metric="revenue", period="2026-09-30:Q3", value=1504957000, doc_url=DOC, html=HTML)
    assert link["calc_type"] == "reported" and link["anchor"] == "F_0d57" and link["url"].endswith("#F_0d57")
    neg = source_link(metric="operating_income", period="2026-09-30:Q3", value=-1200000, doc_url=DOC, html=HTML)
    assert neg["anchor"] == "f-oi"
    acts = actuals_from_facts([("2025-12-31:FY", 400.0, None, DOC), ("2025-03-31:Q1", 90.0, None, DOC),
                               ("2025-06-30:Q2", 110.0, None, DOC), ("2025-09-30:Q3", 100.0, None, DOC)],
                              metric="revenue")
    q4 = acts["q4_2025"]
    derived = source_link(metric="revenue", period="2025-12-31:Q4", value=q4.value, doc_url=q4.url, html=None,
                          derived_formula=q4.formula)
    assert derived["calc_type"] == "derived" and "9M" in derived["formula"] and derived["anchor"] is None


def test_period_bounds_calendar_and_52_week_years() -> None:
    assert period_bounds("2026-09-30:Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert period_bounds("2025-12-31:FY") == (date(2025, 1, 1), date(2025, 12, 31))
    assert period_bounds("2026-06-27:Q3")[0] is None  # 13 semanas: el inicio lo pone el contexto



# ---------------------------------------------------------------------- rutas (sin red)
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.entities import Base, Company, FinancialFact, Tenant  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.flush()
        session.info["tenant_id"] = 1
        yield session


def test_routes_derived_q4_and_own_consensus(db) -> None:
    from app.api.routes.estimates import fact_source_link, own_consensus

    c = Company(ticker="ACME", name="Acme", exchange="NYSE", currency="USD", sector="T", industry="T",
                company_type="operating", valuation_model="standard_dcf")
    db.add(c)
    db.flush()
    for period, v in (("2025-03-31:Q1", 90), ("2025-06-30:Q2", 110), ("2025-09-30:Q3", 100), ("2025-12-31:FY", 400)):
        db.add(FinancialFact(tenant_id=1, company_id=c.id, metric="revenue", value=v, period=period,
                             source_type="SEC"))
    db.flush()
    link = fact_source_link("ACME", metric="revenue", period="2025-12-31:Q4", db=db)
    assert link["calc_type"] == "derived" and link["value"] == 100.0 and "9M" in link["formula"]
    no_sec = fact_source_link("ACME", metric="revenue", period="2025-09-30:Q3", db=db)
    assert no_sec["anchor"] is None and "sin filing" in no_sec["reason"]
    out = own_consensus("ACME", db=db)
    assert out["source_order"][0] == "guia" and "accuracy" in out and out["cells"]
