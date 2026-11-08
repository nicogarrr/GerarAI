"""Desglose por partes generado por el equipo de expertos (dca-valor-8).

Nico, 8-nov-2026 11:11: el ASTS pegado «son un ejemplo de valoración… quiero que
quede ahí con nuestros agentes expertos». Respuestas del modelo GRABADAS (sin LLM).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.data.sotp_examples import ASTS_NICO_2026_11_08
from app.models.entities import Base, Company, FinancialFact, MarketPrice, Tenant, WorkflowRun
from app.services import prompt_registry
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import RunContext, ToolOutput, ToolSpec
from app.services.expert_team.roster import default_experts, pipeline_experts, sotp_valuer_expert
from app.services.expert_team.sotp_valuer import (
    SOTP_VALUER_NAME,
    generate_sotp_proposal,
    parse_proposal,
    run_sotp_valuer,
)
from app.services.user_sotp_service import (
    AGENTS_ASSUMPTIONS_LABEL,
    AGENTS_SEGMENT,
    EXAMPLE_LABEL,
    UserSotpService,
)

T1 = 1
TODAY = date(2026, 11, 8)

ANCHORS = {
    "ticker": "SYNTH", "company": "Synth Inc", "today": "2026-11-08", "base_year": 2026, "currency": "USD",
    "price": 32.0, "price_as_of": "2026-11-06", "shares_current_millions": 300.0, "shares_basis": "shares_outstanding",
    "shares_period_end": "2026-06-30", "cash_millions": 1000.0, "debt_millions": 400.0,
    "balance_period_end": "2026-06-30", "discount_rate": 0.11, "discount_rate_source": "calculated_metric",
    "revenue_actuals": [{"period_end": "2025-12-31", "revenue_millions": 5.0}], "burns_cash": True,
    "base_rate_message": "…",
}


EV_TEXT = ("Definitive agreement with Operator A: contracted backlog of $1.2 billion over 6 years. "
           "The ministry selected us for up to $750 million of non-dilutive funding for the program. "
           "We acquired spectrum rights for $500 million. 12,000,000 Class B shares are exchangeable. "
           "Operator B pilot revenue of $600 million expected.")


def _ledger() -> EvidenceLedger:
    ledger = EvidenceLedger()
    ledger.add(expert=SOTP_VALUER_NAME, tool="sotp_anchors", source={"table": "financial_facts", "title": "Acciones, caja y deuda (SEC)", "url": "/research/SYNTH?view=valuation"}, data={})
    ledger.add(expert=SOTP_VALUER_NAME, tool="value_drivers", source={"table": "value_drivers", "title": "Acuerdo definitivo con Operadora A", "url": "https://example.com/8k", "date": "2026-05-01"}, data={"text": EV_TEXT})
    ledger.add(expert="otro", tool="news_events", source={"table": "news_events"}, data={"text": EV_TEXT})
    return ledger


def _good(cite: str = "ev-2") -> dict:
    """Clasificación del modelo: estados, tipos y anclas copiadas; ni un múltiplo ni una probabilidad."""
    return {
        "summary": "Pesa el contrato con Operadora A. El resto está sin probar.",
        "segments": [
            {"group": "Mayorista", "name": "Operadora A (EE. UU.)", "status": "contratado",
             "business_type": "telecom_mayorista", "why_status": "acuerdo definitivo firmado",
             "anchor": {"type": "backlog", "amount_millions": 1200, "period": "total", "year": None, "years": 6,
                        "quote": "contracted backlog of $1.2 billion over 6 years", "citation": cite}},
            {"group": "Gobierno", "name": "Defensa", "status": "idea", "business_type": "contratos_gobierno",
             "why_status": "sin contrato", "anchor": None},
        ],
        "assets": [{"name": "Espectro", "status": "beta", "value_millions": 500, "quote": "spectrum rights for $500 million",
                    "citation": cite, "why": "precio pagado"}],
        "dilution": [{"label": "Clase B canjeable", "shares_millions": 12, "quote": "12,000,000 Class B shares",
                      "citation": cite, "why": "otra clase canjeable"}],
    }


def test_numbers_come_from_fixed_tables_and_cited_figures_with_a_formula_trace():
    model, problems = parse_proposal(_good(), _ledger(), ANCHORS)
    assert problems == []
    # El código fija la tasa CAPM, las acciones SEC, el año de madurez y la caja menos deuda.
    assert model["discount_rate"] == 0.11 and model["shares_current"] == 300.0 and model["valuation_year"] == 2030
    assert "CAPM" in model["discount_rate_source"] and model["rules_version"] == "sotp-rules-v2"
    cash = model["parts"][-1]
    assert cash["name"].startswith("Caja menos deuda") and cash["value"] == 600.0 and cash["discounted"] is False
    first = model["parts"][0]
    assert first["revenue"] == pytest.approx(200.0)  # backlog 1.200 M ÷ 6 años
    assert (first["ebitda_margin"], first["multiple"], first["probability"]) == (0.45, 8.0, 0.6)
    assert "1.200,0 M ÷ 6 años = 200,0 M/año" in first["why"]["revenue"]
    assert first["why"]["probability"].startswith("Estado «contratado» → 60 %")
    assert first["why"]["multiple"] == "Tabla «telecom_mayorista»: 8x EBITDA a madurez."
    assert first["sources"][0]["url"] == "https://example.com/8k" and first["commercial"] is False
    assert model["unvalued"] == [{"name": "Defensa", "status": "idea", "reason": "sin cifra de ingresos en la evidencia"}]
    assert model["dilution"][0]["shares"] == 12
    assert [s["key"] for s in model["scenarios"]] == ["bear", "bull"]
    from app.valuation.sotp import run_user_sotp

    out = run_user_sotp(model, price=32.0)
    op = 200 * 0.45 * 8 * 0.6 / 1.11**4
    assert out["value_per_share"] == pytest.approx((op + 500 * 0.35 + 600) / 312)


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda p: p["segments"][0].update(status="rumor"), "estado 'rumor' fuera de la tabla"),
        (lambda p: p["segments"][0].update(business_type="cohetes"), "tipo de negocio 'cohetes'"),
        (lambda p: p["segments"][0]["anchor"].update(type="corazonada"), "tipo de ancla"),
        (lambda p: p.update(segments=[]), "faltan los segmentos"),
        (lambda p: p["segments"][0]["anchor"].update(amount_millions=1300), "ningún segmento"),
        (lambda p: p["segments"][0]["anchor"].update(citation="ev-3"), "ningún segmento"),
    ],
)
def test_classification_is_rejected_when_a_rule_fails(mutate, needle):
    raw = json.loads(json.dumps(_good()))
    mutate(raw)
    model, problems = parse_proposal(raw, _ledger(), ANCHORS)
    assert model is None
    assert any(needle in p for p in problems), problems


def test_a_figure_not_in_the_cited_evidence_is_never_used():
    from app.services.expert_team.sotp_valuer import parse_classification

    raw = _good()
    raw["segments"].append({"name": "Operadora B", "status": "beta", "business_type": "telecom_mayorista",
                            "anchor": {"type": "guia", "amount_millions": 900, "period": "anual", "year": 2028,
                                       "citation": "ev-2"}})
    raw["assets"][0]["value_millions"] = 5000
    raw["dilution"][0]["citation"] = "ev-3"  # evidencia de otro experto
    out, problems = parse_classification(raw, _ledger())
    assert problems == []
    reasons = {u["name"]: u["reason"] for u in out["unvalued"]}
    assert "no aparece en la evidencia citada" in reasons["Operadora B"]
    assert "no aparece" in reasons["Espectro"] and "sin cita válida" in reasons["Clase B canjeable"]
    assert [s["name"] for s in out["segments"]] == ["Operadora A (EE. UU.)"] and out["assets"] == []


def test_funding_or_a_third_party_investment_is_never_a_revenue_anchor():
    from app.services.expert_team.sotp_valuer import build_model, parse_classification

    raw = _good()
    raw["segments"].append({"name": "Programa del ministerio", "status": "beta", "business_type": "contratos_gobierno",
                            "anchor": {"type": "contrato", "amount_millions": 750, "period": "total",
                                       "quote": "up to $750 million of non-dilutive funding", "citation": "ev-2"}})
    out, problems = parse_classification(raw, _ledger())
    assert problems == [] and [s["name"] for s in out["segments"]] == ["Operadora A (EE. UU.)"]
    reason = {u["name"]: u["reason"] for u in out["unvalued"]}["Programa del ministerio"]
    assert "financiación o inversión" in reason
    # Una clasificación ya guardada pasa por la misma regla al recalcular (la cita se conserva).
    cached = json.loads(json.dumps(out))
    cached["segments"].append({"name": "Programa del ministerio", "status": "beta", "business_type": "contratos_gobierno",
                               "anchor": {"type": "contrato", "amount_millions": 750, "period": "total", "year": None,
                                          "years": None, "quote": "up to $750 million of non-dilutive funding",
                                          "sources": []}})
    model, _ = build_model(cached, ANCHORS)
    assert [p["name"] for p in model["parts"] if p["kind"] == "operating"] == ["Operadora A (EE. UU.)"]
    assert any(u["name"] == "Programa del ministerio" and "financiación" in u["reason"] for u in model["unvalued"])


def test_a_segment_without_estimates_is_flagged_and_guidance_shows_its_weight():
    raw = _good()
    model, _ = parse_proposal(raw, _ledger(), ANCHORS)
    assert any("«Operadora A (EE. UU.)»: infravalorado por falta de estimaciones" in w and "no hay guía" in w
               for w in model["warnings"])
    raw["segments"][0]["guidance_anchor"] = {"type": "guia", "amount_millions": 600, "year": 2028,
                                             "quote": "Operator B pilot revenue of $600 million expected",
                                             "citation": "ev-2"}
    model, _ = parse_proposal(raw, _ledger(), ANCHORS)
    flag = next(w for w in model["warnings"] if "infravalorado" in w)
    expected = 600 * 0.45 * 8 * 0.6 / 1.11**4 / 300
    assert "con la guía de la empresa" in flag and f"{expected:,.2f} $/acción" in flag
    # Sin recuento por clase (solo la media diluida de la SEC): aviso en la ficha.
    model, _ = parse_proposal(_good(), _ledger(), {**ANCHORS, "shares_basis": "shares_diluted"})
    assert any(w.startswith("Faltan clases de acciones") for w in model["warnings"])
    model, _ = parse_proposal(_good(), _ledger(), ANCHORS)
    assert not any(w.startswith("Faltan clases") for w in model["warnings"])


def test_summary_explains_but_never_brings_its_own_numbers():
    from app.services.expert_team.sotp_valuer import parse_classification

    raw = _good()
    raw["summary"] = "Pesa Operadora A. Vale 45 $ por acción. El servicio llega en 2027. Falta la licencia."
    out, _ = parse_classification(raw, _ledger())
    assert out["summary"] == "Pesa Operadora A. El servicio llega en 2027. Falta la licencia."


def test_revenue_rules_and_figures():
    from app.services.expert_team import sotp_rules as r

    assert r.figure_supported(1300, ["backlog of ~$1.3 billion"]) and r.figure_supported(89.38, ["89,381,000 shares"])
    assert r.figure_supported(2300, ['{"value": 2300000000}']) and not r.figure_supported(500, ["1.625% due 2034"])
    value, formula = r.revenue_rule({"type": "reportado", "amount_millions": 31.5, "period": "trimestral", "year": 2026},
                                    "comercial", base_year=2026, valuation_year=2030, historical_growth=2.0)
    assert value == pytest.approx(126 * 1.15**4) and "tope 15 %" in formula
    value, _ = r.revenue_rule({"type": "estimacion_analista", "amount_millions": 1000, "year": 2032},
                              "contratado", base_year=2026, valuation_year=2030, historical_growth=None)
    assert value == pytest.approx(1000 * 4 / 6)
    value, _ = r.revenue_rule({"type": "guia", "amount_millions": 300, "year": 2027}, "comercial",
                              base_year=2026, valuation_year=2030, historical_growth=None)
    assert value == 300
    assert r.conservative_status(["comercial", "beta"]) == "beta"


def test_code_dilution_sbc_and_funding_gap_with_formulas():
    from app.services.expert_team import sotp_rules as r

    anchors = {**ANCHORS, "sbc_annual_millions": 40.0, "annual_burn_millions": 900.0, "cash_millions": 1000.0,
               "short_term_investments_millions": 200.0}
    out = {d["label"]: d for d in r.code_dilution(anchors, 4)}
    sbc = out["Remuneración en acciones (SBC) hasta el año valorado"]
    assert sbc["shares"] == pytest.approx(40 * 4 / 32) and "÷ precio 32.00" in sbc["why"]["shares"]
    gap = out["Ampliaciones para cubrir la quema"]
    assert gap["shares"] == pytest.approx((900 * 2 - 1200) / 32)
    rich = {d["label"]: d for d in r.code_dilution({**anchors, "cash_millions": 5000.0}, 4)}
    assert rich["Ampliaciones para cubrir la quema"]["shares"] == 0.0


def test_without_capm_rate_or_sec_shares_there_is_no_proposal():
    for key in ("discount_rate", "shares_current_millions"):
        model, problems = parse_proposal(_good(), _ledger(), {**ANCHORS, key: None})
        assert model is None and problems


def test_valuer_is_a_team_role_with_whitelisted_read_tools_and_versioned_prompt():
    spec = sotp_valuer_expert()
    assert spec.name == SOTP_VALUER_NAME and spec.prompt_name == "expert_sotp"
    assert "value_drivers" in spec.tools and "company_documents" in spec.tools and "sotp_anchors" in spec.tools
    assert spec.name not in {e.name for e in default_experts()} | {e.name for e in pipeline_experts()}
    prompt = prompt_registry.get_prompt("expert_sotp", lang="es")
    assert prompt.version == "sotp-valuer-v2"
    for rule in ("No valoras: clasificas", "anchor null", "Nunca inventes", "explica sin cifras"):
        assert rule in prompt.text


def _fake_tools(anchors, extra_drivers=()):
    from app.services.expert_team.sotp_valuer import SOTP_VALUER_TOOLS, _anchor_outputs

    def drivers(ctx):
        out = [ToolOutput(source={"table": "value_drivers", "title": "Acuerdo definitivo con Operadora A",
                                  "url": "https://example.com/8k", "date": "2026-05-01"}, data={"text": EV_TEXT})]
        for extra in extra_drivers:
            out.append(ToolOutput(source={"table": "value_drivers", "title": extra, "url": "", "date": "2026-11-07"},
                                  data={"text": extra}))
        return out

    tools = {name: ToolSpec(name=name, fn=lambda ctx: [], description="") for name in SOTP_VALUER_TOOLS}
    tools["sotp_anchors"] = ToolSpec(name="sotp_anchors", fn=lambda ctx: _anchor_outputs(anchors), description="")
    tools["value_drivers"] = ToolSpec(name="value_drivers", fn=drivers, description="")
    return tools


class _Recorded:
    """Razonador grabado: primero una respuesta que rompe una regla, luego una válida."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, system, user, max_tokens, task):
        self.calls.append({"system": system, "user": json.loads(user), "task": task})
        return self.answers.pop(0)


