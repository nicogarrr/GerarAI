import asyncio
import importlib.util
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.bottlenecks import router
from app.core.database import Base, get_db
from app.llm import LLMResponse, Message, Usage
from app.models import BottleneckDiscovery, BottleneckSignal, Company, NewsEvent, Tenant
from app.models.entities import BudgetUsage
from app.services import bottleneck_discovery_service as svc
from app.services.bottleneck_service import refresh_signals
from app.services.llm_router import ROUTES, route_model
from app.workers import dramatiq_app

NOW = datetime(2026, 10, 9, 10, tzinfo=UTC)
GOOD_REASON = svc.compose_reasoning("NVDA", "beneficiaria", "proveedor_directo")


class Router:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def resolve(self, request):
        return self.overrides.get(request.model, request.model or "space-bunny-free")


class Provider:
    name = "stub"

    def __init__(self, *outs):
        self.outs, self.calls = list(outs), 0
        self.model_router: Any = Router()
        self._fallback_model: str | None = None
        self.requests = []

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        out = self.outs.pop(0)
        text = out if isinstance(out, str) else json.dumps(out)
        return LLMResponse(Message("assistant", text), Usage(10, 10, 20), "space-bunny-free", "p")


def cand(ticker: Any = "NVDA", exposicion: Any = "beneficiaria", canal: Any = "proveedor_directo",
         ids=("news_event:1",), **extra):
    return {"ticker": ticker, "exposicion": exposicion, "canal": canal, "evidence_ids": list(ids), **extra}


def out(*candidates):
    return {"candidatos": list(candidates)}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([Tenant(id=1, external_id="a"), Tenant(id=2, external_id="b")])
        session.commit()
        session.info["tenant_id"] = 1
        for i, ticker in enumerate(["NVDA", "AMD", "TSM"], start=1):
            session.add(Company(id=i, ticker=ticker, name=ticker, exchange="NASDAQ",
                                company_type="large_cap", valuation_model="dcf"))
        session.add_all([
            NewsEvent(id=1, title="Chip shortages persist", url="https://pub-a.example/n1",
                      date=datetime(2026, 10, 3, tzinfo=UTC)),
            NewsEvent(id=2, title="Escasez de chips durante el trimestre", url="https://pub-b.example/n2",
                      date=datetime(2026, 10, 4, tzinfo=UTC)),
            NewsEvent(id=3, title="Chip shortages worsen further", url=None,
                      date=datetime(2026, 10, 5, tzinfo=UTC)),
        ])
        session.commit()
        refresh_signals(session)
        session.commit()
        yield session
    engine.dispose()


def run(db, provider, **kw):
    kw.setdefault("now", NOW)
    return asyncio.run(svc.discover(db, provider=provider, **kw))


def stored(db):
    return list(db.scalars(select(BottleneckDiscovery)))


def test_route_is_owner_approved_and_registered():
    from app.core.config import Settings
    from app.llm.model_aliases import is_owner_approved_model

    assert "bottleneck_discovery" in ROUTES
    assert route_model("bottleneck_discovery").task == "bottleneck_discovery"
    assert is_owner_approved_model(route_model("bottleneck_discovery").model, Settings(_env_file=None))


def test_happy_path_saves_inferred_with_budget_record(db):
    provider = Provider(out(cand(ids=("news_event:1", "news_event:2"))))
    result = run(db, provider)
    assert result["status"] == "ok" and result["saved"] == 1 and result["themes_considered"] == 1
    row = stored(db)[0]
    assert (row.label, row.ticker, row.theme, row.model) == ("INFERIDO", "NVDA", "Semiconductores", "space-bunny-free")
    assert row.evidence_ids == ["news_event:1", "news_event:2"] and row.tenant_id == 1
    assert db.scalar(select(func.count(BudgetUsage.id)).where(BudgetUsage.workflow == "bottleneck_discovery")) == 1


def test_context_contains_only_evidence_texts(db):
    ctx = svc.load_theme_contexts(db)
    assert [c.theme for c in ctx] == ["Semiconductores"]
    assert {e.id for e in ctx[0].evidence} == {"news_event:1", "news_event:2", "news_event:3"}
    payload = json.loads(svc.build_request(ctx[0]).messages[1].content)
    assert set(payload) == {"tema", "evidencias"}
    assert all(set(e) == {"id", "texto"} for e in payload["evidencias"])


