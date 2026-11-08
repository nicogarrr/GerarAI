"""Acierto medido: estimación congelada antes del cierre frente al dato real, y el
historial de la guía reconstruido desde 8-K antiguos."""
from __future__ import annotations

from datetime import date

from app.services.estimate_accuracy import Estimate, cases, measured_errors, summarize
from app.services.guidance_backfill import backfill_rows, earnings_8ks, ex991_url, html_text
from app.services.own_consensus import Actual, confidence_for

ACTS = {"revenue": {
    "fy2024": Actual("fy2024", date(2024, 12, 31), 1000.0), "fy2025": Actual("fy2025", date(2025, 12, 31), 1100.0),
    "q1_2025": Actual("q1_2025", date(2025, 3, 31), 260.0), "q2_2025": Actual("q2_2025", date(2025, 6, 30), 280.0)}}


def test_only_the_last_estimate_before_period_end_counts() -> None:
    est = [Estimate("guia", "revenue", "fy2025", 1000.0, 1050.0, 1080.0, date(2025, 2, 1)),
           Estimate("guia", "revenue", "fy2025", 1060.0, 1080.0, 1100.0, date(2025, 10, 30)),
           Estimate("guia", "revenue", "fy2025", 1100.0, 1100.0, 1100.0, date(2026, 2, 1))]  # tras el cierre
    got = cases(est, ACTS)
    assert len(got) == 1
    c = got[0]
    assert c["as_of"] == "2025-10-30" and c["horizon"] == "≤1T"
    assert abs(c["error"] - (1100 / 1080 - 1)) < 1e-12 and c["inside_range"] is True


def test_summary_by_source_and_horizon_and_feeds_confidence() -> None:
    est = [Estimate("guia", "revenue", f"q{q}_2025", None, v, None, date(2025, 3 * q - 2, 5))
           for q, v in ((1, 250.0), (2, 270.0))]
    est.append(Estimate("analista:Firma A", "revenue", "fy2025", None, 1000.0, None, date(2025, 1, 15)))
    got = cases(est, ACTS)
    rows = {(r["source"], r["horizon"]): r for r in summarize(got)}
    assert rows[("guia", "≤1T")]["n"] == 2
    assert rows[("guia", "≤1T")]["median_bias"] > 0  # el dato supera la guía
    assert rows[("analista:Firma A", "≤1A")]["n"] == 1
    errs = measured_errors(got)
    assert ("analista_citado", "≤1A") in errs and len(errs[("guia", "≤1T")]) == 2
    conf = confidence_for("guia", "≤1T", errs)
    assert conf["level"] == "bajo" and "muestra pequeña" in conf["reason"]
    conf8 = confidence_for("guia", "≤1T", {("guia", "≤1T"): [0.01] * 8})
    assert conf8["level"] == "alto" and conf8["n"] == 8


def test_implausible_reading_is_set_aside_with_its_reason() -> None:
    est = [Estimate("guia", "revenue", "fy2025", None, 110.0, None, date(2025, 2, 1))]  # escala mal leída
    got = cases(est, ACTS)
    assert got and got[0]["excluded"].startswith("lectura_inverosímil")
    # apartada, pero contada en el resumen (nada se aparta en silencio)
    [row] = summarize(got)
    assert row["n"] == 0 and row["n_excluded"] == 1 and row["excluded_reasons"] == ["lectura_inverosímil"]
    assert measured_errors(got) == {}


SUB = {"filings": {"recent": {
    "accessionNumber": ["0000000001-25-000010", "0000000001-25-000011", "0000000001-19-000001"],
    "form": ["8-K", "8-K", "8-K"], "items": ["2.02,9.01", "5.07", "2.02"],
    "filingDate": ["2025-10-23", "2025-06-01", "2019-02-01"]}}}
OLDER = {"accessionNumber": ["0000000001-24-000005"], "form": ["8-K"], "items": ["2.02,9.01"],
         "filingDate": ["2024-10-24"]}


def test_earnings_8ks_are_item_202_within_the_window_oldest_first() -> None:
    got = earnings_8ks(SUB, since=date(2020, 1, 1), older=[OLDER])
    assert [f["accession"] for f in got] == ["0000000001-24-000005", "0000000001-25-000010"]


def test_ex991_link_and_text_from_the_index() -> None:
    index = ('<tr><td scope="row">1</td><td scope="row">Press</td><td scope="row">'
             '<a href="/Archives/edgar/data/1/000000000125000010/ex991.htm">ex991.htm</a></td>'
             '<td scope="row">EX-99.1</td><td scope="row">51234</td></tr>')
    assert ex991_url(index) == "https://www.sec.gov/Archives/edgar/data/1/000000000125000010/ex991.htm"
    assert html_text("<p>Revenue&nbsp;of&#160;<b>$1.2</b> billion</p>") .strip() == "Revenue of $1.2 billion."