def _good_for_tools() -> dict:
    # Con _fake_tools: ev-1..ev-5 son los anclajes y ev-6 el impulsor.
    return _good("ev-6")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=T1, external_id="t1"))
        session.flush()
        session.info["tenant_id"] = T1
        yield session


def _company(db, ticker="SYNTH"):
    company = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD", sector="Telecom",
                      industry="Telecom Services", company_type="operating", valuation_model="pre_revenue")
    db.add(company)
    db.flush()
    return company


def test_valuer_retries_once_with_the_problems_then_returns_the_model(db):
    _company(db)
    bad = json.loads(json.dumps(_good_for_tools()))
    bad["segments"][0]["status"] = "rumor"
    reasoner = _Recorded([json.dumps(bad), "```json\n" + json.dumps(_good_for_tools()) + "\n```"])
    ctx = RunContext(tenant_id=T1, ticker="SYNTH", mode="thesis", lang="es")
    result = asyncio.run(run_sotp_valuer(db, ctx=ctx, reasoner=reasoner, tools=_fake_tools(ANCHORS), anchors=ANCHORS))
    assert result.status == "ok" and result.llm_calls == 2
    assert any("rumor" in p for p in reasoner.calls[1]["user"]["problems_previous_answer"])
    assert reasoner.calls[0]["task"] == "expert_team.valorador_sotp"
    assert "No valoras: clasificas" in reasoner.calls[0]["system"]
    assert result.model["parts"][0]["sources"][0]["url"] == "https://example.com/8k"


