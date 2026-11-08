"""Guía de la empresa citada de sus notas de resultados (fuentes-1, 8-nov-2026).

Frases reales de los EX-99 de los 8-K de la cartera de Nico: ASTS (10-ago-2026),
AMZN (29-oct-2026), POOL (22-oct-2026) y META (21-oct-2026). Antes GerarAI no
guardaba ninguna previsión y el servicio móvil directo de ASTS salía
«infravalorado por falta de estimaciones»; ahora la guía oficial de ingresos
2026 (150-200 M$) llega a los expertos como dato citado.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.declared_input_value import DeclaredInputValue
from app.models.entities import Base, Company, Document, DocumentChunk, Tenant
from app.services.company_guidance import extract_guidance, refresh_company_guidance
from app.services.expert_team.models import RunContext
from app.services.expert_team.sotp_valuer import analyst_estimates_tool

ASTS = (
    "Government with an aggregate value of over $125 million supporting multiple national-security applications "
    "On track to achieve full year 2026 revenue guidance of $150.0 million to $200.0 million, supported by "
    "additional contract awards from the U.S. Government. First quarter revenue was $14.7 million, consistent "
    "with plans for quarterly revenue ramp during 2026. Revenue backlog increased to approximately $1.30 billion "
    "in aggregate contracted revenue agreements, expected to convert in 2027."
)
AMZN = (
    "Our results are inherently unpredictable and may be materially affected by many factors detailed below. "
    "Fourth Quarter 2026 Guidance•Net sales are expected to be between $240.0 billion and $247.0 billion, or to "
    "grow between 12% and 16% compared with fourth quarter 2025. This guidance anticipates an unfavorable impact "
    "of approximately 60 basis points from foreign exchange rates.•Operating income is expected to be between "
    "$28.5 billion and $33.5 billion, compared with $25.0 billion in fourth quarter 2025. •We continue to expect "
    "2026 cash capital expenditures to be approximately $220 billion."
)
POOL = (
    "Outlook“Based on our performance to date and outlook for the remainder of the year, we are confirming our "
    "full-year adjusted diluted EPS guidance range of $10.87 to $11.17. As we look forward to closing out 2026."
)
META = "CFO Outlook CommentaryWe expect fourth quarter 2026 total revenue to be in the range of $73-76 billion."


def _by_key(items):
    return {g.input_key: g for g in items}


def test_asts_guia_de_ingresos_2026_y_nada_de_resultados_ni_backlog():
    got = _by_key(extract_guidance(ASTS, published=date(2026, 8, 10)))
    assert list(got) == ["guidance.revenue.fy2026"]
    g = got["guidance.revenue.fy2026"]
    assert (g.low, g.base, g.high, g.currency) == (Decimal("150000000.0"), Decimal("175000000.0"),
                                                    Decimal("200000000.0"), "USD")
    assert "$150.0 million to $200.0 million" in g.quote and g.period_read == "explicito"


def test_amzn_vinetas_bajo_el_titulo_de_la_seccion_y_capex_del_ano():
    got = _by_key(extract_guidance(AMZN, published=date(2026, 10, 29)))
    assert set(got) == {"guidance.revenue.q4_2026", "guidance.operating_income.q4_2026", "guidance.capex.fy2026"}
    assert got["guidance.revenue.q4_2026"].high == Decimal("247000000000.0")
    assert got["guidance.revenue.q4_2026"].period_read == "titulo_de_seccion"
    # «compared with fourth quarter 2025» no es el periodo previsto.
    assert got["guidance.operating_income.q4_2026"].low == Decimal("28500000000.0")
    capex = got["guidance.capex.fy2026"]
    assert capex.low is None and capex.base == Decimal("220000000000") and capex.period_read == "año_suelto"


def test_pool_bpa_ajustado_del_ejercicio_en_curso():
    got = _by_key(extract_guidance(POOL, published=date(2026, 10, 22)))
    g = got["guidance.adjusted_eps.fy2026"]
    assert (g.low, g.high) == (Decimal("10.87"), Decimal("11.17"))
    assert g.period_read == "ejercicio_del_documento"


def test_meta_rango_con_guion_y_escala_al_final():
    g = _by_key(extract_guidance(META, published=date(2026, 10, 21)))["guidance.revenue.q4_2026"]
    assert (g.low, g.high) == (Decimal("73000000000"), Decimal("76000000000"))


def test_periodo_pasado_o_sin_palabra_de_prevision_no_es_guia():
    assert extract_guidance("Full year 2025 revenue guidance of $50 million to $75 million was achieved.",
                            published=date(2026, 3, 2)) == []
    assert extract_guidance("Revenue for fiscal 2026 of $150 million to $200 million.",
                            published=date(2026, 3, 2)) == []


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.flush()
        session.info["tenant_id"] = 1
        yield session


def _doc(db, company, url, day, text):
    doc = Document(tenant_id=1, company_id=company.id, title=f"8-K EX-99.1 ({day})", source_type="press_release",
                   source_url=url, published_at=datetime.fromisoformat(day).replace(tzinfo=UTC))
    db.add(doc)
    db.flush()
    db.add(DocumentChunk(tenant_id=1, document_id=doc.id, chunk_index=0, text=text, token_count=10))
    db.flush()
    return doc


def test_se_guarda_como_dato_oficial_citado_y_llega_a_los_expertos(db):
    company = Company(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD", sector="T",
                      industry="T", company_type="operating", valuation_model="pre_revenue")
    db.add(company)
    db.flush()
    old = "On track to achieve full year 2026 revenue guidance of $120.0 million to $180.0 million."
    _doc(db, company, "https://www.sec.gov/Archives/edgar/data/1780312/a/ex99_1.htm", "2026-05-11", old)
    new = _doc(db, company, "https://www.sec.gov/Archives/edgar/data/1780312/b/asts-ex99_1.htm", "2026-08-10", ASTS)
    out = refresh_company_guidance(db, company, 1, today=date(2026, 11, 8))
    assert [s["key"] for s in out["guidance"]] == ["guidance.revenue.fy2026"]
    row = db.scalars(select(DeclaredInputValue).where(DeclaredInputValue.superseded_at.is_(None))).one()
    # La nota más reciente gana; dato oficial con frase, URL, documento y fecha.
    assert (row.method, row.status, row.unit) == ("extract", "oficial", "USD")
    assert row.low == Decimal("150000000") and row.high == Decimal("200000000")
    assert row.source_url == new.source_url and row.document_id == new.id and row.as_of == date(2026, 8, 10)
    assert "$150.0 million to $200.0 million" in row.source_quote
    assert row.metadata_["kind"] == "company_guidance"
    # Idempotente: misma guía, ninguna versión nueva.
    again = refresh_company_guidance(db, company, 1, today=date(2026, 11, 8))
    assert again["guidance"][0]["action"] == "unchanged"
    tool = analyst_estimates_tool(db).fn(RunContext(tenant_id=1, ticker="ASTS", mode="thesis", lang="es"))
    guide = [o for o in tool if o.data.get("kind") == "guia"]
    assert len(guide) == 1
    assert guide[0].data["low"] == 150.0 and guide[0].data["high"] == 200.0
    assert guide[0].data["unit"] == "millones de USD" and guide[0].source["url"] == new.source_url



def test_la_metrica_de_otra_cifra_o_una_perdida_de_segmento_no_es_guia():
    """META 10-Q (29-oct-2026): «operating profit» es de los 12,78 mil M$ ya pasados y lo previsto son
    las PÉRDIDAS de Reality Labs; antes se guardaba como beneficio operativo de la empresa (18.500 M$)."""
    meta_rl = ("During the nine months ended September 30, 2026, our RL segment reduced our overall operating "
               "profit by approximately $12.78 billion, and we expect our full-year 2026 RL operating losses to be "
               "approximately $18 billion to $19 billion.")
    assert extract_guidance(meta_rl, published=date(2026, 10, 29)) == []
    ok = extract_guidance("We expect full-year 2026 operating income of $2.0 billion to $2.2 billion.",
                          published=date(2026, 10, 29))
    assert [(g.metric, g.period, g.base) for g in ok] == [("operating_income", "fy2026", Decimal("2100000000.0"))]
