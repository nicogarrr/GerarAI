"""Mensajes de limite del API paper: cuota 429, rechazos 503/422, conflictos 409, colas 202."""
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.routes.paper_trading as routes
from app.api.routes.paper_trading import router
from app.core.database import Base, get_db
from app.models import Tenant
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.llm_proposal_runner import QuotaExceeded
from app.services.llm_proposal_service import ProposalRejected
from app.services.paper_trading_service import UnknownProposalCurrency, create_proposal


def body(**kwargs):
    return {"proposal_key": "run-1-ASTS", "ticker": "ASTS", "direction": "long",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "100", "stop": "90", "target": "120", "quantity": "2",
            "inference_basis": "Inferido a partir de los documentos oficiales", **kwargs}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="paper-api-1"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router, prefix="/paper-trading")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client


def test_duplicate_key_with_other_body_is_409(client):
    assert client.post("/paper-trading/proposals", json=body()).status_code == 201
    conflict = client.post("/paper-trading/proposals", json=body(target=130))
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Clave de propuesta duplicada o en conflicto"


def _llm_trade(db):
    row = PaperTrade(**PaperProposal(**body(ticker="BBB", proposal_key="llm:BBB:20261028:t")).model_dump(),
                     author="LLM", inference_label="inferencia", status="pending")
    db.add(row)
    db.commit()
    return row


def test_llm_proposal_success_is_201(db, client):
    row = _llm_trade(db)

    async def generate(session, ticker, **kwargs):
        assert ticker == "BBB"
        return row

    with patch.object(routes, "generate_proposal", generate):
        response = client.post("/paper-trading/llm-proposals", json={"ticker": "BBB"})
    assert response.status_code == 201
    assert response.json()["ticker"] == "BBB"
    assert response.json()["status"] == "pending"


def test_llm_quota_exceeded_is_429_with_message(client):
    async def generate(session, ticker, **kwargs):
        raise QuotaExceeded(5)

    with patch.object(routes, "generate_proposal", generate):
        response = client.post("/paper-trading/llm-proposals", json={"ticker": "ASTS"})
    assert response.status_code == 429
    assert response.json()["detail"] == "cuota diaria de 5 propuestas LLM agotada"


@pytest.mark.parametrize("reason", ["llm_deshabilitado", "presupuesto_agotado", "modelo_no_gratuito",
                                    "modelo_no_verificable", "fallback_no_gratuito"])
def test_llm_infra_rejections_are_503(client, reason):
    async def generate(session, ticker, **kwargs):
        raise ProposalRejected(reason)

    with patch.object(routes, "generate_proposal", generate):
        response = client.post("/paper-trading/llm-proposals", json={"ticker": "ASTS"})
    assert response.status_code == 503
    assert response.json()["detail"] == f"Propuesta rechazada: {reason}"


def test_llm_data_rejection_is_422(client):
    async def generate(session, ticker, **kwargs):
        raise ProposalRejected("sin_cotizacion")

    with patch.object(routes, "generate_proposal", generate):
        response = client.post("/paper-trading/llm-proposals", json={"ticker": "ASTS"})
    assert response.status_code == 422
    assert response.json()["detail"] == "Propuesta rechazada: sin_cotizacion"


def test_llm_unknown_currency_is_409_with_reason(client):
    async def generate(session, ticker, **kwargs):
        raise UnknownProposalCurrency("No se conoce la moneda original de esta propuesta histórica")

    with patch.object(routes, "generate_proposal", generate):
        response = client.post("/paper-trading/llm-proposals", json={"ticker": "ASTS"})
    assert response.status_code == 409
    assert "histórica" in response.json()["detail"]