def test_valuer_gives_up_after_two_bad_answers_and_saves_nothing(db):
    company = _company(db)
    bad = json.dumps({"segments": []})
    reasoner = _Recorded([bad, bad])
    ctx = RunContext(tenant_id=T1, ticker="SYNTH", mode="thesis", lang="es")
    result = asyncio.run(run_sotp_valuer(db, ctx=ctx, reasoner=reasoner, tools=_fake_tools(ANCHORS), anchors=ANCHORS))
    assert result.status == "rejected" and result.model is None
    assert UserSotpService().read(db, company, T1)["available"] is False


def _seed_market(db, company):
    from decimal import Decimal

    db.add(MarketPrice(company_id=company.id, date=date(2026, 11, 6), close=Decimal("32"), volume=1000,
                       quote_currency="USD"))
    for metric, value, unit in (("shares_outstanding", 300e6, "shares"), ("cash_and_equivalents", 1000e6, "USD"),
                                ("total_debt", 400e6, "USD")):
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
                             period="2026-06-30:Q2", fiscal_quarter="Q2", source_type="SEC", is_reported=True))
    for metric, value in (("net_income", -300e6), ("operating_cash_flow", -200e6), ("revenue", 5e6)):
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(str(value)), unit="USD",
                             period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY", source_type="SEC",
                             is_reported=True))
    db.flush()


