"""Paper trading anclado a la tesis vigente del tenant (no a un texto suelto)."""
import asyncio
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.paper_trading import router
from app.core.database import Base, get_db
from app.llm import LLMResponse, Message, Usage
from app.models import Tenant
from app.models.entities import Company, NewsEvent, ThesisVersion
from app.schemas.paper_trading import PaperProposal
from app.services import llm_proposal_runner as runner
from app.services import llm_proposal_service as proposal_service
from app.services import prompt_registry
from app.services.llm_proposal_service import ProposalRejected, validate_output
from app.services.paper_thesis_anchor import prompt_context
from app.services.paper_trading_service import create_proposal

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def good(**over):
    base = {
        "direction": "long", "horizon": "short",
        "thesis": "El contrato nuevo encaja con la tesis de ingresos recurrentes.",
        "conviction": 0.6, "entry": 99.0, "stop": 92.0, "target": 115.0,
        "evidence_ids": ["news:1"],
        "inference_basis": "Inferencia mia: el contrato refuerza la tesis vigente.",
    }
    base.update(over)
    return base


class Router:
    def resolve(self, request):
        return request.model or "space-bunny-free"


class Provider:
    """Proveedor local: guarda cada petición y puede ejecutar algo durante la llamada."""

    name = "stub"
    _fallback_model: Any = None

    def __init__(self, out, during=None):
        self.out, self.during, self.requests = out, during, []
        self.model_router: Any = Router()

    async def complete(self, request):
        self.requests.append(request)
        if self.during is not None:
            self.during()
        return LLMResponse(Message("assistant", json.dumps(self.out)), Usage(10, 10, 20), "m", "p")


def quote(_ticker):
    return {"live_c": 100.0, "live_t": NOW.timestamp() - 60, "currency": "USD"}


def thesis(db, version, *, tenant_id=1, status="draft", summary="Resumen de la tesis", **values):
    # Cada cuenta escribe con su propio contexto: la sesión bloquea escrituras cruzadas.
    current = db.info["tenant_id"]
    db.info["tenant_id"] = tenant_id
    try:
        row = ThesisVersion(
            tenant_id=tenant_id, company_id=1, version=version, status=status, thesis_markdown="#",
            executive_summary=summary, rating="watch", created_at=NOW - timedelta(days=10 - version),
            invalidation_criteria=["El margen operativo cae por debajo del 20 %"], **values,
        )
        db.add(row)
        db.commit()
    finally:
        db.info["tenant_id"] = current
    return row


