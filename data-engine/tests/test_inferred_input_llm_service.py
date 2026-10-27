import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.llm import LLMResponse, Message, Usage
from app.models import Tenant
from app.models.entities import BudgetUsage, Company, Document, DocumentChunk, InferredInput
from app.services import inferred_input_llm_service as svc

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
CHUNK = "El flujo de caja libre fue de 12 M USD sobre ingresos de 100 M USD; el margen FCF del ejercicio fue 12%."


def good(**over):
    base = {"value": 0.12, "source_ids": ["src:1"],
            "base": "Dado que el extracto src:1 indica FCF 12 M sobre ingresos 100 M, inferimos un margen FCF de 0.12."}
    base.update(over)
    return base


class Provider:
    name = "stub"

    def __init__(self, *outs):
        self.outs, self.calls, self.in_tx = list(outs), 0, []
        self.db = None

    async def complete(self, request):
        self.calls += 1
        if self.db is not None:
            self.in_tx.append(self.db.in_transaction())
        out = self.outs.pop(0)
        return LLMResponse(Message("assistant", out if isinstance(out, str) else json.dumps(out)),
                           Usage(10, 10, 20), "m", "p")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=True) as s:
        s.add_all([Tenant(id=1, external_id="i-1"), Tenant(id=2, external_id="i-2")])
        s.commit()
        s.info["tenant_id"] = 1
        s.add(Company(id=1, ticker="ASTS", name="AST", exchange="NASDAQ", company_type="pre_revenue",
                      valuation_model="pre_revenue"))
        s.add(Document(id=1, company_id=1, title="10-K", source_type="sec", published_at=NOW - timedelta(days=30),
                       source_url="https://www.sec.gov/Archives/edgar/data/1/10k.htm"))
        s.add(Document(id=2, company_id=1, title="Sin URL", source_type="note", source_url=None))
        s.add(DocumentChunk(document_id=1, chunk_index=0, text=CHUNK))
        s.add(DocumentChunk(document_id=2, chunk_index=0, text=CHUNK))
        s.commit()
        yield s
    engine.dispose()


def run(db, provider, ticker="ASTS"):
    provider.db = db
    return asyncio.run(svc.infer_fcf_margin(db, ticker, provider=provider, now=NOW))


def test_infers_from_ingested_sources_with_service_urls_and_label(db):
    row = run(db, Provider(good()))
    assert row.input_key == "fcf_margin" and row.origin == "llm" and float(row.value) == 0.12
    assert row.source_urls == ["https://www.sec.gov/Archives/edgar/data/1/10k.htm"]
    assert db.scalar(select(func.count(BudgetUsage.id)).where(BudgetUsage.workflow == "inferred_input")) == 1


@pytest.mark.parametrize("fake", ["https://evil.example/x", "http://evil.example", "www.evil.example/a", "https://evil.example/x."])
def test_url_written_by_the_model_in_the_base_is_rejected_and_never_stored(db, fake):
    with pytest.raises(svc.InferenceRejected, match="base_con_url_no_entregada"):
        run(db, Provider(good(base=good()["base"] + f" Fuente: {fake}", urls=[fake])))
    assert db.scalar(select(func.count(InferredInput.id))) == 0


def test_delivered_url_in_the_base_is_allowed_and_payload_has_no_foreign_url(db):
    from app.services.inferred_input_service import payload

    url = "https://www.sec.gov/Archives/edgar/data/1/10k.htm"
    row = run(db, Provider(good(base=good()["base"] + f" Fuente: {url}.", urls=["https://evil.example/x"])))
    out = payload(row)
    assert out["source_urls"] == [url]
    assert "evil.example" not in out["base"] and "evil.example" not in json.dumps(out)


def test_no_sources_is_nd_and_never_calls_the_model(db):
    db.query(DocumentChunk).delete()
    db.commit()
    p = Provider(good())
    with pytest.raises(svc.InferenceRejected, match="sin_fuentes"):
        run(db, p)
    assert p.calls == 0 and db.scalar(select(func.count(InferredInput.id))) == 0