def test_request_uses_registered_prompt_and_traces_it(db):
    from app.services import prompt_registry

    request = svc.build_request(svc.load_theme_contexts(db)[0])
    resolved = prompt_registry.get_prompt("bottleneck_discovery_service", allow_remote=False)
    assert request.messages[0].content == resolved.text
    assert request.metadata == resolved.trace_metadata()


WORD_QUANTITIES = [
    "El precio de entrada es noventa y cinco por titulo y podria beneficiarse de la escasez.",
    "Fabrica obleas y registra ingresos de noventa por unidad, por lo que podria beneficiarse.",
    "Vende a veintiun dolares la pieza.",
    "Factura trescientos millones al ano segun las fuentes.",
    "Tiene una cuota del cuarenta por ciento del mercado.",
    "Cobra mil quinientos euros por oblea.",
    "Suministra cien mil unidades al trimestre.",
    "Crecera quince veces en dos anos.",
    "El precio objetivo es cincuenta mas diez.",
    "Costs ninety five dollars per share.",
    "Cuesta 95 por titulo y mas info en https://evil.example/x",
]


@pytest.mark.parametrize("item,reason", [
    (cand(ids=("news_event:99",)), "evidencia_no_recibida"),
    (cand(ids=("news_event:1", "document_chunk:1")), "evidencia_no_recibida"),
    (cand(ids=()), "sin_evidencia"),
    (cand(ticker="ZZZZ"), "ticker_inexistente"),
    (cand(ticker="nvda; DROP"), "ticker_invalido"),
    (cand(exposicion="muy beneficiada"), "exposicion_invalida"),
    (cand(canal="noventa y cinco por titulo"), "canal_invalido"),
    (cand(canal="PROVEEDOR_DIRECTO"), "canal_invalido"),
    (cand(exposicion=None), "exposicion_invalida"),
    (cand(motivo="texto libre"), "campos_no_permitidos"),
])
def test_rejections_never_persist(db, item, reason):
    result = run(db, Provider(out(item)))
    assert result["saved"] == 0 and result["rejected"] == {reason: 1}
    assert stored(db) == []


@pytest.mark.parametrize("quantity", WORD_QUANTITIES)
def test_quantities_in_words_cannot_reach_storage_via_free_text_fields(db, quantity):
    # texto libre en cualquier campo: en motivo (campo extra) o como valor de enum
    for item in (cand(motivo=quantity), cand(canal=quantity), cand(exposicion=quantity), cand(ticker=quantity)):
        result = run(db, Provider(out(item)))
        assert result["saved"] == 0 and sum(result["rejected"].values()) == 1, (item, result)
    assert stored(db) == []


def test_stored_reasoning_is_template_only_and_has_no_numbers_or_urls(db):
    import re

    result = run(db, Provider(out(*[cand(ticker=t, exposicion=e, canal=c)
                                    for t, e, c in [("NVDA", "beneficiaria", "proveedor_directo"),
                                                    ("AMD", "afectada", "cliente_dependiente"),
                                                    ("TSM", "beneficiaria", "alternativa_sustitutiva")]])))
    assert result["saved"] == 3
    for row in stored(db):
        assert row.reasoning == svc.compose_reasoning(row.ticker, "beneficiaria" if row.ticker != "AMD" else "afectada",
                                                      {"NVDA": "proveedor_directo", "AMD": "cliente_dependiente",
                                                       "TSM": "alternativa_sustitutiva"}[row.ticker])
        assert not re.search(r"\d|://|www\.", row.reasoning) and "Hipótesis del modelo" in row.reasoning
    assert "N/D" in svc.compose_reasoning("N/D", "afectada", "proveedor_directo")


def test_all_template_texts_pass_the_guard_and_have_no_quantities():
    import re

    from app.services.llm_output_guard import inspect_response_text

    for e in svc.EXPOSURES:
        for c in svc.CHANNELS:
            for t in ("NVDA", "N/D"):
                text = svc.compose_reasoning(t, e, c)
                assert inspect_response_text(text, english="strict") == [], text
                assert not re.search(r"\d|://", text)