def manual(key="manual:AAPL:1", ticker="AAPL"):
    return PaperProposal(
        proposal_key=key, ticker=ticker, direction="long", horizon="short",
        thesis="Propuesta manual de prueba con riesgos y fuentes.", conviction=Decimal("0.5"),
        proposed_entry=Decimal("100"), stop=Decimal("90"), target=Decimal("120"),
        quantity=Decimal("1"), inference_basis="Inferencia manual de prueba.", currency="USD",
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([Tenant(id=1, external_id="anchor-1"), Tenant(id=2, external_id="anchor-2")])
        session.add(Company(id=1, ticker="AAPL", name="Apple", exchange="NASDAQ",
                            company_type="large_cap", valuation_model="dcf"))
        session.commit()
        session.info["tenant_id"] = 1
        session.add(NewsEvent(id=1, company_id=1, date=NOW - timedelta(days=1), title="Apple firma un contrato",
                              source="Reuters", metadata_={"source_headline": "Apple firma un contrato"}))
        session.commit()
        yield session
    engine.dispose()


def run(db, provider):
    return asyncio.run(runner.generate_proposal(db, "AAPL", provider=provider, fetch_quote=quote, now=NOW))


def sent_payload(provider):
    return json.loads(provider.requests[0].messages[1].content)


def test_manual_proposal_anchors_to_latest_thesis_of_the_same_tenant(db):
    thesis(db, 1, tenant_id=2)  # otra cuenta: nunca ancla
    assert create_proposal(db, manual("manual:AAPL:none")).thesis_version_id is None
    v1 = thesis(db, 1)
    v2 = thesis(db, 2)
    assert v1.id != v2.id
    row = create_proposal(db, manual())
    assert row.thesis_version_id == v2.id
    # Un reintento idéntico tras una versión nueva conserva el ancla original.
    thesis(db, 3)
    assert create_proposal(db, manual()).thesis_version_id == v2.id


def test_model_sees_publishable_thesis_and_trade_keeps_that_version(db):
    seen = thesis(db, 1, base_value=Decimal("120"), bear_value=Decimal("80"), bull_value=Decimal("150"))
    # Una versión nueva publicada DURANTE la llamada no cambia el ancla.
    provider = Provider(good(evidence_ids=["news:1", f"thesis:{seen.id}"]), during=lambda: thesis(db, 2))
    row = run(db, provider)
    context = sent_payload(provider)["tesis_vigente"]
    assert context["id"] == f"thesis:{seen.id}" and context["publicable"] is True
    values = (context["valor_base"], context["valor_bajista"], context["valor_alcista"])
    assert tuple(Decimal(v) for v in values) == (Decimal("120"), Decimal("80"), Decimal("150"))
    assert context["invalidacion"] == ["El margen operativo cae por debajo del 20 %"]
    assert row.thesis_version_id == seen.id
    assert provider.requests[0].metadata["prompt_name"] == "paper_trade_proposal"


def test_withheld_thesis_reaches_the_model_without_figures(db):
    # Publicada sin modelo publicable: la puerta la retiene (fail-closed).
    withheld = thesis(db, 1, status="published", summary="Texto archivado", base_value=Decimal("999"))
    context = prompt_context(db, withheld)
    assert context["publicable"] is False and context["motivo"]
    assert not {"valor_base", "resumen", "invalidacion", "rating"} & set(context)
    provider = Provider(good())
    row = run(db, provider)
    raw = provider.requests[0].messages[1].content
    assert "999" not in raw and "Texto archivado" not in raw
    assert row.thesis_version_id == withheld.id


def test_without_thesis_the_payload_says_so_and_nothing_is_anchored(db):
    provider = Provider(good())
    row = run(db, provider)
    assert sent_payload(provider)["tesis_vigente"] is None
    assert row.thesis_version_id is None


@pytest.mark.parametrize("evidence,thesis_id,ok", [
    (["news:1", "thesis:7"], "thesis:7", True),
    (["thesis:7"], "thesis:7", False),  # la tesis no sustituye a un titular fechado
    (["news:1", "thesis:8"], "thesis:7", False),  # id de tesis que no se envió
    (["news:1", "thesis:7"], None, False),
])
def test_evidence_may_cite_the_received_thesis_but_needs_a_headline(evidence, thesis_id, ok):
    call = lambda: validate_output(  # noqa: E731
        good(evidence_ids=evidence), ticker="AAPL", price=Decimal("100"), headline_ids={"news:1"},
        now=NOW, currency="USD", thesis_id=thesis_id,
    )
    if ok:
        assert call().ticker == "AAPL"
    else:
        with pytest.raises(ProposalRejected, match="evidencia_no_recibida"):
            call()


def test_proposals_filter_by_ticker_and_flag_superseded_thesis(db):
    v1 = thesis(db, 1)
    create_proposal(db, manual("manual:AAPL:a"))
    db.add(Company(id=2, ticker="MSFT", name="Microsoft", exchange="NASDAQ",
                   company_type="large_cap", valuation_model="dcf"))
    db.commit()
    create_proposal(db, manual("manual:MSFT:a", ticker="MSFT"))
    app = FastAPI()
    app.include_router(router, prefix="/api/paper-trading")
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    rows = client.get("/api/paper-trading/proposals", params={"ticker": "aapl"}).json()
    assert [r["ticker"] for r in rows] == ["AAPL"]
    assert rows[0]["thesis_anchor"]["id"] == v1.id and rows[0]["thesis_anchor"]["superseded"] is False
    thesis(db, 2, tenant_id=2)  # una versión de otra cuenta no marca la tesis como cambiada
    assert client.get("/api/paper-trading/proposals", params={"ticker": "AAPL"}).json()[0]["thesis_anchor"]["superseded"] is False
    thesis(db, 2)
    anchor = client.get("/api/paper-trading/proposals", params={"ticker": "AAPL"}).json()[0]["thesis_anchor"]
    assert (anchor["version"], anchor["latest_version"], anchor["superseded"]) == (1, 2, True)
    msft = client.get("/api/paper-trading/proposals", params={"ticker": "MSFT"}).json()
    assert msft[0]["thesis_anchor"] is None
    assert len(client.get("/api/paper-trading/proposals").json()) == 2


def test_prompt_lives_in_the_registry_with_its_version():
    resolved = prompt_registry.get_prompt("paper_trade_proposal", allow_remote=False)
    assert proposal_service.SYSTEM == resolved.text == prompt_registry.PAPER_TRADE_PROPOSAL
    assert resolved.version == "paper-proposal-v2-thesis"
    assert "tesis_vigente" in proposal_service.SYSTEM


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/0099_paper_trade_thesis_version.py"
    spec = importlib.util.spec_from_file_location("paper_thesis_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_idempotent_and_downgrade_keeps_trades(monkeypatch):
    module = _migration()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE thesis_versions (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, status VARCHAR(12))")
        conn.exec_driver_sql("INSERT INTO paper_trades VALUES (1, 'closed'), (2, 'open')")
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()
        assert list(conn.exec_driver_sql("SELECT id, status, thesis_version_id FROM paper_trades ORDER BY id")) == [
            (1, "closed", None), (2, "open", None)]
        assert any(fk["referred_table"] == "thesis_versions" for fk in inspect(conn).get_foreign_keys("paper_trades"))
        module.downgrade()
        module.downgrade()
        assert {c["name"] for c in inspect(conn).get_columns("paper_trades")} == {"id", "status"}
        assert list(conn.exec_driver_sql("SELECT * FROM paper_trades ORDER BY id")) == [(1, "closed"), (2, "open")]
    context = MigrationContext.configure(dialect_name="postgresql")
    assert len(module.revision) <= context._version.c.version_num.type.length
    assert module.down_revision == "0098_dca_direction_settings"