@pytest.mark.parametrize("over,reason", [
    ({"source_ids": []}, "fuente_no_recibida"),
    ({"source_ids": ["src:2"]}, "fuente_no_recibida"),   # documento sin URL: no se entrego
    ({"source_ids": [{}]}, "fuente_no_recibida"),
    ({"base": "corta"}, "base_ausente"),
    ({"base": None}, "base_ausente"),
    ({"value": "NaN"}, "valor_fuera_de_rango"),
    ({"value": 0.9}, "valor_fuera_de_rango"),
    ({"value": True}, "valor_invalido"),
    ({"value": None}, "valor_invalido"),
])
def test_invalid_outputs_are_rejected_and_nothing_is_stored(db, over, reason):
    with pytest.raises(svc.InferenceRejected, match=reason):
        run(db, Provider(good(**over)))
    assert db.scalar(select(func.count(InferredInput.id))) == 0


def test_no_transaction_during_either_llm_call(db):
    cjk = good(base="Dado que el extracto \u4e2d\u6587\u6a21\u578b indica margen 12%, inferimos 0.12 de margen FCF.")
    p = Provider(cjk, good())
    row = run(db, p)
    assert row.id and p.in_tx == [False, False]


def test_daily_quota_blocks_before_calling_the_model(db):
    for i in range(svc.DAILY_QUOTA):
        db.add(InferredInput(tenant_id=1, company_id=1, input_key="fcf_margin", value=0.1,
                             base="b" * 25, source_urls=["https://a.example.com/x"], origin="llm",
                             created_at=NOW - timedelta(hours=1)))
    db.commit()
    p = Provider(good())
    with pytest.raises(svc.QuotaExceeded):
        run(db, p)
    assert p.calls == 0


def test_endpoint_statuses(db, monkeypatch):
    from app.api.routes.companies import router
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(router, prefix="/companies")
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(svc, "create_llm_provider", lambda: Provider(good()))
    client = TestClient(app)
    assert client.post("/companies/ZZZZ/inferred-inputs/llm", json={}).status_code == 404
    assert client.post("/companies/ASTS/inferred-inputs/llm", json={"input_key": "unsupported"}).status_code == 422
    ok = client.post("/companies/ASTS/inferred-inputs/llm", json={})
    assert ok.status_code == 201, ok.text
    assert ok.json()["origin"] == "llm" and ok.json()["input_key"] == "fcf_margin"

RATE_CHUNKS = {
    "wacc": "La deuda tiene un tipo de interes del 6%; beta 1.2 y prima de riesgo del 5% para el coste de capital.",
    "terminal_growth": "La inflacion a largo plazo es 2% y el crecimiento sostenible del PIB se situa en 2.5%.",
}
RATE_VALUES = {"wacc": 0.12, "terminal_growth": 0.025}


def seed_rate_source(db, key):
    db.query(DocumentChunk).filter_by(document_id=1).update({"text": RATE_CHUNKS[key]})
    db.commit()


def rate_good(key, **over):
    return good(value=RATE_VALUES[key],
                base=f"Dado el extracto src:1 y sus cifras publicadas, inferimos {key} en fraccion anual.", **over)


def run_rate(db, provider, key):
    provider.db = db
    return asyncio.run(svc.infer_input(db, "ASTS", input_key=key, provider=provider, now=NOW))


@pytest.mark.parametrize("key", RATE_VALUES)
def test_rate_happy_path_with_service_urls_ignores_model_urls(db, key):
    seed_rate_source(db, key)
    p = Provider(rate_good(key, urls=["https://evil.example/x"]))
    row = run_rate(db, p, key)
    assert row.input_key == key and row.origin == "llm"
    assert float(row.value) == RATE_VALUES[key]
    assert row.source_urls == ["https://www.sec.gov/Archives/edgar/data/1/10k.htm"]
    assert p.in_tx == [False]


