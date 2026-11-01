"""Ronda CodeQL py/stack-trace-exposure: los payloads que llegan al cliente
nunca llevan tipo ni texto de excepcion; el detalle (redactado) va al log.

Antes del fix estos campos llevaban ``f"{type(exc).__name__}: {exc}"``
(redactado de secretos, pero con rutas internas, SQL o mensajes de libreria).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services import insider_service, valuation_service
from app.services.manager_holding_ingestion_service import ManagerHoldingIngestionService
from app.services.moat_service import MoatService

CIK = "0001067983"
SECRET_MARK = "sk-probe-XYZ-INTERNAL-PATH"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_manager_sync_unavailable_reason_is_a_stable_code(db):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"down {SECRET_MARK}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = ManagerHoldingIngestionService(client=client).sync_manager(db, cik=CIK)
    assert result["status"] == "unavailable"
    assert result["reason"] == "fuente_no_disponible"
    assert SECRET_MARK not in result["reason"]
    assert "Error" not in result["reason"]


def test_moat_unavailable_payload_hides_exception_text(monkeypatch):
    engine = type("E", (), {
        "build_context": lambda self, db, company, current_price, as_of=None, **_: object(),
        "currency_input_units": lambda self, context: [],
        "value": lambda self, context: {"ticker": "PIT", "model_type": "test", "status": "ok",
                                        "publishable": True, "trace": {"periods": {"revenue": "FY2025"}}},
    })()
    company = SimpleNamespace(id=1, ticker="PIT")
    monkeypatch.setattr(valuation_service, "resolve", lambda _company: engine)
    monkeypatch.setattr(valuation_service, "resolve_engine_key", lambda _company: "test")
    monkeypatch.setattr(valuation_service, "_position_price", lambda _db, _cid, _as_of=None: 100.0)
    monkeypatch.setattr(valuation_service, "_free_data_trace", lambda _db, _company: None)

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"db interna caida: {SECRET_MARK}")

    monkeypatch.setattr(MoatService, "assess", boom)
    result = valuation_service.ValuationService().value_company(object(), company, as_of=date(2025, 12, 31))
    assert result["moat"]["status"] == "unavailable"
    assert result["moat"]["error"] == "moat_no_disponible"
    assert SECRET_MARK not in str(result["moat"])


def test_insider_notify_skipped_reason_hides_exception_text(monkeypatch):
    monkeypatch.setenv("INSIDER_ALERTS_ENABLED", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        def boom(_payload):
            raise RuntimeError(f"telegram token en ruta {SECRET_MARK}")

        result = insider_service.maybe_notify_insider_buy(
            "ACME", [{"signal": "cluster_buy", "detail": "x"}], notifier=boom
        )
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert result["status"] == "skipped"
    assert result["reason"] == "fuente_no_disponible"
    assert SECRET_MARK not in str(result)