def test_anchors_come_from_gerarai_data_not_from_the_model(db):
    from app.services.expert_team.sotp_valuer import sotp_anchors

    company = _company(db)
    _seed_market(db, company)
    anchors = sotp_anchors(db, company, today=TODAY)
    assert anchors["price"] == pytest.approx(32.0) and anchors["currency"] == "USD"
    assert anchors["shares_current_millions"] == pytest.approx(300.0)
    assert anchors["cash_millions"] == pytest.approx(1000.0) and anchors["debt_millions"] == pytest.approx(400.0)
    assert anchors["burns_cash"] is True
    assert anchors["base_year"] == 2026
    assert anchors["discount_rate"] is None or 0.0 < anchors["discount_rate"] < 0.4


def _generate(db, company, monkeypatch, answers, extra_drivers=(), narrative=False, **kw):
    from app.services.expert_team import sotp_valuer

    monkeypatch.setattr(sotp_valuer, "sotp_anchors", lambda db, company, today=None: dict(ANCHORS, ticker=company.ticker))
    monkeypatch.setattr(sotp_valuer, "build_sotp_tools", lambda db, anchors: _fake_tools(anchors, extra_drivers))
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "sotp_agents_narrative_enabled", narrative, raising=False)
    reasoner = _Recorded(answers)
    out = generate_sotp_proposal(db, company, reasoner=reasoner, **kw)
    out.calls = len(reasoner.calls)
    return out