@pytest.mark.parametrize("key", RATE_VALUES)
def test_rate_irrelevant_sources_never_call_model(db, key):
    p = Provider(rate_good(key))
    with pytest.raises(svc.InferenceRejected, match="sin_fuentes"):
        run_rate(db, p, key)
    assert p.calls == 0
    assert db.scalar(select(func.count(InferredInput.id))) == 0


@pytest.mark.parametrize("key", RATE_VALUES)
def test_rate_foreign_base_url_is_rejected(db, key):
    seed_rate_source(db, key)
    out = rate_good(key)
    out["base"] += " Fuente: https://evil.example/x"
    with pytest.raises(svc.InferenceRejected, match="base_con_url_no_entregada"):
        run_rate(db, Provider(out), key)
    assert db.scalar(select(func.count(InferredInput.id))) == 0


@pytest.mark.parametrize("key,value,other_key,other_value", [
    ("wacc", 0.045, "terminal_growth", 0.05),
    ("terminal_growth", 0.05, "wacc", 0.06),
])
def test_rate_pair_with_insufficient_spread_is_rejected(db, key, value, other_key, other_value):
    seed_rate_source(db, key)
    db.add(InferredInput(tenant_id=1, company_id=1, input_key=other_key, value=other_value,
                         base="Dado el documento inferimos la otra tasa anual.",
                         source_urls=["https://www.sec.gov/Archives/edgar/data/1/10k.htm"], origin="llm"))
    db.commit()
    out = rate_good(key)
    out["value"] = value
    with pytest.raises(svc.InferenceRejected, match="spread_wacc_terminal_insuficiente"):
        run_rate(db, Provider(out), key)
    assert db.scalar(select(func.count(InferredInput.id))) == 1


@pytest.mark.parametrize("key,values", [
    ("wacc", [0.04, 0.31, "NaN", "Infinity"]),
    ("terminal_growth", [0.0, 0.051, "NaN", "-Infinity"]),
])
def test_rate_value_ranges_are_key_specific(db, key, values):
    seed_rate_source(db, key)
    for value in values:
        out = rate_good(key)
        out["value"] = value
        with pytest.raises(svc.InferenceRejected, match="valor_fuera_de_rango"):
            run_rate(db, Provider(out), key)
    assert db.scalar(select(func.count(InferredInput.id))) == 0


@pytest.mark.parametrize("key", RATE_VALUES)
def test_rate_retry_has_no_open_transaction(db, key):
    seed_rate_source(db, key)
    out = rate_good(key)
    out["base"] += " \u4e2d\u6587\u6a21\u578b"
    p = Provider(out, rate_good(key))
    row = run_rate(db, p, key)
    assert row.id and p.in_tx == [False, False]


@pytest.mark.parametrize("key", RATE_VALUES)
def test_rate_retry_revalidates_budget(db, monkeypatch, key):
    seed_rate_source(db, key)
    checks = iter([True, False])
    monkeypatch.setattr(svc.BudgetController, "can_spend", lambda *_: next(checks))
    out = rate_good(key)
    out["base"] += " \u4e2d\u6587\u6a21\u578b"
    p = Provider(out, rate_good(key))
    with pytest.raises(svc.InferenceRejected, match="presupuesto_agotado"):
        run_rate(db, p, key)
    assert p.calls == 1 and not db.in_transaction()
    assert db.scalar(select(func.count(InferredInput.id))) == 0


@pytest.mark.parametrize("key", RATE_VALUES)
def test_rate_endpoint_201_and_422_nd_without_sources(db, monkeypatch, key):
    from app.api.routes.companies import router
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(router, prefix="/companies")
    app.dependency_overrides[get_db] = lambda: db
    p = Provider(rate_good(key))
    monkeypatch.setattr(svc, "create_llm_provider", lambda: p)
    client = TestClient(app)
    nd = client.post("/companies/ASTS/inferred-inputs/llm", json={"input_key": key})
    assert nd.status_code == 422 and "N/D" in nd.json()["detail"] and p.calls == 0
    seed_rate_source(db, key)
    ok = client.post("/companies/ASTS/inferred-inputs/llm", json={"input_key": key})
    assert ok.status_code == 201, ok.text
    assert ok.json()["input_key"] == key and ok.json()["origin"] == "llm"


