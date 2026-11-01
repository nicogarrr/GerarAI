"""Expertos del equipo: prompts versionados, listas blancas y herramientas de solo lectura.

SQLite en memoria y LLM falso: sin red.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact, NewsEvent, Position, RiskEvent, ThesisVersion
from app.services import prompt_registry
from app.services.expert_team import ExpertTeam, RunContext, build_tools, default_experts

TODAY = date(2026, 11, 1)
EXPECTED_TOOLS = {
    "fundamental": ("financial_facts",),
    "valuation": ("valuation_engine",),
    "risk": ("risk_events", "portfolio_concentration"),
    "news": ("news_events",),
    "tax": ("user_position", "irpf_savings_bands"),
}


@pytest.fixture()
def db(monkeypatch):
    from app.services import valuation_service

    def fake_value(self, db, company, *, as_of=None):
        return {"model_type": "dcf", "current_price": 400.0, "base_value": 450.0, "margin_of_safety": 0.11,
                "trace": {"price_as_of": "2026-10-31"}}

    monkeypatch.setattr(valuation_service.ValuationService, "value_company", fake_value)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        msft = Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD", company_type="operating", valuation_model="dcf")
        other = Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD", company_type="operating", valuation_model="dcf")
        session.add_all([msft, other])
        session.flush()
        for tenant, revenue, secret in ((1, 245.0, "A-NEWS"), (2, 999.0, "B-NEWS")):
            session.add_all(
                [
                    FinancialFact(tenant_id=tenant, company_id=msft.id, metric="revenue", value=revenue, unit="USD_bn",
                                  period="FY", fiscal_year=2025, source_type="SEC", source_id="10-K-2025",
                                  is_reported=True),
                    NewsEvent(tenant_id=tenant, company_id=msft.id, date=date(2026, 10, 20), title=secret,
                              source="Reuters", url="https://example.com/n", materiality_score=70),
                    RiskEvent(tenant_id=tenant, company_id=msft.id, severity="high", event_type="leverage",
                              message=f"deuda {secret}", status="open"),
                    Position(tenant_id=tenant, company_id=msft.id, quantity=10, average_cost=300,
                             market_value_base=4000.0 if tenant == 1 else 1.0, currency="USD"),
                    Position(tenant_id=tenant, company_id=other.id, quantity=5, average_cost=100,
                             market_value_base=6000.0, currency="USD"),
                ]
            )
        session.add(ThesisVersion(tenant_id=1, company_id=msft.id, version=3, status="published", thesis_markdown="x", executive_summary="x",
                                  rating="buy", current_price=400.0, base_value=460.0))
        session.commit()
        yield session


def test_every_expert_has_versioned_bilingual_prompt():
    for spec in default_experts():
        definition = prompt_registry.PROMPTS[spec.prompt_name]
        assert definition.version == "expert-team-v1"
        assert definition.text_en and "English" in definition.text_en
        assert "español" in definition.text


def test_whitelists_are_exactly_the_expected_read_tools(db):
    experts = {s.name: s.tools for s in default_experts()}
    assert experts == EXPECTED_TOOLS
    tools = build_tools(db, today=TODAY)
    assert set(tools) == {t for names in EXPECTED_TOOLS.values() for t in names}
    ExpertTeam(default_experts(), tools, _reasoner)  # lista blanca válida


def test_tools_are_read_only(db):
    statements: list[str] = []

    def spy(conn, cursor, statement, *args):
        statements.append(statement.strip().split()[0].upper())

    event.listen(db.get_bind(), "before_cursor_execute", spy)
    try:
        ctx = RunContext(tenant_id=1, ticker="MSFT", holds_position=True)
        for tool in build_tools(db, today=TODAY).values():
            tool.fn(ctx)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", spy)
    assert statements and set(statements) == {"SELECT"}
    assert not db.new and not db.dirty and not db.deleted


def test_tools_only_return_the_runs_tenant(db):
    tools = build_tools(db, today=TODAY)
    ctx = RunContext(tenant_id=1, ticker="MSFT", holds_position=True)
    facts = tools["financial_facts"].fn(ctx)
    assert [f.data["values"]["revenue"] for f in facts] == [245.0]
    assert facts[0].source == {"table": "financial_facts", "filing": "SEC:10-K-2025", "period": "FY", "date": "2025"}
    news = tools["news_events"].fn(ctx)
    assert [n.data["title"] for n in news] == ["A-NEWS"]
    assert news[0].source["date"] == "2026-10-20" and news[0].source["source"] == "Reuters"
    risks = tools["risk_events"].fn(ctx)
    assert [r.data["message"] for r in risks] == ["deuda A-NEWS"]
    concentration = tools["portfolio_concentration"].fn(ctx)
    assert concentration.data["weight_pct"] == 40.0
    position = tools["user_position"].fn(ctx)
    assert position.data["quantity"] == 10.0 and position.source["table"] == "positions"


def test_tax_bands_come_from_the_tax_module(db):
    out = build_tools(db, today=TODAY)["irpf_savings_bands"].fn(RunContext(tenant_id=1))
    assert out.data["year"] == 2026
    assert [b["rate_pct"] for b in out.data["bands"]] == [19.0, 21.0, 23.0, 27.0, 30.0]


def test_valuation_tool_uses_the_engine(db):
    outs = build_tools(db, today=TODAY)["valuation_engine"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    engine = [o for o in outs if o.source["table"] == "valuation_engine"]
    assert engine and engine[0].data["base_value"] == 450.0 and engine[0].source["date"] == "2026-10-31"
    thesis = [o for o in outs if o.source["table"] == "thesis_versions"]
    assert thesis and thesis[0].data["base_value"] == 460.0 and thesis[0].source["version"] == "3"
    assert build_tools(db, today=TODAY)["valuation_engine"].fn(RunContext(tenant_id=2, ticker="MSFT"))[1:] == []


def test_unknown_ticker_gives_no_evidence(db):
    tools = build_tools(db, today=TODAY)
    ctx = RunContext(tenant_id=1, ticker="ZZZZ")
    assert tools["financial_facts"].fn(ctx) == []
    assert tools["news_events"].fn(ctx) == []
    assert tools["user_position"].fn(ctx) is None


def test_chat_plan_with_default_experts():
    team = ExpertTeam(default_experts(), _dummy_tools(), _reasoner)

    def plan(question: str) -> list[str]:
        return team.plan(RunContext(tenant_id=1, ticker="MSFT", mode="chat", question=question))

    assert plan("¿Está cara MSFT? dame su valoración") == ["valuation"]
    assert plan("riesgos y últimas noticias de MSFT") == ["risk", "news"]
    assert plan("¿cuánto IRPF pagaría si vendo?") == ["tax"]
    assert plan("pero hola") == []


async def _reasoner(system, user, max_tokens, task):
    payload = json.loads(user)
    claims = [
        {"text": json.dumps(ev["data"], ensure_ascii=False)[:120], "numbers": [], "citations": [ev["id"]]}
        for ev in payload["evidence"]
    ]
    return json.dumps({"summary": "", "stance": "neutral", "claims": claims})


def _dummy_tools():
    from app.services.expert_team import ToolSpec

    return {name: ToolSpec(name=name, fn=lambda ctx: None) for names in EXPECTED_TOOLS.values() for name in names}


def test_end_to_end_thesis_run_cites_real_tables_and_isolates_tenants(db):
    team = ExpertTeam(default_experts(), build_tools(db, today=TODAY), _reasoner)
    result = asyncio.run(team.run(RunContext(tenant_id=1, ticker="MSFT", holds_position=True)))
    assert result.plan == ["fundamental", "valuation", "risk", "news", "tax"]
    assert {r.expert: r.status for r in result.reports} == dict.fromkeys(result.plan, "ok")
    tables = {s["table"] for s in result.sources}
    assert {"financial_facts", "valuation_engine", "risk_events", "positions", "news_events"} <= tables
    blob = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "A-NEWS" in blob and "B-NEWS" not in blob and "999" not in blob