def test_schema_has_no_free_text_fields():
    item = svc._SCHEMA["properties"]["candidatos"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["properties"]) == {"ticker", "exposicion", "canal", "evidence_ids"}
    assert "enum" in item["properties"]["exposicion"] and "enum" in item["properties"]["canal"]


def test_guarded_output_rejected_twice_persists_nothing(db):
    bad = out(cand(canal="这家公司可能受益于芯片短缺的供应限制情况说明很长很长很长"))
    result = run(db, Provider(bad, bad))
    assert result["stop_reason"] is None and result["saved"] == 0 and stored(db) == []


def test_nd_ticker_allowed_and_duplicates_dropped(db):
    result = run(db, Provider(out(cand(ticker="N/D"), cand(ticker="NVDA"), cand(ticker="nvda"))))
    assert result["saved"] == 2 and result["rejected"] == {"ticker_duplicado": 1}
    assert {r.ticker for r in stored(db)} == {"N/D", "NVDA"}


def test_malformed_json_and_provider_error_degrade(db):
    assert run(db, Provider("no es json"))["errors"] == 1
    assert run(db, Provider({"otra": 1}))["rejected"] == {"json_invalido": 1}

    class Boom(Provider):
        async def complete(self, request):
            raise RuntimeError("provider down")

    result = run(db, Boom())
    assert result["status"] == "partial" and result["errors"] == 1 and stored(db) == []


def test_guard_retry_records_budget_for_each_call(db):
    bad = "这家公司可能受益于芯片短缺" * 4
    provider = Provider(out(cand(canal=bad)), out(cand()))
    result = run(db, provider)
    assert provider.calls == 2 and result["saved"] == 1
    assert db.scalar(select(func.count(BudgetUsage.id))) == 2


def test_daily_quota(db, monkeypatch):
    monkeypatch.setattr(svc, "DAILY_QUOTA", 1)
    result = run(db, Provider(out(cand(ticker="NVDA"), cand(ticker="AMD"))))
    assert result["saved"] == 1 and len(stored(db)) == 1
    provider = Provider(out(cand(ticker="TSM")))
    again = run(db, provider)
    assert again["status"] == "skipped" and again["stop_reason"] == "cuota_agotada"
    assert provider.calls == 0 and len(stored(db)) == 1


def test_quota_exhausted_mid_run_is_partial(db, monkeypatch):
    db.add(BottleneckDiscovery(theme="Energía", ticker="AMD", reasoning="x", evidence_ids=[], model="m",
                               day=NOW.date(), created_at=NOW))
    db.commit()
    monkeypatch.setattr(svc, "DAILY_QUOTA", 2)
    run(db, Provider(out(cand(ticker="NVDA"))))
    assert len(stored(db)) == 2
    real = svc.todays_discoveries
    first = []

    def blind_once(d, n):  # el pre-chequeo no ve la cuota llena; el guardado bajo candado si
        if not first:
            first.append(1)
            return 0
        return real(d, n)

    monkeypatch.setattr(svc, "todays_discoveries", blind_once)
    result = run(db, Provider(out(cand(ticker="TSM"))))
    assert result["status"] == "partial" and result["stop_reason"] == "cuota_agotada"


def test_same_day_rerun_is_idempotent(db):
    run(db, Provider(out(cand())))
    result = run(db, Provider(out(cand())))
    assert result["saved"] == 0 and len(stored(db)) == 1


def test_budget_exceeded_stops_before_calling_model(db, monkeypatch):
    monkeypatch.setattr(svc.BudgetController, "can_spend", lambda self, d, c: False)
    provider = Provider(out(cand()))
    result = run(db, provider)
    assert result["status"] == "partial" and result["stop_reason"] == "presupuesto_agotado"
    assert provider.calls == 0 and stored(db) == []