@pytest.mark.parametrize("key", RATE_VALUES)
def test_rate_quota_is_shared_across_keys_and_rechecked_on_save(db, key):
    seed_rate_source(db, key)

    class RacingProvider(Provider):
        async def complete(self, request):
            response = await super().complete(request)
            for i in range(svc.DAILY_QUOTA):
                db.add(InferredInput(tenant_id=1, company_id=1, input_key="fcf_margin", value=0.1,
                                     base="b" * 25, source_urls=["https://a.example.com/x"],
                                     origin="llm", created_at=NOW))
            db.commit()
            return response

    p = RacingProvider(rate_good(key))
    with pytest.raises(svc.QuotaExceeded):
        run_rate(db, p, key)
    assert p.calls == 1
    assert db.scalar(select(func.count(InferredInput.id))) == svc.DAILY_QUOTA


def test_sources_are_company_scoped_https_and_max_six(db):
    for i in range(3, 13):
        db.add(Document(id=i, company_id=1, title="10-K", source_type="sec",
                        source_url=f"https://www.sec.gov/Archives/{i}.htm"))
        db.add(DocumentChunk(document_id=i, chunk_index=0, text=RATE_CHUNKS["wacc"]))
    db.add(Company(id=2, ticker="OTHER", name="Other", exchange="NASDAQ", company_type="growth", valuation_model="dcf"))
    db.add(Document(id=13, company_id=2, title="10-K", source_type="sec",
                    source_url="https://www.sec.gov/Archives/other.htm"))
    db.add(DocumentChunk(document_id=13, chunk_index=0, text=RATE_CHUNKS["wacc"]))
    db.add(Document(id=14, company_id=1, title="10-K", source_type="sec",
                    source_url="http://www.sec.gov/invalid.htm"))
    db.add(DocumentChunk(document_id=14, chunk_index=0, text=RATE_CHUNKS["wacc"]))
    db.commit()
    sources = svc.load_sources(db, 1, "wacc")
    assert len(sources) == svc.MAX_DOCS
    assert {s["id"] for s in sources} == {f"src:{i}" for i in range(7, 13)}


@pytest.mark.parametrize("key,value,other_key,other_value", [
    ("wacc", 0.045, "terminal_growth", 0.025),
    ("terminal_growth", 0.025, "wacc", 0.045),
])
def test_exact_minimum_rate_spread_is_accepted(db, key, value, other_key, other_value):
    seed_rate_source(db, key)
    db.add(InferredInput(tenant_id=1, company_id=1, input_key=other_key, value=other_value,
                         base="Dado el documento inferimos la otra tasa anual.",
                         source_urls=["https://www.sec.gov/Archives/edgar/data/1/10k.htm"], origin="llm"))
    db.commit()
    out = rate_good(key)
    out["value"] = value
    row = run_rate(db, Provider(out), key)
    assert float(row.value) == value


@pytest.mark.parametrize("key", RATE_VALUES)
@pytest.mark.parametrize("failure,status", [("disabled", 503), ("budget", 503), ("quota", 429), ("unknown", 404)])
def test_rate_endpoint_failure_statuses(db, monkeypatch, key, failure, status):
    from app.api.routes.companies import router
    from app.core.database import get_db

    seed_rate_source(db, key)
    p = Provider(rate_good(key))
    ticker = "ASTS"
    if failure == "disabled":
        p.name = "disabled"
    elif failure == "budget":
        monkeypatch.setattr(svc.BudgetController, "can_spend", lambda *_: False)
    elif failure == "quota":
        for i in range(svc.DAILY_QUOTA):
            db.add(InferredInput(tenant_id=1, company_id=1, input_key="fcf_margin", value=0.1,
                                 base="b" * 25, source_urls=["https://a.example.com/x"],
                                 origin="llm", created_at=datetime.now(UTC)))
        db.commit()
    else:
        ticker = "ZZZZ"
    monkeypatch.setattr(svc, "create_llm_provider", lambda: p)
    app = FastAPI()
    app.include_router(router, prefix="/companies")
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    response = client.post(f"/companies/{ticker}/inferred-inputs/llm", json={"input_key": key})
    assert response.status_code == status, response.text
    assert p.calls == 0


