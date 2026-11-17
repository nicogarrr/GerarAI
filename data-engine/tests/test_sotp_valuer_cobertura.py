"""Suite dedicada de cobertura para ``sotp_valuer`` (gate >=85% por fichero).

Hermetica: sqlite en memoria, razonador grabado, servicios de apoyo
monkeypatcheados. Cubre lo que la suite combinada no alcanza de forma
estable: anclas SEC (divisa, flujos viejos, CAPM), corrida completa con
cache, propuesta guardada/rechazada, recompute y salidas de herramientas.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact, Tenant
from app.services.expert_team import sotp_valuer as svc
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import RunContext, ToolOutput, ToolSpec
from app.services.expert_team.sotp_valuer import SOTP_VALUER_NAME

T1 = 1
TODAY = date(2026, 11, 8)

ANCHORS = {
    "ticker": "SYNTH",
    "company": "Synth Inc",
    "today": "2026-11-08",
    "base_year": 2026,
    "currency": "USD",
    "price": 32.0,
    "price_as_of": "2026-11-06",
    "shares_current_millions": 300.0,
    "shares_basis": "shares_outstanding",
    "shares_period_end": "2026-06-30",
    "cash_millions": 1000.0,
    "debt_millions": 400.0,
    "balance_period_end": "2026-06-30",
    "discount_rate": 0.11,
    "discount_rate_source": "calculated_metric",
    "revenue_actuals": [{"period_end": "2025-12-31", "revenue_millions": 5.0}],
    "burns_cash": True,
    "base_rate_message": "…",
}

EV_TEXT = (
    "Definitive agreement with Operator A: contracted backlog of $1.2 billion over 6 years. "
    "We acquired spectrum rights for $500 million. 12,000,000 Class B shares are exchangeable."
)


def _ledger() -> EvidenceLedger:
    ledger = EvidenceLedger()
    ledger.add(
        expert=SOTP_VALUER_NAME,
        tool="value_drivers",
        source={
            "table": "value_drivers",
            "title": "Acuerdo",
            "url": "https://example.com/8k",
            "date": "2026-05-01",
        },
        data={"text": EV_TEXT},
    )
    return ledger


def _good(cite: str = "ev-1") -> dict:
    return {
        "summary": "Pesa el contrato con Operadora A.",
        "segments": [
            {
                "group": "Mayorista",
                "name": "Operadora A",
                "status": "contratado",
                "business_type": "telecom_mayorista",
                "why_status": "acuerdo firmado",
                "anchor": {
                    "type": "backlog",
                    "amount_millions": 1200,
                    "period": "total",
                    "year": None,
                    "years": 6,
                    "quote": "contracted backlog of $1.2 billion over 6 years",
                    "citation": cite,
                },
            },
        ],
        "assets": [
            {
                "name": "Espectro",
                "status": "beta",
                "value_millions": 500,
                "quote": "spectrum rights for $500 million",
                "citation": cite,
                "why": "precio pagado",
            }
        ],
        "dilution": [
            {
                "label": "Clase B canjeable",
                "shares_millions": 12,
                "quote": "12,000,000 Class B shares",
                "citation": cite,
                "why": "canjeable",
            }
        ],
    }


def _classification() -> dict:
    out, problems = svc.parse_classification(json.loads(json.dumps(_good())), _ledger())
    assert problems == []
    return json.loads(json.dumps(out))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=T1, external_id="tcov"))
        session.flush()
        session.info["tenant_id"] = T1
        yield session


def _company(db, ticker="SYNTH", currency="USD"):
    company = Company(
        ticker=ticker,
        name=f"{ticker} Inc",
        exchange="NASDAQ",
        currency=currency,
        company_type="operating",
        valuation_model="pre_revenue",
    )
    db.add(company)
    db.flush()
    return company


def _fact(db, company, metric, value, period, unit="USD", fy=None, fq=None):
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit=unit,
            period=period,
            fiscal_year=fy,
            fiscal_quarter=fq,
            source_type="SEC",
            is_reported=True,
        )
    )
    db.flush()


# ---------------------------------------------------------------- helpers puros


def test_helpers_numericos_y_de_texto():
    assert svc._num(True) is None and svc._num(None) is None and svc._num("x") is None
    assert svc._num(float("inf")) is None and svc._num("3.5") == 3.5
    assert svc._millions(None) is None and svc._millions({"value": "x"}) is None
    assert svc._millions({"value": 2_500_000}) == 2.5
    assert (
        svc._iso("usd") == "USD"
        and svc._iso("US") is None
        and svc._iso("US1") is None
        and svc._iso(None) is None
    )
    assert svc._text("  a   b ") == "a b" and svc._text(None) == ""
    assert svc._cut("x" * 400) == "x" * 299 + "…" and svc._cut("corta") == "corta"
    assert svc._summary_without_numbers("Vale 45 dólares. Pesa el contrato. Llega en 2027.") == (
        "Pesa el contrato. Llega en 2027."
    )
    assert svc._older_than("2020-12-31", "2025-12-31") is True
    assert svc._older_than("2025-12-31", "2025-12-31") is False
    assert svc._older_than(None, "2025-12-31") is False
    assert svc._model_without_date(None) == {}
    assert svc._model_without_date({"source": "s", "x": 1}) == {"x": 1}


def test_sources_y_citas(db):
    ledger = _ledger()
    sources = svc._sources_for(["ev-1", "ev-1", "ev-99"], ledger)
    assert sources == [
        {"label": "Acuerdo (value_drivers)", "url": "https://example.com/8k", "date": "2026-05-01"}
    ]
    cites, valid = svc._citations({"citations": ["ev-1", "ev-99"]}, ledger, SOTP_VALUER_NAME)
    assert cites == ["ev-1", "ev-99"] and valid is False
    cites, valid = svc._citations({"citations": ["ev-1"]}, ledger, "otro-experto")
    assert valid is False
    result = svc.SotpProposalResult(status="ok", fingerprint={"hash": "abc"}, narrative={"status": "cached"})
    assert result.as_dict()["fingerprint"] == "abc" and result.as_dict()["narrative"] == "cached"


def test_anchor_currency_problem_y_note():
    anchor = {"currency": "CAD"}
    assert "CAD" in svc._anchor_currency_problem(anchor, "USD")
    assert svc._anchor_currency_problem(anchor, "CAD") is None
    assert svc._anchor_currency_problem(anchor, None) is None
    assert svc._anchor_currency_problem({"currency": None}, "USD") is None
    assert "CAD (la de la cita)" in svc._anchor_currency_note(anchor, "USD")
    assert "USD" in svc._anchor_currency_note({"currency": None}, "USD")
    assert "N/D" in svc._anchor_currency_note({"currency": None}, None)


# ---------------------------------------------------------------- hechos SEC


def test_fact_millions_filtra_unidad_y_cierre(db):
    company = _company(db)
    _fact(db, company, "revenue", 100e6, "2025-12-31:FY", unit="CAD", fy=2025, fq="FY")
    _fact(db, company, "revenue", 50e6, "2024-12-31:FY", unit="USD", fy=2024, fq="FY")
    _fact(db, company, "revenue", 10e6, "2026-06-30:Q2", unit="USD", fq="Q2")
    value, end = svc._fact_millions(db, company, "revenue", annual=True)
    assert value == 50.0 and end == "2024-12-31"  # la CAD no cuenta en USD
    value, end = svc._fact_millions(db, company, "revenue", period_prefix="2026-06-30")
    assert value == 10.0 and end == "2026-06-30"
    assert svc._fact_millions(db, company, "no_existe") == (None, None)
    assert svc._latest_annual_end(db, company) == "2025-12-31"


def test_capm_cost_of_equity(db):
    company = _company(db)
    assert svc._capm_cost_of_equity(db, company) is None  # faltan insumos
    _fact(db, company, "risk_free_rate", 0.04, "2026-11-01:Q4")
    _fact(db, company, "beta", 1.5, "2026-11-01:Q4")
    _fact(db, company, "equity_risk_premium", 0.05, "2026-11-01:Q4")
    _fact(db, company, "country_risk_premium", 0.01, "2026-11-01:Q4")
    out = svc._capm_cost_of_equity(db, company)
    assert out is not None
    rate, formula = out
    assert rate == pytest.approx(0.125) and "4.00%" in formula and "1.50" in formula and "1.00%" in formula
    # Fuera de la banda de cordura (3%-40%): no sirve.
    company2 = _company(db, "SYNTH2")
    _fact(db, company2, "risk_free_rate", 0.04, "2026-11-01:Q4")
    _fact(db, company2, "beta", 20.0, "2026-11-01:Q4")
    _fact(db, company2, "equity_risk_premium", 0.05, "2026-11-01:Q4")
    assert svc._capm_cost_of_equity(db, company2) is None


def test_reporting_currency(db):
    company = _company(db)
    assert svc._reporting_currency(db, company) is None
    _fact(db, company, "cash_and_equivalents", 5e6, "2026-06-30:Q2", unit="cad")
    assert svc._reporting_currency(db, company) == "CAD"


# ---------------------------------------------------------------- sotp_anchors


def _patch_report(monkeypatch, report, price=(32.0, "USD", "2026-11-06"), rate=(None, None), base_rate=None):
    import app.services.analyst_report as analyst_report
    import app.services.user_sotp_service as user_sotp_service
    import app.valuation.engines.base as engines_base

    monkeypatch.setattr(analyst_report, "build_company_report", lambda db, company, today=None: report)
    monkeypatch.setattr(user_sotp_service, "_price", lambda db, company: price)
    monkeypatch.setattr(
        user_sotp_service,
        "_base_rate",
        lambda db, company: base_rate or {"applies": False, "message_es": "m"},
    )
    monkeypatch.setattr(engines_base, "resolve_rates", lambda db, company, as_of=None: rate)


def test_sotp_anchors_base_y_capm_de_rescate(db, monkeypatch):
    company = _company(db)
    _fact(db, company, "shares_outstanding", 300e6, "2026-09-25:Q3", unit="SHARES")
    _fact(db, company, "stock_based_compensation", 40e6, "2025-12-31:FY", fy=2025, fq="FY")
    _fact(db, company, "free_cash_flow", -900e6, "2025-12-31:FY", fy=2025, fq="FY")
    _fact(db, company, "risk_free_rate", 0.04, "2026-11-01:Q4")
    _fact(db, company, "beta", 2.0, "2026-11-01:Q4")
    _fact(db, company, "equity_risk_premium", 0.035, "2026-11-01:Q4")
    report = {
        "market": {
            "cash": {"value": 1000e6, "period_end": "2026-06-30"},
            "total_debt": {"value": 400e6, "period_end": "2026-06-30"},
        },
        "estimates": {
            "annual": [
                {"period_end": "2025-12-31", "revenue": {"value": 5e6}},
                {"period_end": "2024-12-31", "revenue": None},
            ]
        },
    }
    _patch_report(monkeypatch, report)  # resolve_rates sin tasa → rescate CAPM
    anchors = svc.sotp_anchors(db, company, today=TODAY)
    assert anchors["shares_current_millions"] == 300.0 and anchors["shares_basis"] == "shares_outstanding"
    assert anchors["cash_millions"] == 1000.0 and anchors["debt_millions"] == 400.0
    assert anchors["sbc_annual_millions"] == 40.0 and anchors["annual_burn_millions"] == 900.0
    assert anchors["discount_rate"] == pytest.approx(0.11)
    assert "capm_cost_of_equity" in anchors["discount_rate_source"]
    assert anchors["revenue_actuals"] == [{"period_end": "2025-12-31", "revenue_millions": 5.0}]
    assert anchors["stale_annual_notes"] == []


def test_sotp_anchors_flujos_viejos_quedan_nd_con_motivo(db, monkeypatch):
    company = _company(db)
    # SBC y FCF del 2020 con un ejercicio 2025 ya presentado: N/D, nunca la cifra vieja.
    _fact(db, company, "stock_based_compensation", 40e6, "2020-12-31:FY", fy=2020, fq="FY")
    _fact(db, company, "free_cash_flow", -900e6, "2020-12-31:FY", fy=2020, fq="FY")
    _fact(db, company, "net_income", 1e6, "2025-12-31:FY", fy=2025, fq="FY")
    _patch_report(monkeypatch, {"market": {}, "estimates": {}})
    anchors = svc.sotp_anchors(db, company, today=TODAY)
    assert anchors["sbc_annual_millions"] is None and anchors["annual_burn_millions"] is None
    notes = " ".join(anchors["stale_annual_notes"])
    assert "SBC anual N/D" in notes and "2020-12-31" in notes and "Consumo de caja anual N/D" in notes


def test_sotp_anchors_convierte_precio_a_la_divisa_de_los_informes(db, monkeypatch):
    import app.services.user_sotp_service as user_sotp_service

    company = _company(db, currency="CAD")
    _fact(db, company, "revenue", 50e6, "2025-12-31:FY", unit="CAD", fy=2025, fq="FY")
    _patch_report(monkeypatch, {"market": {}, "estimates": {}}, price=(10.0, "USD", "2026-11-06"))
    monkeypatch.setattr(
        user_sotp_service,
        "convert_amount",
        lambda db, amount, frm, to, as_of: (amount * 1.4, f"{frm}→{to} ×1.40"),
    )
    anchors = svc.sotp_anchors(db, company, today=TODAY)
    assert anchors["currency"] == "CAD" and anchors["price"] == pytest.approx(14.0)
    assert "USD→CAD" in anchors["price_fx_note"] and anchors["fx_missing"] is None
    # Sin tipo de cambio guardado: fx_missing con el par, precio intacto.
    monkeypatch.setattr(user_sotp_service, "convert_amount", lambda db, amount, frm, to, as_of: None)
    anchors = svc.sotp_anchors(db, company, today=TODAY)
    assert anchors["fx_missing"] == "tipo de cambio USD→CAD" and anchors["price"] == 10.0


def test_sotp_anchors_resolve_rates_roto_no_tumba(db, monkeypatch):
    import app.valuation.engines.base as engines_base

    company = _company(db)
    _patch_report(monkeypatch, {"market": {}, "estimates": {}})
    monkeypatch.setattr(engines_base, "resolve_rates", lambda db, company, as_of=None: 1 / 0)
    anchors = svc.sotp_anchors(db, company, today=TODAY)
    assert anchors["discount_rate"] is None and anchors["discount_rate_source"] is None


def test_anchor_outputs_cinco_bloques():
    out = svc._anchor_outputs(ANCHORS)
    assert len(out) == 5
    assert out[0].data == {"price": 32.0, "currency": "USD"}
    assert out[1].data["shares_current_millions"] == 300.0
    assert out[3].data["source"] == "calculated_metric"
    assert all(item.source["url"] == "/research/SYNTH?view=valuation" for item in out)


# ---------------------------------------------------------------- herramientas


def test_build_sotp_tools_reune_las_piezas(db, monkeypatch):
    import app.services.expert_team.recopilador as recopilador
    import app.services.expert_team.tools as team_tools

    spec = ToolSpec(name="news_events", fn=lambda ctx: [], description="")
    base = dict.fromkeys(("financial_facts", "valuation_engine", "news_events", "risk_events"), spec)
    monkeypatch.setattr(team_tools, "build_tools", lambda db: {**base, "fuera": spec})
    monkeypatch.setattr(recopilador, "company_documents_tool", lambda db: spec)
    tools = svc.build_sotp_tools(db, ANCHORS)
    assert "fuera" not in tools
    for name in svc.SOTP_VALUER_TOOLS:
        assert name in tools, name
    assert tools["sotp_anchors"].fn(RunContext(tenant_id=T1, ticker="SYNTH"))[0].data["price"] == 32.0


def test_companies_house_outputs_todas_las_rutas():
    result = {
        "members": [
            {
                "company_name": "Filial UK",
                "company_number": "123",
                "parent": "Madre",
                "via": "psc",
                "accounts_type": "full",
                "made_up_to": "2025-12-31",
                "filed_on": "2026-06-01",
                "formats": ["ixbrl"],
                "pages": 10,
                "ixbrl_url": "https://ch.test/ixbrl",
                "figures": [
                    {
                        "metric": "revenue",
                        "value_millions": 12.5,
                        "currency": "GBP",
                        "period_end": "2025-12-31",
                        "concept": "Revenue",
                        "label": "Ingresos",
                        "value": 12_500_000,
                        "source": "ixbrl",
                    }
                ],
            },
            {
                "company_name": "Scan OK",
                "company_number": "124",
                "accounts_type": None,
                "made_up_to": "",
                "document_url": "https://ch.test/pdf",
                "figures": [
                    {
                        "metric": "assets",
                        "value_millions": 3.0,
                        "currency": "GBP",
                        "period_end": "2025-12-31",
                        "concept": "Assets",
                        "label": "Activos",
                        "value": 3_000_000,
                        "source": "ocr",
                        "page": 7,
                        "line": "Total assets 3.0m",
                        "unit": "GBPm",
                        "page_url": "https://ch.test/p7",
                        "basis": "balance",
                        "check": "cuadra",
                    }
                ],
            },
            {
                "company_name": "Scan Cola",
                "company_number": "125",
                "company_url": "https://ch.test/c125",
                "figures": [],
                "scanned": {"status": "pending"},
            },
            {
                "company_name": "Scan Rota",
                "company_number": "126",
                "company_url": "https://ch.test/c126",
                "figures": [],
                "scanned": {"status": "failed", "reason": "ilegible"},
            },
            {
                "company_name": "Solo PDF",
                "company_number": "127",
                "company_url": "https://ch.test/c127",
                "figures": [],
            },
        ]
    }
    out = svc.companies_house_outputs(result)
    assert len(out) == 5
    tagged, ocr, queued, broken, plain = out
    assert (
        tagged.source["url"] == "https://ch.test/ixbrl"
        and tagged.data["cifras"]["revenue"]["millones"] == 12.5
    )
    assert tagged.data["nota"] is None and "Ingresos 12,500,000 GBP" in (tagged.data["quote"] or "")
    assert ocr.data["cifras"]["assets"]["pagina"] == 7 and "OCR" in ocr.data["nota"]
    assert "pág. 7" in (ocr.data["quote"] or "") and ocr.source["url"] == "https://ch.test/pdf"
    assert "lectura OCR en cola" in queued.data["nota"]
    assert "ilegible" in broken.data["nota"]
    assert "sin cifras extraidas" in plain.data["nota"] and plain.data["cifras"] is None
    assert svc.companies_house_outputs(None) == []


def test_companies_house_tool_guardas(db, monkeypatch):
    import app.services.companies_house_evidence as ch

    tool = svc.companies_house_tool(db)
    assert tool.fn(RunContext(tenant_id=T1, ticker=None)) == []
    assert tool.fn(RunContext(tenant_id=T1, ticker="ABSENT")) == []
    con_cik = _company(db, "CONCIK")
    con_cik.cik = "0001"
    db.flush()
    assert tool.fn(RunContext(tenant_id=T1, ticker="CONCIK")) == []
    _company(db, "UKHOLD")
    calls = {}

    def fake_collect(name, hints, people=None):
        calls["collect"] = (name, list(hints), people)
        return {"members": []}

    monkeypatch.setattr(ch, "collect_group_accounts", fake_collect)
    monkeypatch.setattr(ch, "subsidiary_hints", lambda db, company, tenant: iter(["pista"]))
    monkeypatch.setattr(ch, "holding_people", lambda db, company: ["persona"])
    monkeypatch.setattr(ch, "queue_scanned_reads", lambda result, ticker: calls.setdefault("queued", ticker))
    out = tool.fn(RunContext(tenant_id=T1, ticker="UKHOLD"))
    assert out == [] and calls["collect"][0] == "UKHOLD Inc" and calls["queued"] == "UKHOLD"


# ---------------------------------------------------------------- corrida del valorador


class _Recorded:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, system, user, max_tokens, task):
        self.calls.append(json.loads(user))
        return self.answers.pop(0)


def _fake_tools():
    def drivers(ctx):
        return [
            ToolOutput(
                source={
                    "table": "value_drivers",
                    "title": "Acuerdo",
                    "url": "https://example.com/8k",
                    "date": "2026-05-01",
                },
                data={"text": EV_TEXT},
            )
        ]

    tools = {name: ToolSpec(name=name, fn=lambda ctx: [], description="") for name in svc.SOTP_VALUER_TOOLS}
    tools["value_drivers"] = ToolSpec(name="value_drivers", fn=drivers, description="")
    return tools


def _ctx(ticker="SYNTH"):
    return RunContext(tenant_id=T1, ticker=ticker, mode="thesis", lang="es")


def test_run_guardas_sin_tenant_sin_empresa_sin_precio(db):
    result = asyncio.run(
        svc.run_sotp_valuer(
            db, ctx=RunContext(tenant_id="x", ticker="SYNTH"), reasoner=_Recorded([]), tools=_fake_tools()
        )
    )
    assert result.status == "no_company" and result.problems
    result = asyncio.run(
        svc.run_sotp_valuer(db, ctx=_ctx("ABSENT"), reasoner=_Recorded([]), tools=_fake_tools())
    )
    assert result.status == "no_company"
    _company(db)
    result = asyncio.run(
        svc.run_sotp_valuer(
            db, ctx=_ctx(), reasoner=_Recorded([]), tools=_fake_tools(), anchors={**ANCHORS, "price": None}
        )
    )
    assert result.status == "no_price" and result.problems == ["sin precio de la empresa"]
    # Sin acciones ni tasa no se gasta llamada al modelo.
    reasoner = _Recorded([])
    result = asyncio.run(
        svc.run_sotp_valuer(
            db,
            ctx=_ctx(),
            reasoner=reasoner,
            tools=_fake_tools(),
            anchors={
                **ANCHORS,
                "shares_current_millions": None,
                "discount_rate": None,
                "fx_missing": "tipo de cambio USD→CAD",
            },
        )
    )
    assert result.status == "no_data" and reasoner.calls == []
    assert "acciones (SEC)" in result.problems[0] and "USD→CAD" in result.problems[0]


def test_run_sin_evidencia_y_error_llm(db):
    _company(db)
    vacias = {name: ToolSpec(name=name, fn=lambda ctx: [], description="") for name in svc.SOTP_VALUER_TOOLS}
    result = asyncio.run(
        svc.run_sotp_valuer(db, ctx=_ctx(), reasoner=_Recorded([]), tools=vacias, anchors=ANCHORS)
    )
    assert result.status == "no_data" and result.fingerprint is None

    class Roto:
        async def __call__(self, *args):
            raise RuntimeError("sin presupuesto")

    result = asyncio.run(
        svc.run_sotp_valuer(db, ctx=_ctx(), reasoner=Roto(), tools=_fake_tools(), anchors=ANCHORS)
    )
    assert result.status == "error" and result.problems == ["llm:RuntimeError"]


def test_run_cache_hit_ok_y_rechazo_cacheado(db):
    _company(db)
    hit = _classification()
    result = asyncio.run(
        svc.run_sotp_valuer(
            db, ctx=_ctx(), reasoner=_Recorded([]), tools=_fake_tools(), anchors=ANCHORS, cached=lambda h: hit
        )
    )
    assert result.cache_hit is True and result.status == "ok" and result.value_per_share is not None
    # Misma huella con una clasificación sin segmentos válidos: el mismo rechazo, sin llamar.
    reasoner = _Recorded([])
    result = asyncio.run(
        svc.run_sotp_valuer(
            db,
            ctx=_ctx(),
            reasoner=reasoner,
            tools=_fake_tools(),
            anchors=ANCHORS,
            cached=lambda h: {"segments": []},
        )
    )
    assert result.status == "rejected" and result.cache_hit is True and reasoner.calls == []
    assert result.problems == [svc.NO_SEGMENTS]


def test_run_lecturas_multiples_gana_la_conservadora(db):
    _company(db)
    buena = json.dumps(_good())
    cara_raw = json.loads(json.dumps(_good()))
    cara_raw["segments"][0]["anchor"]["amount_millions"] = 1200
    cara = json.dumps(cara_raw)
    reasoner = _Recorded([cara, buena])
    result = asyncio.run(
        svc.run_sotp_valuer(
            db, ctx=_ctx(), reasoner=reasoner, tools=_fake_tools(), anchors=ANCHORS, readings=2
        )
    )
    assert result.status == "ok" and len(result.readings) == 2
    assert result.readings_differ is False  # misma clasificación, mismo valor
    otra = json.loads(json.dumps(_good()))
    otra["segments"][0]["status"] = "beta"  # misma cita, otro estado: la clave cambia
    reasoner = _Recorded([json.dumps(otra), buena])
    result = asyncio.run(
        svc.run_sotp_valuer(
            db, ctx=_ctx(), reasoner=reasoner, tools=_fake_tools(), anchors=ANCHORS, readings=2
        )
    )
    assert result.readings_differ is True


def test_run_rechazo_sin_segmentos_y_tope_de_llamadas(db):
    _company(db)
    sin_cifra = json.dumps(
        {"segments": [{"name": "X", "status": "idea", "business_type": "contratos_gobierno", "anchor": None}]}
    )
    reasoner = _Recorded([sin_cifra, sin_cifra])
    result = asyncio.run(
        svc.run_sotp_valuer(db, ctx=_ctx(), reasoner=reasoner, tools=_fake_tools(), anchors=ANCHORS)
    )
    assert result.status == "rejected" and result.classification is not None
    assert result.problems == [svc.NO_SEGMENTS]
    # max_calls=1: un solo intento aunque la forma sea mala.
    mala = json.dumps({"segments": []})
    reasoner = _Recorded([mala, mala])
    result = asyncio.run(
        svc.run_sotp_valuer(
            db, ctx=_ctx(), reasoner=reasoner, tools=_fake_tools(), anchors=ANCHORS, max_calls=1
        )
    )
    assert result.status == "rejected" and result.llm_calls == 1 and result.classification is None
    # JSON roto: cuenta como intento y reintenta.
    reasoner = _Recorded(["no es json", json.dumps(_good())])
    result = asyncio.run(
        svc.run_sotp_valuer(db, ctx=_ctx(), reasoner=reasoner, tools=_fake_tools(), anchors=ANCHORS)
    )
    assert result.status == "ok" and result.llm_calls == 2


# ---------------------------------------------------------------- propuesta guardada


def _patch_propuesta(monkeypatch, *, stale=False):
    import app.services.analyst_press_estimates as analyst_press
    import app.services.company_guidance as company_guidance
    import app.workers.dramatiq_app as dramatiq_app

    monkeypatch.setattr(
        company_guidance, "refresh_company_guidance", lambda db, company, tenant_id, today=None: None
    )
    # El stub CAPTURA el today que recibe: si el cableado dejara de pasar
    # today=today, el test tiene que caer (mutante del Auditor 2).
    captured: list = []

    def fake_stale(db, company, tenant_id, today=None):
        captured.append(today)
        return stale

    monkeypatch.setattr(analyst_press, "press_estimates_stale", fake_stale)
    sent = []
    monkeypatch.setattr(dramatiq_app.collect_analyst_estimates, "send", lambda *args: sent.append(args))
    return sent, captured


def test_generate_sin_tenant_no_toca_nada(db):
    db.info.pop("tenant_id", None)
    company = _company(db)
    out = svc.generate_sotp_proposal(db, company, reasoner=_Recorded([]))
    assert out.status == "no_company"


def test_generate_encola_prensa_solo_si_esta_vieja(db, monkeypatch):
    """El cableado today= de fix3b: press_estimates_stale decide con el today de la corrida."""
    company = _company(db)
    monkeypatch.setattr(svc, "sotp_anchors", lambda db, company, today=None: dict(ANCHORS))
    monkeypatch.setattr(svc, "build_sotp_tools", lambda db, anchors: _fake_tools())
    reasoner = _Recorded([json.dumps(_good())])
    sent, captured = _patch_propuesta(monkeypatch, stale=True)
    out = svc.generate_sotp_proposal(db, company, reasoner=reasoner, today=TODAY)
    assert out.status == "stored" and out.row_id is not None
    assert sent and sent[0][2] == "SYNTH"
    # El today de la corrida llega al chequeo de frescura (cableado fix3b).
    assert captured == [TODAY]
    sent, captured = _patch_propuesta(monkeypatch, stale=False)
    out = svc.generate_sotp_proposal(db, company, reasoner=_Recorded([json.dumps(_good())]), today=TODAY)
    assert out.status in ("stored", "cached") and sent == []
    assert captured == [TODAY]


def test_generate_cache_hit_devuelve_lo_guardado(db, monkeypatch):
    company = _company(db)
    monkeypatch.setattr(svc, "sotp_anchors", lambda db, company, today=None: dict(ANCHORS))
    monkeypatch.setattr(svc, "build_sotp_tools", lambda db, anchors: _fake_tools())
    monkeypatch.setattr(svc, "_attach_narrative", lambda *a, **k: None)
    _patch_propuesta(monkeypatch)
    reasoner = _Recorded([json.dumps(_good())])
    out1 = svc.generate_sotp_proposal(db, company, reasoner=reasoner, today=TODAY)
    assert out1.status == "stored"
    # Segunda corrida con la misma evidencia: cache_hit, sin llamada al modelo, estado «cached».
    reasoner2 = _Recorded([])
    out2 = svc.generate_sotp_proposal(db, company, reasoner=reasoner2, today=TODAY)
    assert out2.status == "cached" and out2.cache_hit is True and reasoner2.calls == []
    assert out2.row_id == out1.row_id


def test_generate_rechazo_se_guarda_y_error_al_guardar(db, monkeypatch):
    company = _company(db)
    monkeypatch.setattr(svc, "sotp_anchors", lambda db, company, today=None: dict(ANCHORS))
    monkeypatch.setattr(svc, "build_sotp_tools", lambda db, anchors: _fake_tools())
    _patch_propuesta(monkeypatch)
    sin_cifra = json.dumps(
        {"segments": [{"name": "X", "status": "idea", "business_type": "contratos_gobierno", "anchor": None}]}
    )
    out = svc.generate_sotp_proposal(db, company, reasoner=_Recorded([sin_cifra, sin_cifra]), today=TODAY)
    assert out.status == "rejected"
    # Segunda vez con la misma huella: el rechazo cacheado no vuelve a llamar.
    reasoner2 = _Recorded([])
    out2 = svc.generate_sotp_proposal(db, company, reasoner=reasoner2, today=TODAY)
    assert out2.status == "rejected" and out2.cache_hit is True and reasoner2.calls == []
    # Fallo al guardar la propuesta: estado error «guardar:…», nunca una excepción.
    from app.services.user_sotp_service import UserSotpService

    def boom(db, company, tenant_id, model, *, meta):
        raise RuntimeError("caído")

    monkeypatch.setattr(UserSotpService, "save_agents", boom)
    out3 = svc.generate_sotp_proposal(
        db, company, reasoner=_Recorded([json.dumps(_good())]), today=TODAY, use_cache=False
    )
    assert out3.status == "error" and out3.problems[0].startswith("guardar:")


def test_generate_excepcion_en_la_corrida_nunca_rompe(db, monkeypatch):
    company = _company(db)
    _patch_propuesta(monkeypatch)

    async def boom(*args, **kwargs):
        raise RuntimeError("corrida rota")

    monkeypatch.setattr(svc, "run_sotp_valuer", boom)
    out = svc.generate_sotp_proposal(db, company, reasoner=_Recorded([]))
    assert out.status == "error" and out.problems == ["RuntimeError"]


# ---------------------------------------------------------------- recompute


def _saved_model() -> dict:
    model, problems = svc.parse_proposal(json.loads(json.dumps(_good())), _ledger(), ANCHORS)
    assert problems == []
    return model


def test_recompute_rutas(db, monkeypatch):
    from app.services.user_sotp_service import UserSotpService

    company = _company(db)
    assert svc.recompute_saved_proposal(db, company)["status"] == "no_proposal"
    service = UserSotpService()
    # Clasificación guardada pero sin anclas válidas hoy → rejected_by_rules.
    service.save_agents(
        db, company, T1, _saved_model(), meta={"classification": _classification(), "rules_version": "vieja"}
    )
    monkeypatch.setattr(
        svc, "sotp_anchors", lambda db, company, today=None: {**ANCHORS, "discount_rate": None}
    )
    out = svc.recompute_saved_proposal(db, company)
    assert out["status"] == "rejected_by_rules" and out["problems"]
    # Sin clasificación en la fila: no_classification. recompute crea su propio
    # servicio: se parchea el history del servicio de inputs, no la instancia local.
    from app.services.user_sotp_service import DeclaredInputService

    fila = type("Fila", (), {"metadata_": {}, "base": None, "id": 1})()
    monkeypatch.setattr(DeclaredInputService, "history", lambda self, db, **kw: [fila])
    out = svc.recompute_saved_proposal(db, company)
    assert out["status"] == "no_classification"
    db.info.pop("tenant_id", None)
    assert svc.recompute_saved_proposal(db, company)["status"] == "no_tenant"


# ---------------------------------------------------------------- cache lookup y narrativa


def test_cache_lookup_y_previous_fingerprint(db):
    from app.services.user_sotp_service import UserSotpService

    company = _company(db)
    service = UserSotpService()
    service.save_agents(
        db,
        company,
        T1,
        _saved_model(),
        meta={"fingerprint": {"hash": "h1"}, "classification": {"segments": [1]}},
    )
    service.save_agents(
        db,
        company,
        T1,
        _saved_model(),
        meta={"fingerprint": {"hash": "h2"}, "classification": {"segments": [2]}},
    )
    service.save_rejected(
        db, company, T1, meta={"fingerprint": {"hash": "h3"}, "classification": {"segments": []}}
    )
    lookup = svc._cache_lookup(db, company, T1)
    assert lookup.previous_fingerprint == {"hash": "h2"}
    assert lookup("h1") == {"segments": [1]}
    assert lookup("h3") == {"segments": []}
    assert lookup("no-esta") is None


def test_attach_narrative_guardas(db, monkeypatch):
    company = _company(db)
    result = svc.SotpProposalResult(status="stored")  # sin row_id ni modelo: no-op
    svc._attach_narrative(db, company, T1, result, _Recorded([]), timeout=1.0)
    assert result.narrative is None
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "sotp_agents_narrative_enabled", False, raising=False)
    result = svc.SotpProposalResult(status="stored", row_id=1, model={"parts": []})
    svc._attach_narrative(db, company, T1, result, _Recorded([]), timeout=1.0)
    assert result.narrative is None