def test_llm_duplicate_key_is_409(client):
    async def generate(session, ticker, **kwargs):
        raise IntegrityError("INSERT INTO paper_trades ...", {}, Exception("UNIQUE constraint failed"))

    with patch.object(routes, "generate_proposal", generate):
        response = client.post("/paper-trading/llm-proposals", json={"ticker": "ASTS"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Clave de propuesta duplicada o en conflicto"


def test_llm_request_validation_rejects_empty_or_extra(client):
    assert client.post("/paper-trading/llm-proposals", json={"ticker": ""}).status_code == 422
    assert client.post("/paper-trading/llm-proposals", json={"ticker": "ASTS", "price": 1}).status_code == 422


def _dramatiq_stub(monkeypatch, actor_name, message_id):
    sent = {}
    stub = ModuleType("app.workers.dramatiq_app")

    def send(tenant_id, user_id):
        sent["args"] = (tenant_id, user_id)
        return SimpleNamespace(message_id=message_id)

    setattr(stub, actor_name, SimpleNamespace(send=send))
    monkeypatch.setitem(sys.modules, "app.workers.dramatiq_app", stub)
    return sent


def test_refresh_enqueues_worker_with_tenant(db, client, monkeypatch):
    sent = _dramatiq_stub(monkeypatch, "refresh_paper_trades", "msg-refresh-1")
    response = client.post("/paper-trading/refresh")
    assert response.status_code == 202
    assert response.json() == {"status": "queued", "message_id": "msg-refresh-1"}
    assert sent["args"] == (1, None)


def test_feed_enqueues_worker_with_tenant(db, client, monkeypatch):
    sent = _dramatiq_stub(monkeypatch, "propose_paper_trades", "msg-feed-1")
    response = client.post("/paper-trading/feed")
    assert response.status_code == 202
    assert response.json() == {"status": "queued", "message_id": "msg-feed-1"}
    assert sent["args"] == (1, None)


def _open_row(db, *, stale_mark=False, entry_equals_mark=False):
    row = create_proposal(db, PaperProposal(**body()))
    now = datetime.now(UTC)
    mark_at = now - timedelta(days=2) if stale_mark else now - timedelta(minutes=5)
    row.status = "open"
    row.entry_price = Decimal(98)
    row.entry_at = mark_at if entry_equals_mark else now - timedelta(hours=2)
    row.mark_price = Decimal(105)
    row.mark_at = mark_at
    row.currency = "USD"
    db.commit()
    return row


def _no_refresh(db, only_id=None):
    raise AssertionError("no debe refrescar si ya esta cerrada")


def test_close_already_closed_returns_without_refresh(db, client):
    row = create_proposal(db, PaperProposal(**body()))
    row.status = "closed"
    row.entry_price, row.exit_price = Decimal(100), Decimal(110)
    row.exit_at = datetime.now(UTC)
    row.close_reason = "target"
    db.commit()
    with patch.object(routes, "refresh_trades", _no_refresh):
        response = client.post(f"/paper-trading/proposals/{row.id}/close")
    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["close_reason"] == "target"


def test_close_pending_without_fill_is_409_no_price(db, client):
    row = create_proposal(db, PaperProposal(**body()))
    with patch.object(routes, "refresh_trades", lambda db_, only_id=None: {"updated": 0}):
        response = client.post(f"/paper-trading/proposals/{row.id}/close")
    assert response.status_code == 409
    assert response.json()["detail"] == "Sin precio real reciente para cerrar"


def test_close_with_stale_mark_is_409_no_price(db, client):
    row = _open_row(db, stale_mark=True)
    with patch.object(routes, "refresh_trades", lambda db_, only_id=None: {"updated": 0}):
        response = client.post(f"/paper-trading/proposals/{row.id}/close")
    assert response.status_code == 409
    assert response.json()["detail"] == "Sin precio real reciente para cerrar"
    db.expire_all()
    assert db.get(PaperTrade, row.id).status == "open"  # no se cerro sin precio


def test_close_requires_quote_after_entry(db, client):
    row = _open_row(db, entry_equals_mark=True)
    with patch.object(routes, "refresh_trades", lambda db_, only_id=None: {"updated": 0}):
        response = client.post(f"/paper-trading/proposals/{row.id}/close")
    assert response.status_code == 409
    assert response.json()["detail"] == "Falta una cotización posterior a la entrada"


def test_close_manual_uses_observed_mark_and_keeps_legacy_net_na(db, client):
    row = _open_row(db)  # entry_fee NULL: trade legado, no gana costes a medias
    with patch.object(routes, "refresh_trades", lambda db_, only_id=None: {"updated": 0}):
        response = client.post(f"/paper-trading/proposals/{row.id}/close")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "closed"
    assert data["close_reason"] == "manual"
    assert float(data["exit_price"]) == 105.0  # marca observada, no un nivel ideal
    assert float(data["realized_pnl"]) == 14.0  # (105-98) x 2
    assert data["realized_pnl_net"] is None  # legado: neto N/D, no inventado


def test_close_returns_closed_when_refresh_closed_it(db, client):
    row = _open_row(db)

    def closing_refresh(db_, only_id=None):
        current = db_.get(PaperTrade, row.id)
        current.status = "closed"
        current.exit_price = Decimal(104)
        current.exit_at = datetime.now(UTC)
        current.close_reason = "stop"
        db_.commit()
        return {"updated": 1}

    with patch.object(routes, "refresh_trades", closing_refresh):
        response = client.post(f"/paper-trading/proposals/{row.id}/close")
    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["close_reason"] == "stop"