@pytest.mark.parametrize("key,value,other_key,other_value", [
    ("wacc", 0.045, "terminal_growth", 0.05),
    ("terminal_growth", 0.05, "wacc", 0.06),
])
def test_rate_spread_rechecked_after_llm_returns(db, key, value, other_key, other_value):
    seed_rate_source(db, key)

    class ChangedRateProvider(Provider):
        async def complete(self, request):
            response = await super().complete(request)
            db.add(InferredInput(tenant_id=1, company_id=1, input_key=other_key, value=other_value,
                                 base="Dado el documento inferimos la otra tasa anual.",
                                 source_urls=["https://www.sec.gov/Archives/edgar/data/1/10k.htm"], origin="llm"))
            db.commit()
            return response

    out = rate_good(key)
    out["value"] = value
    with pytest.raises(svc.InferenceRejected, match="spread_wacc_terminal_insuficiente"):
        run_rate(db, ChangedRateProvider(out), key)
    assert db.scalar(select(func.count(InferredInput.id))) == 1


@pytest.mark.parametrize("key", RATE_VALUES)
def test_other_tenant_quota_does_not_block_rates(db, key):
    seed_rate_source(db, key)
    db.info["tenant_id"] = 2
    for i in range(svc.DAILY_QUOTA):
        db.add(InferredInput(tenant_id=2, company_id=1, input_key="fcf_margin", value=0.1,
                             base="b" * 25, source_urls=["https://a.example.com/x"],
                             origin="llm", created_at=NOW))
    db.commit()
    db.info["tenant_id"] = 1
    row = run_rate(db, Provider(rate_good(key)), key)
    assert row.tenant_id == 1 and row.input_key == key


def test_terminal_spread_prefers_traceable_wacc_over_inferred(db):
    from app.models.entities import CalculatedMetric

    seed_rate_source(db, "terminal_growth")
    db.add(InferredInput(tenant_id=1, company_id=1, input_key="wacc", value=0.12,
                         base="Dado el documento inferimos la otra tasa anual.",
                         source_urls=["https://www.sec.gov/Archives/edgar/data/1/10k.htm"], origin="llm"))
    db.add(CalculatedMetric(tenant_id=1, company_id=1, metric="wacc", value=0.06,
                            unit="decimal", period="FY2025", fiscal_year=2025,
                            formula="CAPM", definition_version="v1", status="ok"))
    db.commit()
    out = rate_good("terminal_growth")
    out["value"] = 0.05
    with pytest.raises(svc.InferenceRejected, match="spread_wacc_terminal_insuficiente"):
        run_rate(db, Provider(out), "terminal_growth")
    assert db.scalar(select(func.count(InferredInput.id))) == 1


@pytest.mark.parametrize("key", RATE_VALUES)
def test_prompt_and_excerpts_are_specific_to_requested_rate(db, key):
    seed_rate_source(db, key)

    class InspectingProvider(Provider):
        async def complete(self, request):
            assert svc._TARGETS[key] in request.messages[0].content
            payload = json.loads(request.messages[1].content)
            assert payload["empresa"] == "ASTS"
            assert payload["extractos"][0]["excerpts"] == [RATE_CHUNKS[key]]
            return await super().complete(request)

    row = run_rate(db, InspectingProvider(rate_good(key)), key)
    assert row.input_key == key