def test_backfill_rows_keep_each_revision_until_the_next_document() -> None:
    a = "The Company now expects full-year 2025 revenue of $1.00 billion to $1.10 billion."
    b = "The Company now expects full-year 2025 revenue of $1.05 billion to $1.15 billion."
    rows = backfill_rows([(date(2025, 7, 24), "https://sec/b", b), (date(2025, 4, 24), "https://sec/a", a)])
    rows = sorted(rows, key=lambda r: r["published"])
    assert [r["key"] for r in rows] == ["guidance.revenue.fy2025"] * 2
    assert rows[0]["superseded"] == date(2025, 7, 24) and rows[1]["superseded"] is None
    assert float(rows[0]["item"].base) == 1.05e9 and rows[1]["url"] == "https://sec/b"



# ---------------------------------------------------------------------- con BD (sqlite en memoria)
import pytest  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.declared_input_value import DeclaredInputValue  # noqa: E402
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


def test_backfill_freeze_and_measured_beat_end_to_end(db) -> None:
    from app.services.estimate_accuracy import company_accuracy, freeze_consensus
    from app.services.expert_team.models import RunContext
    from app.services.expert_team.sotp_valuer import analyst_estimates_tool
    from app.services.guidance_backfill import ensure_backfill
    from app.services.own_consensus import build_company_consensus

    company = Company(ticker="ACME", name="Acme", exchange="NYSE", currency="USD", sector="T", industry="T",
                      company_type="operating", valuation_model="standard_dcf", cik="0000000001")
    db.add(company)
    db.flush()
    rev = {2021: [100, 110, 120, 130], 2022: [105, 116, 126, 137], 2023: [110, 121, 132, 144],
           2024: [116, 128, 139, 151], 2025: [122, 134, 146, 159], 2026: [128, 141, 153]}
    ends = ("03-31", "06-30", "09-30", "12-31")
    for y, qs in rev.items():
        for i, v in enumerate(qs):
            if i < 3:
                db.add(FinancialFact(tenant_id=1, company_id=company.id, metric="revenue", value=v * 1e6,
                                     period=f"{y}-{ends[i]}:Q{i + 1}", source_type="SEC", filed=date(y, 3 * i + 4, 28)))
        if len(qs) == 4:
            db.add(FinancialFact(tenant_id=1, company_id=company.id, metric="revenue", value=sum(qs) * 1e6,
                                 period=f"{y}-12-31:FY", fiscal_year=y, source_type="SEC", filed=date(y + 1, 2, 20)))
    db.flush()
    # 8-K antiguos: cada año la empresa guía el 3 % por debajo de lo que luego presenta
    docs = []
    for y, qs in rev.items():
        total = sum(qs) if len(qs) == 4 else 600.0
        lo, hi = total / 1.03 * 0.99, total / 1.03 * 1.01
        docs.append((date(y, 7, 25), f"https://www.sec.gov/{y}/ex991.htm",
                     f"The Company now expects full-year {y} revenue of ${lo:.1f} million to ${hi:.1f} million."))

    def fake_fetch(cik, *, today=None):
        return {"filings": len(docs), "documents": docs, "misses": 0}

    out = ensure_backfill(db, company, 1, fetch=fake_fetch)
    assert out["status"] == "ok" and out["stored"] == 6
    assert ensure_backfill(db, company, 1, fetch=fake_fetch)["status"] == "done_before"
    rows = db.scalars(select(DeclaredInputValue).where(DeclaredInputValue.input_key == "guidance.revenue.fy2026")).all()
    assert rows and all(r.superseded_at is not None for r in rows)  # histórico: no es la guía vigente

    acc = company_accuracy(db, company, 1)
    guia = [r for r in acc["by_source"] if r["source"] == "guia"]
    assert guia and guia[0]["n"] == 5 and abs(guia[0]["median_bias"] - 0.03) < 0.002

    result = build_company_consensus(db, company, 1, today=date(2026, 11, 8))
    cells = {c["key"]: c for c in result["cells"]}
    fy = cells["estimate.revenue.fy2026"]
    assert fy["status"] == "estimado" and fy["source"] == "modelo"  # la guía 2026 es histórica, no vigente
    assert "tasa base" in fy["formula"] and result["base_rate"]["n"] > 0
    stats = freeze_consensus(db, company, 1, result, today=date(2026, 11, 8))
    assert stats["frozen"] >= 3
    again = freeze_consensus(db, company, 1, result, today=date(2026, 11, 9))
    assert again["frozen"] == 0 and again["unchanged"] == stats["frozen"]
    frozen = db.scalars(select(DeclaredInputValue).where(DeclaredInputValue.input_key == "estimate.revenue.fy2026",
                                                         DeclaredInputValue.superseded_at.is_(None))).one()
    assert frozen.method == "derive" and frozen.metadata_["source"] == "modelo" and frozen.as_of == date(2026, 11, 8)

    tool = analyst_estimates_tool(db).fn(RunContext(tenant_id=1, ticker="ACME", mode="thesis", lang="es"))
    own = [o for o in tool if o.data.get("kind") == "own_consensus"]
    assert {o.data["period"] for o in own} >= {"fy2026", "q4_2026", "fy2027"}