def test_budget_exhausted_before_guard_retry(db, monkeypatch):
    answers = iter([True, False])
    monkeypatch.setattr(svc.BudgetController, "can_spend", lambda self, d, c: next(answers))
    provider = Provider(out(cand(canal="这家公司可能受益于芯片短缺" * 4)), out(cand()))
    result = run(db, provider)
    assert result["stop_reason"] == "presupuesto_agotado" and provider.calls == 1 and stored(db) == []


def test_disabled_and_non_free_route_skip(db, monkeypatch):
    class Off(Provider):
        name = "disabled"

    assert run(db, Off())["stop_reason"] == "llm_deshabilitado"
    monkeypatch.setattr(svc, "route_model", lambda task: type("R", (), {"model": "caro-pro"})())
    provider = Provider(out(cand()))
    assert run(db, provider)["stop_reason"] == "modelo_no_gratuito" and provider.calls == 0


def test_session_released_before_llm_call(db):
    seen = []

    class Watcher(Provider):
        async def complete(self, request):
            seen.append(db.in_transaction())
            return await super().complete(request)

    run(db, Watcher(out(cand())))
    assert seen == [False]


def test_min_sources_threshold(db):
    assert run(db, Provider(), min_sources=3)["themes_considered"] == 0
    row = db.scalar(select(BottleneckSignal))
    row.n_sources = 1
    db.commit()
    assert svc.load_theme_contexts(db) == []


def test_tenant_isolation(db):
    run(db, Provider(out(cand())))
    db.info["tenant_id"] = 2
    # señal forjada del tenant 2 que apunta a ids del tenant 1: no se resuelven
    db.add(BottleneckSignal(theme="Semiconductores", evidence_ids=["news_event:1", "news_event:2"], n_sources=5))
    db.commit()
    assert svc.resolve_evidence(db, ["news_event:1"]) == {}
    provider = Provider(out(cand()))
    result = run(db, provider)
    assert result["themes_considered"] == 0 and provider.calls == 0
    assert stored(db) == []
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        body = client.get("/api/bottlenecks/discoveries").json()
    assert body["items"] == [] and body["total"] == 0
    db.info.clear()
    assert svc.load_theme_contexts(db) == [] and svc.resolve_evidence(db, ["news_event:1"]) == {}


def test_e2e_to_endpoint_with_real_urls_and_pagination(db):
    run(db, Provider(out(cand(ticker="NVDA", ids=("news_event:1", "news_event:3")), cand(ticker="AMD"))))
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        body = client.get("/api/bottlenecks/discoveries").json()
        assert body["total"] == 2 and body["has_more"] is False and "INFERIDO" in body["note"]
        nvda = next(i for i in body["items"] if i["ticker"] == "NVDA")
        assert nvda["label"] == "INFERIDO" and nvda["reasoning"] == GOOD_REASON
        assert nvda["evidence"][0] == {"id": "news_event:1", "title": "Chip shortages persist",
                                       "url": "https://pub-a.example/n1", "status": "verificada"}
        assert nvda["evidence"][1]["url"] is None and nvda["evidence"][1]["status"] == "N/D"
        page = client.get("/api/bottlenecks/discoveries", params={"limit": 1, "offset": 0}).json()
        assert len(page["items"]) == 1 and page["has_more"] is True
        assert client.get("/api/bottlenecks/discoveries", params={"limit": 1, "offset": 1}).json()["has_more"] is False
        assert client.get("/api/bottlenecks/discoveries", params={"limit": 0}).status_code == 422
        assert client.get("/api/bottlenecks/discoveries", params={"limit": 101}).status_code == 422
        assert client.get("/api/bottlenecks").status_code == 200  # la ruta antigua sigue igual


def test_endpoint_without_tenant_is_empty(db):
    db.info.clear()
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get("/api/bottlenecks/discoveries").json()["items"] == []


def test_non_http_urls_are_nd():
    assert svc._real_url("javascript:alert(1)") is None
    assert svc._real_url("  https://ok.example/a ") == "https://ok.example/a"
    assert svc._real_url(None) is None