def test_agents_version_is_the_default_and_nicos_example_stays(db, monkeypatch):
    asts = _company(db, "ASTS")
    service = UserSotpService()
    assert service.read(db, asts, T1)["variant"] == "example"

    out = _generate(db, asts, monkeypatch, [json.dumps(_good_for_tools())], thesis_version_id=7, trigger="thesis")
    assert out.status == "stored" and out.row_id
    shown = service.read(db, asts, T1)
    assert shown["variant"] == shown["default_variant"] == "agents" and shown["origin"] == "agents"
    assert shown["label"] == AGENTS_ASSUMPTIONS_LABEL and shown["validated"] is False
    assert shown["agents"]["thesis_version_id"] == 7 and shown["agents"]["price"] == 32.0
    assert shown["agents"]["generated_at"]
    keys = {v["key"]: v for v in shown["variants"]}
    assert keys["agents"]["available"] and keys["example"]["available"] and not keys["user"]["available"]
    assert keys["example"]["label"] == EXAMPLE_LABEL
    # El ejemplo pegado por Nico sigue ahí, intacto.
    example = service.read(db, asts, T1, variant="example")
    assert example["origin"] == "example" and example["result"]["value_per_share"] == pytest.approx(155.82, abs=0.01)
    assert example["default_variant"] == "agents"

    # Lo editado por el usuario gana solo si es posterior a la propuesta.
    later = service.save(db, asts, T1, {**ASTS_NICO_2026_11_08, "discount_rate": 0.15})
    assert later["variant"] == "user"
    assert service.read(db, asts, T1)["default_variant"] == "user"
    _generate(db, asts, monkeypatch, [json.dumps(_good_for_tools())], use_cache=False)
    assert service.read(db, asts, T1)["default_variant"] == "agents"
    assert len(service.inputs.history(db, company_id=asts.id, tenant_id=T1, input_key="sotp_user_model",
                                      segment_key=AGENTS_SEGMENT)) == 2


def test_agents_proposal_never_feeds_the_engines(db, monkeypatch):
    from app.models.declared_input_value import DeclaredInputValue

    company = _company(db)
    _generate(db, company, monkeypatch, [json.dumps(_good_for_tools())])
    row = db.query(DeclaredInputValue).one()
    assert row.method == "manual" and row.segment_key == AGENTS_SEGMENT and row.model_family == "sotp_agents"


def test_llm_failure_leaves_no_proposal_and_says_why(db, monkeypatch):
    company = _company(db)

    async def broken(*a):
        raise RuntimeError("sin LLM")

    from app.services.expert_team import sotp_valuer

    monkeypatch.setattr(sotp_valuer, "sotp_anchors", lambda db, company, today=None: dict(ANCHORS))
    monkeypatch.setattr(sotp_valuer, "build_sotp_tools", lambda db, anchors: _fake_tools(anchors))
    out = generate_sotp_proposal(db, company, reasoner=broken)
    assert out.status == "error" and out.problems == ["llm:RuntimeError"]
    assert UserSotpService().read(db, company, T1)["available"] is False


def test_thesis_run_gets_its_proposal_and_a_failure_never_touches_the_thesis(db, monkeypatch):
    from app.services import sotp_agents_job
    from app.services.expert_team import sotp_valuer
    from app.services.thesis_job_service import WORKFLOW_NAME

    company = _company(db, "ASTS")
    run = WorkflowRun(tenant_id=T1, workflow_name=WORKFLOW_NAME, status="succeeded", idempotency_key="k1",
                      input_payload={"ticker": "ASTS"}, result_payload={"thesis_version_id": 3})
    db.add(run)
    db.commit()
    monkeypatch.setattr(sotp_valuer, "sotp_anchors", lambda db, company, today=None: dict(ANCHORS, ticker="ASTS"))
    monkeypatch.setattr(sotp_valuer, "build_sotp_tools", lambda db, anchors: _fake_tools(anchors))
    monkeypatch.setattr("app.services.expert_team.service.provider_reasoner",
                        lambda *a, **k: _Recorded([json.dumps(_good_for_tools())]))
    out = sotp_agents_job.attach_to_thesis_run(db, run.id, "ASTS", 3)
    assert out["status"] == "stored"
    db.refresh(run)
    assert run.status == "succeeded" and run.result_payload["thesis_version_id"] == 3
    assert run.result_payload["sotp_agents"]["status"] == "stored"
    assert UserSotpService().read(db, company, T1)["agents"]["thesis_version_id"] == 3

    def boom(*a, **k):
        raise RuntimeError("caído")

    monkeypatch.setattr(sotp_valuer, "run_sotp_valuer", boom)
    out = sotp_agents_job.attach_to_thesis_run(db, run.id, "ASTS", 4)
    assert out["status"] == "error"
    db.refresh(run)
    assert run.status == "succeeded" and run.result_payload["sotp_agents"]["status"] == "error"
    status = UserSotpService().read(db, company, T1)["agents_status"]
    assert status["source"] == "thesis" and status["status"] == "error"


