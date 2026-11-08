"""Huecos de cobertura en corporate_actions, plan y knowledge_rag (lote 9).

Medicion previa (mismo metodo, tests que referencian cada modulo):
corporate_actions 83 % (ingesta async, apply y delete), plan 90,8 %
(get_plan con plan, lista y borrado de aportaciones, drift, proyeccion) y
knowledge_rag 88 % (list/get sources, disco lleno -> 507, abandono de
processing, fallo de dispatch -> 503 y fallo de query -> 503). Estos
tests cierran esas ramas con servicios doblados.

Que NO se prueba aqui: nada de HTTP ni auth; ningun servicio real
(CorporateActionService, InvestmentPlanService, register_source,
search_knowledge, el actor de ingesta van doblados); ningun proveedor de
datos, disco, cola dramatiq ni Qdrant reales; y el _payload de
corporate_actions va doblado en apply/delete (su forma se prueba en los
tests ya existentes de la ruta). El reparto por nivel DCA de plan
(/contribution-split) NO se toca: zona excluida del encargo.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import corporate_actions as ca_route
from app.api.routes import knowledge_rag as rag_route
from app.models import CorporateAction
from app.api.routes import plan as plan_route


def run_async(coro):
    return asyncio.run(coro)


def _db():
    db = Mock()
    db.info = {"tenant_id": 1, "user_id": 2}
    return db


# --- corporate_actions -------------------------------------------------------


def test_ingesta_de_splits_pasa_por_el_servicio(monkeypatch):
    """POST /corporate-actions/sync: hilo + puente async, con todo doblado."""
    monkeypatch.setattr(
        ca_route, "SplitIngestionService", lambda: SimpleNamespace(
            sync_portfolio=lambda db: {"result": "ok"}
        )
    )
    monkeypatch.setattr(ca_route, "run_from_any_context", lambda x: x)

    def hilo_inline(fn):
        async def _coro():
            return fn()

        return _coro()

    monkeypatch.setattr(ca_route, "run_in_threadpool", hilo_inline)
    result = run_async(ca_route.sync_portfolio_splits(db=_db()))
    assert result == {"result": "ok"}


def test_apply_correcto_devuelve_el_payload(monkeypatch):
    servicio = Mock()
    # Modelo real, no SimpleNamespace: el gate de tenant/company se prueba de verdad.
    servicio.apply_action.return_value = CorporateAction(company_id=9)
    monkeypatch.setattr(ca_route, "CorporateActionService", lambda: servicio)
    monkeypatch.setattr(ca_route, "_payload", lambda action, ticker: {"t": ticker})
    db = _db()
    db.get.return_value = SimpleNamespace(ticker="ASTS")
    assert ca_route.apply_action(5, db=db) == {"t": "ASTS"}


def test_apply_invalido_es_400(monkeypatch):
    servicio = Mock()
    servicio.apply_action.side_effect = ValueError("ya aplicada")
    monkeypatch.setattr(ca_route, "CorporateActionService", lambda: servicio)
    with pytest.raises(HTTPException) as exc:
        ca_route.apply_action(5, db=_db())
    assert exc.value.status_code == 400


def test_delete_inexistente_es_404(monkeypatch):
    servicio = Mock()
    servicio.delete_action.return_value = False
    monkeypatch.setattr(ca_route, "CorporateActionService", lambda: servicio)
    with pytest.raises(HTTPException) as exc:
        ca_route.delete_action(5, db=_db())
    assert exc.value.status_code == 404


def test_delete_correcto_devuelve_none(monkeypatch):
    servicio = Mock()
    servicio.delete_action.return_value = True
    monkeypatch.setattr(ca_route, "CorporateActionService", lambda: servicio)
    assert ca_route.delete_action(5, db=_db()) is None


def test_delete_invalido_es_400(monkeypatch):
    servicio = Mock()
    servicio.delete_action.side_effect = ValueError("aplicada")
    monkeypatch.setattr(ca_route, "CorporateActionService", lambda: servicio)
    with pytest.raises(HTTPException) as exc:
        ca_route.delete_action(5, db=_db())
    assert exc.value.status_code == 400


# --- plan --------------------------------------------------------------------


def test_get_plan_con_plan_devuelve_metricas_con_id(monkeypatch):
    servicio = Mock()
    servicio.get_plan.return_value = SimpleNamespace(id=7)
    servicio.plan_metrics.return_value = {"months": 3}
    monkeypatch.setattr(plan_route, "InvestmentPlanService", lambda: servicio)
    assert plan_route.get_plan(db=_db()) == {"months": 3, "id": 7}


def test_lista_aportaciones_mapea_campos(monkeypatch):
    aportacion = SimpleNamespace(
        id=1, date=datetime(2026, 1, 15), amount=100.0, currency="EUR", note=None
    )
    servicio = Mock()
    servicio.list_contributions.return_value = [aportacion]
    monkeypatch.setattr(plan_route, "InvestmentPlanService", lambda: servicio)
    result = plan_route.list_contributions(limit=10, db=_db())
    assert result == [
        {"id": 1, "date": "2026-01-15T00:00:00", "amount": 100.0, "currency": "EUR", "note": None}
    ]


def test_borrar_aportacion_inexistente_es_404(monkeypatch):
    servicio = Mock()
    servicio.delete_contribution.return_value = False
    monkeypatch.setattr(plan_route, "InvestmentPlanService", lambda: servicio)
    with pytest.raises(HTTPException) as exc:
        plan_route.delete_contribution(5, db=_db())
    assert exc.value.status_code == 404


def test_borrar_aportacion_correcto_devuelve_none(monkeypatch):
    servicio = Mock()
    servicio.delete_contribution.return_value = True
    monkeypatch.setattr(plan_route, "InvestmentPlanService", lambda: servicio)
    assert plan_route.delete_contribution(5, db=_db()) is None


def test_drift_delega_en_el_servicio(monkeypatch):
    servicio = Mock()
    servicio.drift_analysis.return_value = {"drift": 0.0}
    monkeypatch.setattr(plan_route, "InvestmentPlanService", lambda: servicio)
    assert plan_route.drift_analysis(db=_db()) == {"drift": 0.0}


def test_proyeccion_de_ahorro_delega_en_el_contrato(monkeypatch):
    from app.services import savings_projection

    monkeypatch.setattr(
        savings_projection, "savings_contract", lambda db, **kw: {"ok": True}
    )
    result = plan_route.savings_projection(
        db=_db(), monthly=None, years=None, currency=None,
        annual_return=None, dividend_yield=0.03, inflation=0.02,
    )
    assert result == {"ok": True}


# --- knowledge_rag ------------------------------------------------------------


def test_list_sources_vacia(monkeypatch):
    monkeypatch.setattr(rag_route, "_enabled", lambda: Mock())
    db = _db()
    db.scalars.return_value = []
    assert rag_route.list_sources(db=db) == []


def test_get_source_inexistente_es_404(monkeypatch):
    monkeypatch.setattr(rag_route, "_enabled", lambda: Mock())
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        rag_route.get_source(5, db=db)
    assert exc.value.status_code == 404


def test_create_source_disco_lleno_es_507(monkeypatch):
    settings = Mock()
    monkeypatch.setattr(rag_route, "_enabled", lambda: settings)
    monkeypatch.setattr(rag_route, "resolve_inbox_path", lambda *a: "inbox/x.pdf")

    def sin_disco(*a):
        raise rag_route.InsufficientDisk("disco lleno")

    monkeypatch.setattr(rag_route, "check_disk", sin_disco)
    payload = rag_route.SourceCreate(
        path="x.pdf", title="t", source_uri="u", language="es", doc_type="memo"
    )
    with pytest.raises(HTTPException) as exc:
        rag_route.create_source(payload, db=_db())
    assert exc.value.status_code == 507


def test_processing_abandonado_sin_updated_at_no_es_abandono():
    source = SimpleNamespace(status="processing", updated_at=None)
    assert rag_route._processing_abandoned(source) is False


def test_processing_abandonado_fecha_naive_se_asume_utc():
    # now fijo: el abandono se evalua contra un reloj doblado, no el real.
    source = SimpleNamespace(status="processing", updated_at=datetime(2020, 1, 1))
    ahora = datetime(2026, 1, 1, tzinfo=UTC)
    assert rag_route._processing_abandoned(source, now=ahora) is True


def test_dispatch_sin_cola_es_503(monkeypatch):
    from app.workers import knowledge_rag_actors

    class ActorRoto:
        def send(self, *a, **kw):
            raise ConnectionError("broker caido")

    monkeypatch.setattr(knowledge_rag_actors, "ingest_knowledge_source", ActorRoto())
    marcado = []
    monkeypatch.setattr(rag_route, "mark_failed", lambda db, sid, msg: marcado.append(msg))
    source = SimpleNamespace(id=5)
    with pytest.raises(HTTPException) as exc:
        rag_route._dispatch(_db(), source)
    assert exc.value.status_code == 503
    assert "ConnectionError" in marcado[0]


def test_query_con_indice_roto_es_503(monkeypatch):
    settings = Mock()
    settings.knowledge_rag_query_translation = False
    monkeypatch.setattr(rag_route, "_enabled", lambda: settings)

    def hilo_roto(fn):
        async def _coro():
            raise ConnectionError("qdrant caido")

        return _coro()

    monkeypatch.setattr(rag_route, "run_in_threadpool", hilo_roto)
    payload = rag_route.QueryRequest(query="que es un moat")
    with pytest.raises(HTTPException) as exc:
        run_async(rag_route.query(payload, db=_db()))
    assert exc.value.status_code == 503