def test_label_is_enforced_by_schema(db):
    from sqlalchemy.exc import IntegrityError

    db.add(BottleneckDiscovery(theme="t", ticker="X", reasoning="r", evidence_ids=[], model="m", label="HECHO",
                               day=NOW.date(), created_at=NOW))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_migration_upgrade_downgrade():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = Path(__file__).parents[1] / "alembic/versions/0057_bottleneck_discovery.py"
    spec = importlib.util.spec_from_file_location("migration_discovery", path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0056_bottleneck_signal"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        columns = {c["name"] for c in inspect(conn).get_columns("bottleneck_discovery")}
        assert columns == {c.name for c in BottleneckDiscovery.__table__.columns}
        module.downgrade()
        assert "bottleneck_discovery" not in inspect(conn).get_table_names()
    engine.dispose()


# --- actor ------------------------------------------------------------------

def _fn() -> Callable[..., dict[str, Any]]:
    return cast(Callable[..., dict[str, Any]], getattr(dramatiq_app.discover_bottlenecks, "fn", dramatiq_app.discover_bottlenecks))


@pytest.fixture
def actor_env(db, monkeypatch):
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(dramatiq_app, "_session", lambda t, u: db)
    monkeypatch.setattr(dramatiq_app, "_run", lambda coro: asyncio.run(coro))
    monkeypatch.setattr(svc, "create_llm_provider", lambda: Provider(out(cand())))
    return db


class FakeDeadline:
    def __init__(self, expired_value=False, truncated=False):
        self._expired, self.truncated = expired_value, truncated

    def expired(self):
        return self._expired


def test_actor_declares_explicit_time_limit():
    options = dramatiq_app.discover_bottlenecks.options
    # max_retries=2: politica de ingesta de b199a6ed0 (tests/test_worker_retry_policy.py).
    assert options["time_limit"] == 600_000 and options["max_retries"] == 2
    assert options["time_limit"] > dramatiq_app.DISCOVERY_DEADLINE_SECONDS * 1000


def test_actor_ok(actor_env):
    result = _fn()(1, "u")
    assert result["actor"] == "discover_bottlenecks" and result["status"] == "ok" and result["saved"] == 1


def test_actor_returns_partial_when_deadline_truncates(actor_env, monkeypatch):
    monkeypatch.setattr("app.services.ticker_news_lane.Deadline", lambda s: FakeDeadline(expired_value=True))
    result = _fn()(1, "u")
    assert result["status"] == "partial" and result["stop_reason"] == "deadline" and result["saved"] == 0


def test_actor_marks_truncated_sweep_partial_even_if_loop_finished(actor_env, monkeypatch):
    monkeypatch.setattr("app.services.ticker_news_lane.Deadline", lambda s: FakeDeadline(truncated=True))
    assert _fn()(1, "u")["status"] == "partial"


def test_actor_skipped_when_llm_disabled(actor_env, monkeypatch):
    class Off(Provider):
        name = "disabled"

    monkeypatch.setattr(svc, "create_llm_provider", lambda: Off())
    result = _fn()(1, "u")
    assert result["status"] == "skipped" and result["stop_reason"] == "llm_deshabilitado"


def test_actor_permanent_error_is_structured_and_transient_retries(actor_env, monkeypatch):
    async def boom(db, **kw):
        raise ValueError("permanente")

    monkeypatch.setattr(svc, "discover", boom)
    assert _fn()(1, "u")["status"] == "error"

    async def transient(db, **kw):
        raise ConnectionError("db down")

    monkeypatch.setattr(svc, "discover", transient)
    with pytest.raises(ConnectionError):
        _fn()(1, "u")


def test_resolves_document_and_knowledge_lanes_with_real_urls(db):
    from datetime import date

    from app.models import Document, DocumentChunk, KnowledgeChunk, KnowledgeDocument

    doc = Document(title="Filing", source_type="filing", source_url="https://chips.example/filing",
                   published_at=datetime(2026, 10, 1, tzinfo=UTC))
    letter = KnowledgeDocument(title="Carta", document_type="fund_letter", author="Fondo A",
                               source_url="ftp://no-http.example/x", publication_date=date(2026, 10, 2),
                               status="ready")
    db.add_all([doc, letter])
    db.flush()
    dchunk = DocumentChunk(document_id=doc.id, chunk_index=0, text="Chip shortages persist")
    kchunk = KnowledgeChunk(knowledge_document_id=letter.id, chunk_index=0, content="Escasez de chips")
    db.add_all([dchunk, kchunk])
    db.commit()
    ids = [f"document_chunk:{dchunk.id}", f"knowledge_chunk:{kchunk.id}", "news_event:abc", "otro:1"]
    found = svc.resolve_evidence(db, ids)
    assert set(found) == set(ids[:2])
    assert found[ids[0]].url == "https://chips.example/filing" and found[ids[0]].title == "Filing"
    assert found[ids[1]].url is None and found[ids[1]].text == "Escasez de chips"
    db.info["tenant_id"] = 2
    assert svc.resolve_evidence(db, ids) == {}


# --- modelo gratuito RESUELTO ---------------------------------------------------

def test_request_pins_the_go_model(db):
    provider = Provider(out(cand()))
    run(db, provider)
    assert provider.requests[0].model == "deepseek-v4.1-flash" and provider.requests[0].task == "bottleneck_discovery"


@pytest.mark.parametrize("overrides", [
    {"deepseek-v4.1-flash": "paid-model"},
    {"bottleneck_discovery": "paid-model", "deepseek-v4.1-flash": "paid-model"},
])
def test_env_override_to_paid_model_skips_before_any_call(db, overrides):
    provider = Provider(out(cand()))
    provider.model_router = Router(overrides)
    result = run(db, provider)
    assert result["status"] == "skipped" and result["stop_reason"] == "modelo_no_gratuito"
    assert provider.calls == 0 and stored(db) == []
    assert db.scalar(select(func.count(BudgetUsage.id))) == 0


def test_real_task_model_router_override_is_caught(db):
    from app.llm.routing import TaskModelRouter

    provider = Provider(out(cand()))
    provider.model_router = TaskModelRouter(default_model="space-bunny-free",
                                            overrides={"deepseek-v4.1-flash": "paid-model"})
    assert run(db, provider)["stop_reason"] == "modelo_no_gratuito" and provider.calls == 0
    ok = Provider(out(cand()))
    ok.model_router = TaskModelRouter(default_model="space-bunny-free", overrides={"bottleneck_discovery": "paid"})
    # el modelo fijado en el request gana al override por tarea, y el resuelto es aprobado
    assert run(db, ok)["status"] == "ok" and ok.calls == 1


def test_paid_fallback_model_blocks_and_free_fallback_allows(db):
    provider = Provider(out(cand()))
    provider._fallback_model = "paid-fallback"
    assert run(db, provider)["stop_reason"] == "fallback_no_gratuito" and provider.calls == 0
    ok = Provider(out(cand()))
    ok._fallback_model = "space-bunny-free"
    assert run(db, ok)["status"] == "ok"


def test_unverifiable_model_fails_closed(db):
    no_router = Provider(out(cand()))
    del no_router.model_router
    assert run(db, no_router)["stop_reason"] == "modelo_no_verificable" and no_router.calls == 0

    class Broken:
        def resolve(self, request):
            raise ValueError("alias disabled")

    broken = Provider(out(cand()))
    broken.model_router = Broken()
    assert run(db, broken)["stop_reason"] == "modelo_no_verificable"


# --- deadline antes y despues de cada unidad -------------------------------------

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


from app.services.ticker_news_lane import Deadline as RealDeadline  # noqa: E402


def _deadline(clock, seconds=10):
    return RealDeadline(seconds, clock=clock)


def test_deadline_expiring_during_llm_call_discards_and_flags_partial(db):
    clock = Clock()

    class Slow(Provider):
        async def complete(self, request):
            response = await super().complete(request)
            clock.t = 99.0  # vence DURANTE la llamada
            return response

    deadline = _deadline(clock)
    result = run(db, Slow(out(cand())), deadline=deadline)
    assert result["status"] == "partial" and result["stop_reason"] == "deadline"
    assert deadline.truncated is True and result["saved"] == 0 and stored(db) == []
    # el gasto de la llamada ya hecha SI queda registrado
    assert db.scalar(select(func.count(BudgetUsage.id))) == 1


def test_deadline_expiring_during_persistence_is_partial_but_kept(db, monkeypatch):
    clock = Clock()
    real = svc.save_within_quota

    def slow_save(*a, **k):
        saved = real(*a, **k)
        clock.t = 99.0
        return saved

    monkeypatch.setattr(svc, "save_within_quota", slow_save)
    deadline = _deadline(clock)
    result = run(db, Provider(out(cand())), deadline=deadline)
    assert result["status"] == "partial" and result["stop_reason"] == "deadline"
    assert result["saved"] == 1 and deadline.truncated is True


def test_deadline_hard_stops_a_hanging_provider(db):
    from app.services.ticker_news_lane import Deadline

    class Hang(Provider):
        async def complete(self, request):
            await asyncio.sleep(5)

    deadline = Deadline(0.05)
    result = run(db, Hang(), deadline=deadline)
    assert result["status"] == "partial" and result["stop_reason"] == "deadline"
    assert deadline.truncated is True and stored(db) == []


def test_deadline_not_expired_stays_ok(db):
    deadline = _deadline(Clock())
    result = run(db, Provider(out(cand())), deadline=deadline)
    assert result["status"] == "ok" and result["stop_reason"] is None and deadline.truncated is False


def test_actor_reports_partial_when_deadline_crosses_during_call(actor_env, monkeypatch):
    clock = Clock()
    monkeypatch.setattr("app.services.ticker_news_lane.Deadline", lambda s: _deadline(clock, 10))

    class Slow(Provider):
        async def complete(self, request):
            response = await super().complete(request)
            clock.t = 99.0
            return response

    monkeypatch.setattr(svc, "create_llm_provider", lambda: Slow(out(cand())))
    result = _fn()(1, "u")
    assert result["status"] == "partial" and result["stop_reason"] == "deadline" and result["saved"] == 0


def test_signals_return_resolved_sources_not_only_opaque_ids(db):
    from app.api.routes.bottlenecks import list_bottlenecks
    refresh_signals(db)
    signals = list_bottlenecks(db).signals
    found = [e for signal in signals for e in signal.evidence]
    assert any(e.url == 'https://pub-a.example/n1' and e.status == 'verificada' for e in found)
    assert all(e.id for e in found)


def _patterns(*companies):
    return {t: svc._mention_pattern(t, n) for t, n in companies}


def test_mention_pattern_matches_ticker_and_name_without_suffix():
    pattern = svc._mention_pattern("CVU", "CV Sciences, Inc.")
    assert pattern.search(svc.fold("CV Sciences anuncia un acuerdo"))
    assert pattern.search(svc.fold("Las acciones de CVU suben"))
    assert not pattern.search(svc.fold("El mercado de chips se tensiona"))


def test_mention_pattern_skips_short_tickers():
    # Ticker de 2 letras: no se prueba como palabra suelta ("bn" en un texto
    # tematico no es evidencia de Brookfield); solo casa el nombre completo.
    pattern = svc._mention_pattern("BN", "Brookfield Corporation")
    assert pattern.search(svc.fold("Brookfield reporta resultados"))
    assert not pattern.search(svc.fold("un parrafo con bn suelto"))
    # Sin nombre util y ticker corto no hay patron fiable: mejor None.
    assert svc._mention_pattern("BN", None) is None
    short_name = svc._mention_pattern("BN", "BN Inc.")
    assert short_name is None or not short_name.search(svc.fold("bn cae hoy"))


def test_mention_pattern_skips_common_word_tickers():
    # NOW/META/ZETA son palabras comunes: en minusculas (fold) serian falsos
    # positivos sobre evidencia tematica, asi que casan por nombre, no ticker.
    pattern = svc._mention_pattern("NOW", "ServiceNow, Inc.")
    assert pattern.search(svc.fold("ServiceNow cierra un acuerdo"))
    assert not pattern.search(svc.fold("act now before the deadline"))
    meta = svc._mention_pattern("META", "Meta Platforms, Inc.")
    assert meta.search(svc.fold("Meta Platforms presenta gafas"))
    assert not meta.search(svc.fold("la meta del proyecto es clara"))
    zeta = svc._mention_pattern("ZETA", "Zeta Global Holdings Corp.")
    assert zeta.search(svc.fold("Zeta Global crece en marketing"))
    assert not zeta.search(svc.fold("la funcion zeta de Riemann"))


def test_cites_other_company_only_detects_cross_ticker_evidence():
    patterns = _patterns(("AAPL", "Apple Inc."), ("MSFT", "Microsoft Corporation"))
    # La evidencia habla de Apple, no de Microsoft: cruce detectado.
    assert svc._cites_other_company_only(["Apple reporta ventas récord"], "MSFT", patterns)
    # Si la evidencia tambien nombra al candidato, no es cruce.
    assert not svc._cites_other_company_only(["Apple y Microsoft firman"], "MSFT", patterns)
    # Evidencia tematica sin empresa conocida: la inferencia sigue permitida.
    assert not svc._cites_other_company_only(["Chip shortages persist"], "MSFT", patterns)


def test_cross_ticker_evidence_rejected_end_to_end(db):
    db.add(NewsEvent(id=4, title="NVDA asegura chips ante la escasez",
                     url="https://pub-c.example/n4", date=datetime(2026, 10, 6, tzinfo=UTC)))
    db.commit()
    refresh_signals(db)
    db.commit()
    result = run(db, Provider(out(cand(ticker="AMD", ids=("news_event:4",)))))
    assert result["saved"] == 0 and result["rejected"] == {"evidencia_de_otra_empresa": 1}
    assert stored(db) == []
    # La misma evidencia citada por la empresa de la que habla si se acepta.
    result = run(db, Provider(out(cand(ticker="NVDA", ids=("news_event:4",)))))
    assert result["saved"] == 1


def test_distinct_sources_collapses_chunks_of_one_document():
    def ev(id_, title, url):
        return svc.ResolvedEvidence(id_, f"texto de {id_}", title, url, None)

    chunks = [
        ev("document_chunk:1", "AAPL 10-K 2025", "https://sec.gov/aapl-10k"),
        ev("document_chunk:2", "AAPL 10-K 2025", "https://sec.gov/aapl-10k"),
        ev("document_chunk:3", "AAPL 10-Q T3", "https://sec.gov/aapl-10q"),
        ev("news_event:9", "Titular suelto", None),
        ev("news_event:10", "Titular suelto", None),
    ]
    assert [e.id for e in svc.distinct_sources(chunks)] == [
        "document_chunk:1", "document_chunk:3", "news_event:9"]


def test_reasoning_uses_curated_company_profile(db):
    """La hipotesis es especifica por empresa con datos curados de `companies`
    (nombre · industria); nunca texto libre del modelo."""
    text = svc.compose_reasoning("SIFI", "beneficiaria", "proveedor_directo",
                                 company_name="SIFCO Industries", sector="Industrials",
                                 industry="Aerospace & Defense")
    assert "SIFI (SIFCO Industries · Aerospace & Defense)" in text
    # Sin ficha curada util: se omite el detalle (nombre = ticker o "Unknown").
    plain = svc.compose_reasoning("XYZ", "afectada", "cliente_dependiente",
                                  company_name="XYZ", sector="Unknown", industry="Unknown")
    assert "XYZ (" not in plain
    # Sin industria curada se usa el sector.
    sec = svc.compose_reasoning("ABC", "afectada", "cliente_dependiente",
                                company_name="Acme", sector="Utilities", industry="Unknown")
    assert "ABC (Acme · Utilities)" in sec


def test_run_persists_company_profile_in_reasoning(db):
    company = db.scalar(select(Company).where(Company.ticker == "NVDA"))
    company.name = "NVIDIA Corp."
    company.industry = "Semiconductors"
    db.commit()
    result = run(db, Provider(out(cand(ticker="NVDA", exposicion="beneficiaria", canal="proveedor_directo"))))
    assert result["saved"] == 1
    row = db.scalar(select(svc.BottleneckDiscovery).where(svc.BottleneckDiscovery.ticker == "NVDA"))
    assert "NVIDIA Corp. · Semiconductors" in row.reasoning
    # Los demas (nombre = ticker, industria Unknown) conservan el texto anterior.