def test_button_job_enqueues_once_runs_and_reports_honest_state(db, monkeypatch):
    from app.services import sotp_agents_job
    from app.services.expert_team import sotp_valuer

    company = _company(db)
    sent = []
    run, created = sotp_agents_job.enqueue(db, "SYNTH", dispatch=sent.append)
    again, created_again = sotp_agents_job.enqueue(db, "synth", dispatch=sent.append)
    assert created and not created_again and again.id == run.id and len(sent) == 1
    assert sotp_agents_job.job_payload(run)["status"] == "queued"

    monkeypatch.setattr(sotp_valuer, "sotp_anchors", lambda db, company, today=None: dict(ANCHORS))
    monkeypatch.setattr(sotp_valuer, "build_sotp_tools", lambda db, anchors: _fake_tools(anchors))
    engine = db.get_bind()

    def factory():
        return Session(engine)

    sotp_agents_job.run_job(run.id, reasoner=_Recorded([json.dumps(_good_for_tools())]), session_factory=factory)
    db.expire_all()
    done = sotp_agents_job.latest_run(db, "SYNTH")
    payload = sotp_agents_job.job_payload(done)
    assert payload["status"] == "succeeded" and payload["result"]["status"] == "stored"
    assert UserSotpService().read(db, company, T1)["variant"] == "agents"

    # Una corrida activa vieja (worker reiniciado) no bloquea para siempre.
    stale, _ = sotp_agents_job.enqueue(db, "SYNTH", dispatch=sent.append)
    stale.status, stale.started_at = "running", datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    fresh, created = sotp_agents_job.enqueue(db, "SYNTH", dispatch=sent.append)
    assert created and fresh.id != stale.id
    db.refresh(stale)
    assert stale.status == "failed"


def test_routes_generate_and_variant(db, monkeypatch):
    from app.api.routes.sotp import generate_agents_sotp, get_user_sotp, latest_agents_sotp_job
    from app.services import sotp_agents_job

    _company(db, "ASTS")
    monkeypatch.setattr(sotp_agents_job, "_dispatch", lambda run: None)
    out = generate_agents_sotp("ASTS", db=db)
    assert out["created"] and out["job"]["status"] == "queued"
    assert latest_agents_sotp_job("ASTS", db=db)["job"]["id"] == out["job"]["id"]
    shown = get_user_sotp("ASTS", db=db, variant="example")
    assert shown["variant"] == "example" and shown["agents_status"]["source"] == "button"


def test_two_agent_runs_that_differ_over_30pct_are_flagged_as_sensitive(db, monkeypatch):
    company = _company(db)
    _generate(db, company, monkeypatch, [json.dumps(_good_for_tools())])
    first = UserSotpService().read(db, company, T1)
    assert first["agents_stability"] is None
    other = _good_for_tools()  # otra lectura: además valora Operadora B con su cifra citada
    other["segments"].append({"name": "Operadora B", "status": "beta", "business_type": "telecom_mayorista",
                              "anchor": {"type": "guia", "amount_millions": 600, "year": 2028, "citation": "ev-6"}})
    _generate(db, company, monkeypatch, [json.dumps(other)], use_cache=False)
    stability = UserSotpService().read(db, company, T1)["agents_stability"]
    assert stability["unstable"] is True and stability["change"] > 0.3
    assert stability["previous_value_per_share"] == pytest.approx(first["result"]["value_per_share"], rel=1e-5)


