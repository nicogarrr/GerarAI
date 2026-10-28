"""Estados y clasificaciones herméticos, sin peticiones externas."""
import asyncio

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.llm.jev import JevAuthError, JevCreditExhausted, JevDecisionClient
from app.models import ResearchAlert, Tenant
from app.services import jev_availability, jev_gates


def test_billing_402_no_retry():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(402, json={"error": "credit exhausted"})
    client = JevDecisionClient("fake", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        asyncio.run(client.classify("x", "q", "?", {"yes": "yes", "no": "no"}))
        assert False, "Debe detectar falta de crédito"
    except JevCreditExhausted:
        assert len(calls) == 1


def test_transition_persists_once_and_alerts_once(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(external_id="t", name="Test", status="active"))
        db.commit()
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(jev_availability, "SessionLocal", sessionmaker(engine))
    jev_availability.mark_credit_exhausted()
    jev_availability.mark_credit_exhausted()
    with Session(engine) as db:
        assert len(db.scalars(select(ResearchAlert).where(ResearchAlert.alert_type == "typesafe_credit_exhausted")).all()) == 1
    assert jev_availability.credit_status()["last_billing_failure_at"]


def test_fallback_only_marks_tier_one(monkeypatch):
    monkeypatch.setattr(jev_gates, "credit_status", lambda: {"status": "fallback_proveedor_alternativo"})
    class Decision:
        label = "observed"
        confidence = .91
        backend = "jev_fallback_alternative"
    async def free(*args, **kwargs):
        return Decision()
    monkeypatch.setattr(jev_gates, "classify_free", free)
    assert asyncio.run(jev_gates.jev_choice_or_none(name="claim_routing", text="x", instructions="?", criteria={"observed": "x"})) is None
    mark = jev_gates.mark_only("copilot_ticket", "x", "?", {"observed": "x"})
    assert mark["backend"] == "jev_fallback_alternative"

def test_billing_403_with_provider_signal_is_credit():
    def handler(req):
        return httpx.Response(403, text="insufficient_quota: billing hard limit reached")
    client = JevDecisionClient("fake", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        asyncio.run(client.classify("x", "q", "?", {"yes": "yes"}))
        assert False, "403 con señal de billing del proveedor es crédito"
    except JevCreditExhausted:
        pass


def test_plain_403_is_auth_not_credit():
    def handler(req):
        return httpx.Response(403, json={"error": "forbidden: key without access to this model"})
    client = JevDecisionClient("fake", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        asyncio.run(client.classify("x", "q", "?", {"yes": "yes"}))
        assert False, "403 plano no debe tratarse como crédito agotado"
    except JevAuthError:
        pass
    except JevCreditExhausted:
        assert False, "403 plano jamás es JevCreditExhausted"


def test_broken_db_fails_closed_and_stops_typesafe(monkeypatch):
    """DB rota al persistir la transición: el proceso no reintenta TypeSafe
    y expone estado_no_disponible en lugar de seguir facturando a ciegas."""
    monkeypatch.setattr(jev_availability, "_PERSISTENCE_BROKEN", False)

    class BrokenSession:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("db down")
    monkeypatch.setattr(jev_availability, "SessionLocal", BrokenSession())

    jev_availability.mark_credit_exhausted()  # no lanza
    assert jev_availability._PERSISTENCE_BROKEN is True
    assert jev_availability.credit_status()["status"] == "estado_no_disponible"

    monkeypatch.setattr(jev_gates, "credit_status", jev_availability.credit_status)
    def forbidden_client():
        raise AssertionError("TypeSafe no debe llamarse con persistencia rota")
    monkeypatch.setattr(jev_gates, "build_client", forbidden_client)
    result = asyncio.run(jev_gates.jev_choice_or_none(
        name="claim_routing", text="x", instructions="?", criteria={"observed": "x"}))
    assert result is None


def test_mark_credit_exhausted_with_auth_required_writes_alerts(monkeypatch):
    """Regresión: con research_auth_required (producción) los guards de
    database.py rechazaban las alertas tenant-owned escritas desde una sesión
    anónima — RuntimeError «Tenant context is required for tenant-owned
    writes» tras el 402 de TypeSafe. La transición y las alertas deben
    persistir igualmente, cada alerta en la sesión de su tenant."""
    from app.core import database as database_module

    monkeypatch.setattr(database_module.settings, "research_auth_required", True)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(external_id="t1", name="Uno", status="active"))
        db.add(Tenant(external_id="t2", name="Dos", status="active"))
        db.commit()
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(jev_availability, "SessionLocal", sessionmaker(engine))
    monkeypatch.setattr(jev_availability, "_PERSISTENCE_BROKEN", False)
    jev_availability.mark_credit_exhausted()
    assert jev_availability._PERSISTENCE_BROKEN is False
    with Session(engine) as db:
        alerts = db.scalars(
            select(ResearchAlert).where(ResearchAlert.alert_type == "typesafe_credit_exhausted")
        ).all()
        assert len(alerts) == 2
        assert {alert.tenant_id for alert in alerts} == {1, 2}
    assert jev_availability.credit_status()["last_billing_failure_at"]


def test_classify_free_request_uses_registered_prompt_and_traces_it(monkeypatch):
    from app.services import jev_fallback, prompt_registry

    seen = []

    class Provider:
        name = "fake"

        async def generate_json(self, request, *, schema, schema_name):
            seen.append(request)
            return {"choice": "yes", "confidence": 0.9}

    monkeypatch.setattr(jev_fallback, "create_llm_provider", lambda: Provider())
    decision = asyncio.run(
        jev_fallback.classify_free("texto", instructions="?", criteria={"yes": "si", "no": "no"})
    )
    assert decision is not None and decision.label == "yes"
    resolved = prompt_registry.get_prompt("jev_fallback", allow_remote=False)
    assert seen[0].messages[0].content == resolved.text
    assert seen[0].metadata == resolved.trace_metadata()