def test_same_fingerprint_is_served_from_cache_without_calling_the_model(db, monkeypatch):
    company = _company(db)
    first = _generate(db, company, monkeypatch, [json.dumps(_good_for_tools())])
    assert first.status == "stored" and first.calls == 1 and not first.cache_hit
    for _ in range(2):  # 2.ª y 3.ª vez: misma huella → caché, 0 llamadas, mismo número, sin versión nueva
        again = _generate(db, company, monkeypatch, [])
        assert again.status == "cached" and again.cache_hit and again.calls == 0
        assert again.value_per_share == pytest.approx(first.value_per_share)
    rows = UserSotpService().inputs.history(db, company_id=company.id, tenant_id=T1, input_key="sotp_user_model",
                                            segment_key=AGENTS_SEGMENT)
    assert len(rows) == 1 and rows[0].metadata_["fingerprint"]["hash"] == first.fingerprint["hash"]
    # Entra un dato nuevo: huella nueva, una llamada, y la ficha dice qué lo cambió.
    newer = _generate(db, company, monkeypatch, [json.dumps(_good_for_tools())], extra_drivers=["Nuevo 8-K de noviembre"])
    assert newer.status == "stored" and newer.calls == 1 and newer.fingerprint["hash"] != first.fingerprint["hash"]
    shown = UserSotpService().read(db, company, T1)
    assert any("Nuevo 8-K de noviembre" in c for c in shown["agents"]["changed_by"])


def test_two_readings_keep_the_most_conservative_and_say_they_differ(db, monkeypatch):
    company = _company(db)
    rich = _good_for_tools()
    rich["segments"][0]["status"] = "comercial"
    out = _generate(db, company, monkeypatch, [json.dumps(rich), json.dumps(_good_for_tools())], readings=2)
    assert out.status == "stored" and out.calls == 2 and out.readings_differ is True
    values = sorted(r["value_per_share"] for r in out.readings)
    assert out.value_per_share == pytest.approx(values[0]) and values[0] < values[1]
    assert out.model["parts"][0]["probability"] == 0.6  # «contratado», el estado más bajo de las dos lecturas
    meta = UserSotpService().read(db, company, T1)["agents"]
    assert meta["readings_differ"] is True and len(meta["readings"]) == 2


def test_valuer_runs_at_temperature_zero_and_reads_balance_and_analyst_tools(db, monkeypatch):
    from app.services.expert_team import service as team_service
    from app.services.expert_team import sotp_valuer

    seen = {}

    def fake_provider_reasoner(*a, **k):
        seen.update(k)
        return _Recorded([json.dumps(_good_for_tools())])

    monkeypatch.setattr(team_service, "provider_reasoner", fake_provider_reasoner)
    monkeypatch.setattr(sotp_valuer, "sotp_anchors", lambda db, company, today=None: dict(ANCHORS))
    monkeypatch.setattr(sotp_valuer, "build_sotp_tools", lambda db, anchors: _fake_tools(anchors))
    company = _company(db)
    assert generate_sotp_proposal(db, company).status == "stored"
    assert seen["temperature"] == 0.0
    spec = sotp_valuer_expert()
    assert {"balance_asset_documents", "analyst_estimates", "share_count_documents"} <= set(spec.tools)


def test_cash_line_adds_short_term_investments_of_the_same_close(db):
    from app.services.expert_team.sotp_valuer import sotp_anchors

    company = _company(db)
    _seed_market(db, company)
    for period, value in (("2026-06-30:Q2", "250000000"), ("2026-03-31:Q1", "999000000")):
        db.add(FinancialFact(company_id=company.id, metric="short_term_investments", value=Decimal(value), unit="USD",
                             period=period, fiscal_quarter=period[-2:], source_type="SEC", is_reported=True))
    db.flush()
    anchors = sotp_anchors(db, company, today=TODAY)
    assert anchors["short_term_investments_millions"] == pytest.approx(250.0)
    model, problems = parse_proposal(_good(), _ledger(), {**ANCHORS, "short_term_investments_millions": 250.0})
    assert problems == []
    assert model["parts"][-1]["value"] == pytest.approx(1000 + 250 - 400)
    assert "inversiones a corto 250 M" in model["parts"][-1]["why"]["value"]


def test_shares_use_the_sum_of_all_classes_from_the_sec_cover_when_it_exists(db):
    from app.services.expert_team.sotp_valuer import sotp_anchors

    company = _company(db)
    _seed_market(db, company)
    db.query(FinancialFact).filter(FinancialFact.metric == "shares_outstanding").delete()
    db.add(FinancialFact(company_id=company.id, metric="shares_diluted", value=Decimal("300000000"), unit="shares",
                         period="2026-06-30:Q2", fiscal_quarter="Q2", source_type="SEC", is_reported=True))
    db.flush()
    assert sotp_anchors(db, company, today=TODAY)["shares_basis"] == "shares_diluted"
    db.add(FinancialFact(company_id=company.id, metric="shares_outstanding", value=Decimal("389000000"), unit="shares",
                         period="2026-08-06:DEI", source_type="derived", is_reported=False))
    db.flush()
    anchors = sotp_anchors(db, company, today=TODAY)
    assert anchors["shares_basis"] == "shares_outstanding" and anchors["shares_current_millions"] == pytest.approx(389.0)
    assert anchors["shares_period_end"] == "2026-08-06"


def test_analyst_tool_reads_notes_and_analyst_inputs_of_the_tenant(db):
    from app.models.analyst_note import AnalystNote
    from app.services.expert_team.sotp_valuer import analyst_estimates_tool

    company = _company(db)
    db.add(AnalystNote(tenant_id=T1, company_id=company.id, ticker="SYNTH", firm="Firma A", firm_key="firma_a",
                       note_date=date(2026, 10, 1), action="maintain", pt_new=Decimal("55"), currency="USD",
                       key_arguments=["contrato"], source_url="https://example.com/a", source_type="press",
                       verification="fragmento", dedupe_key="a", estimates={"revenue_2030": 3000}))
    db.flush()
    db.add(Tenant(id=2, external_id="t2"))
    db.flush()
    db.info["tenant_id"] = 2
    db.add(AnalystNote(tenant_id=2, company_id=company.id, ticker="SYNTH", firm="Otro tenant", firm_key="otro",
                       note_date=date(2026, 10, 2), action="maintain", pt_new=Decimal("1"), currency="USD",
                       source_type="press", verification="fragmento", dedupe_key="b"))
    db.flush()
    db.info["tenant_id"] = T1
    out = analyst_estimates_tool(db).fn(RunContext(tenant_id=T1, ticker="SYNTH", mode="thesis", lang="es"))
    assert [o.data["firm"] for o in out] == ["Firma A"] and out[0].data["price_target"] == 55.0
    assert out[0].data["estimates"] == {"revenue_2030": 3000}


def _narrative_answer(text_partes="La parte de Operadora A vale {{part.1.value_per_share}} por acción."):
    from app.services.expert_team.sotp_narrative import SECTIONS

    sections = {key: f"Sección {title} sin cifras propias." for key, title in SECTIONS}
    sections["resumen"] = "El desglose da {{sotp.base_per_share}} por acción frente a {{sotp.price}} ({{sotp.vs_price}}) en 2030."
    sections["partes"] = text_partes
    return json.dumps({"sections": sections})


def test_long_thesis_uses_markers_rendered_from_the_calculation_and_is_cached(db, monkeypatch):
    company = _company(db)
    out = _generate(db, company, monkeypatch, [json.dumps(_good_for_tools()), _narrative_answer()], narrative=True)
    assert out.status == "stored" and out.calls == 2 and out.narrative["status"] == "ok"
    shown = UserSotpService().read(db, company, T1)
    narrative = shown["agents"]["narrative"]
    resumen = next(s["text"] for s in narrative["sections"] if s["key"] == "resumen")
    base = shown["result"]["value_per_share"]
    assert f"{base:,.2f}".replace(".", ",") in resumen and "{{" not in resumen and "2030" in resumen
    assert [s["key"] for s in narrative["sections"]][0] == "resumen"
    again = _generate(db, company, monkeypatch, [], narrative=True)  # misma huella: SOTP y tesis de la caché
    assert again.status == "cached" and again.calls == 0 and again.narrative["status"] == "cached"


def test_a_number_written_by_the_model_is_rejected_then_stripped(db, monkeypatch):
    company = _company(db)
    bad = _narrative_answer("Operadora A vale 45 $ por acción y crecerá un 30 %.")
    out = _generate(db, company, monkeypatch, [json.dumps(_good_for_tools()), bad, bad], narrative=True)
    assert out.narrative["status"] == "stripped" and out.calls == 3
    partes = next(s["text"] for s in UserSotpService().read(db, company, T1)["agents"]["narrative"]["sections"]
                  if s["key"] == "partes")
    assert "45" not in partes and "30" not in partes and partes.startswith("Operadora A vale")


def test_free_numbers_validator_allows_years_dates_and_markers_only():
    from app.services.expert_team.sotp_narrative import free_numbers, strip_free_numbers, unknown_markers

    assert free_numbers("En 2030 vale {{sotp.base_per_share}}; el 8-K del 2026-11-06 lo confirma.") == []
    assert free_numbers("Vale 4,80 $ y el 15 % de tasa") == ["4,80 $", "15 %"]
    assert unknown_markers("{{sotp.inventado}} y {{sotp.price}}", {"sotp.price": "1"}) == ["sotp.inventado"]
    assert strip_free_numbers("Vale 4,80 $ en 2030 ({{sotp.price}}).") == "Vale en 2030 ({{sotp.price}})."


def test_when_the_total_is_mostly_cash_the_reader_is_told():
    from app.services.user_sotp_service import _mostly_cash

    rows = [{"name": "Caja menos deuda (último balance SEC)", "value_per_share": 3.95}, {"name": "D2D", "value_per_share": 0.85}]
    flag = _mostly_cash({"value_per_share": 4.80, "rows": rows})
    assert flag["share"] == pytest.approx(3.95 / 4.80)
    assert _mostly_cash({"value_per_share": 10.0, "rows": rows}) is None
