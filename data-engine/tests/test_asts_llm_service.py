"""ASTS catalog LLM layer: real data only, honest 'sin datos', gated free model."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Tenant
from app.services import asts_llm_quota as quota
from app.services import asts_llm_service as service
from app.services.asts_catalog_service import persist_catalog
from app.services.connectors.celestrak_ast import SOURCE_URL


def row(cat_id, name, epoch):
    return {"norad_cat_id": cat_id, "object_name": name, "object_id": f"2026-0{cat_id % 90}",
            "epoch": epoch.isoformat(), "mean_motion": 15.39, "eccentricity": 0.0007,
            "inclination": 53.22, "ra_of_asc_node": 277.6, "arg_of_pericenter": 121.8,
            "mean_anomaly": 238.3, "bstar": 0.00018, "mean_motion_dot": 6.6e-5,
            "mean_motion_ddot": 0.0}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        session.add_all([Tenant(id=1, external_id="one"), Tenant(id=2, external_id="two")])
        session.commit()
    with factory() as session:
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def fresh_catalog(db, *, age=timedelta(hours=1)):
    now = datetime.now(UTC)
    fetched = now - age
    catalog = [row(53807, "BLUEWALKER-3", fetched - timedelta(hours=20)),
               row(61045, "SPACEMOBILE-003", fetched - timedelta(hours=5)),
               row(61046, "SPACEMOBILE-004", fetched - timedelta(hours=2))]
    persist_catalog(db, catalog, fetched)
    return fetched


def test_stale_snapshot_reports_sin_datos_without_llm(db, monkeypatch):
    fetched = fresh_catalog(db, age=timedelta(hours=31))
    monkeypatch.setenv("ASTS_LLM_ENABLED", "1")
    monkeypatch.setattr(quota, "_LOCAL", {})
    result = service.analyze_asts_catalog(db)
    assert result["status"] == "sin datos"
    assert result["analysis"] is None and result["mode"] is None
    assert result["stale_snapshot_at"] == fetched.isoformat()
    assert result["llm_quota"] is None  # ni reserva sin datos frescos
    assert "30 h" in result["note"]
    assert result["source"]["url"] == SOURCE_URL  # igualdad exacta, no substring


def test_fresh_catalog_deterministic_when_flag_off(db, monkeypatch):
    fetched = fresh_catalog(db)
    monkeypatch.delenv("ASTS_LLM_ENABLED", raising=False)
    result = service.analyze_asts_catalog(db)
    assert result["status"] == "disponible" and result["mode"] == "determinista"
    assert result["note"] == "Análisis LLM desactivado por configuración."
    assert result["llm_quota"] is None
    assert result["analysis"]["llm_interpretation"] is None
    agg = result["analysis"]["aggregates"]
    assert agg["count"] == 3
    assert agg["families"] == {"BLUEWALKER": 1, "SPACEMOBILE": 2}
    assert agg["epoch_max"] in result["analysis"]["summary"]
    assert fetched.isoformat() in result["analysis"]["summary"]
    assert "CelesTrak" in result["analysis"]["summary"]
    # solo datos reales: cada observación cita valores del catálogo
    for obs in result["analysis"]["observations"]:
        assert any(token in obs["text"] for token in ("53.22", "15.39", "SPACEMOBILE", "epoch", "Época"))


def test_llm_failure_falls_back_honestly(db, monkeypatch):
    fresh_catalog(db)
    monkeypatch.setenv("ASTS_LLM_ENABLED", "1")
    monkeypatch.setattr(service, "reserve_llm_call", lambda *_args: {
        "allowed": True, "minute_used": 1, "minute_limit": 2,
        "day_used": 1, "day_limit": 30, "reset": "UTC calendar minute/day"})
    def boom(_payload, **_kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr(service, "_analyze_with_llm", boom)
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista"
    assert result["note"] == "Análisis LLM no disponible; se usa el resumen determinista."
    assert result["analysis"]["aggregates"]["count"] == 3


def stub_llm(monkeypatch, summary, observations=()):
    monkeypatch.setenv("ASTS_LLM_ENABLED", "1")
    monkeypatch.setattr(service, "reserve_llm_call", lambda *_args: {
        "allowed": True, "minute_used": 1, "minute_limit": 2,
        "day_used": 1, "day_limit": 30, "reset": "UTC calendar minute/day"})
    async def fake(_payload, **_kwargs):
        return service.AstsAnalysis(
            summary=summary,
            observations=[service.Observation(text=o) for o in observations]), object()
    monkeypatch.setattr(service, "_analyze_with_llm", fake)


def test_llm_success_marks_mode_and_keeps_aggregates(db, monkeypatch):
    fetched = fresh_catalog(db)
    stub_llm(monkeypatch,
             f"Catálogo CelesTrak descargado el {fetched.isoformat()}: 3 objetos.",
             ["Inclinación uniforme de 53.22°."])
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "llm"
    assert result["llm_input"] == "completo"
    # el resumen canonico es SIEMPRE el determinista, tambien en modo llm
    assert result["analysis"]["summary"].startswith("Catálogo CelesTrak del grupo AST descargado el")
    assert result["analysis"]["aggregates"]["count"] == 3  # datos reales siempre presentes
    interp = result["analysis"]["llm_interpretation"]
    assert interp["summary"].startswith("Catálogo CelesTrak descargado el")
    assert "no verificada" in interp["disclaimer"]
    assert result["llm_quota"]["day_limit"] == 30


def test_llm_rounded_values_are_accepted(db, monkeypatch):
    fetched = fresh_catalog(db)
    # 53.2 es un redondeo legitimo de la inclinacion real 53.22
    stub_llm(monkeypatch,
             f"Catálogo CelesTrak descargado el {fetched.isoformat()[:10]}: 3 objetos.",
             ["Inclinación de 53.2° en todo el catálogo."])
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "llm"
    assert result["analysis"]["llm_interpretation"]["observations"][0]["text"].startswith("Inclinación de 53.2")


def test_llm_invented_number_falls_back_to_deterministic(db, monkeypatch):
    fetched = fresh_catalog(db)
    stub_llm(monkeypatch,
             f"Catálogo CelesTrak descargado el {fetched.isoformat()[:10]}: 200 satélites operativos.")
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista"
    assert result["note"] == ("Interpretación generativa descartada: incluía datos "
                              "no contrastados con el catálogo.")
    assert result["analysis"]["llm_interpretation"] is None
    # el canonico sigue siendo el determinista con los valores reales
    assert result["analysis"]["summary"].startswith("Catálogo CelesTrak del grupo AST descargado el")
    assert result["analysis"]["aggregates"]["count"] == 3


def test_llm_invented_satellite_name_falls_back(db, monkeypatch):
    fetched = fresh_catalog(db)
    stub_llm(monkeypatch,
             f"Catálogo CelesTrak descargado el {fetched.isoformat()[:10]}: 3 objetos.",
             ["SPACEMOBILE-999 lidera la constelación."])
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista"
    assert "no contrastados" in result["note"]
    assert result["analysis"]["llm_interpretation"] is None


def test_llm_generic_summary_without_source_or_date_falls_back(db, monkeypatch):
    fresh_catalog(db)
    stub_llm(monkeypatch, "Resumen general del catálogo de satélites.")
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista"
    assert "no contrastados" in result["note"]
    assert result["analysis"]["llm_interpretation"] is None


def test_quota_cap_falls_back_honestly(db, monkeypatch):
    fresh_catalog(db)
    monkeypatch.setenv("ASTS_LLM_ENABLED", "1")
    monkeypatch.setattr(service, "reserve_llm_call", lambda *_args: {
        "allowed": False, "minute_used": 2, "minute_limit": 2,
        "day_used": 30, "day_limit": 30, "reset": "UTC calendar minute/day"})
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista"
    assert result["note"] == "Análisis LLM no disponible: tope alcanzado."


def test_llm_input_aggregated_for_large_catalog(db, monkeypatch):
    now = datetime.now(UTC)
    fetched = now - timedelta(hours=1)
    catalog = [row(60000 + i, f"SPACEMOBILE-{i:03d}", fetched - timedelta(minutes=i))
               for i in range(200)]
    persist_catalog(db, catalog, fetched)
    payload, mode = service._llm_payload(catalog, service._aggregates(catalog), fetched.isoformat())
    assert mode == "agregado"
    assert "agregados" in payload and "satelites" not in payload
    assert "No inventes filas" in payload


def test_quota_is_tenant_scoped_and_reports_limit(monkeypatch):
    class Config:
        is_production = False
        asts_llm_calls_per_minute = 1
        asts_llm_calls_per_day = 3

    config = Config()
    monkeypatch.setattr(quota, "_LOCAL", {})
    assert quota.reserve_llm_call("tenant-one", config)["allowed"] is True
    exceeded = quota.reserve_llm_call("tenant-one", config)
    assert exceeded["allowed"] is False and exceeded["minute_limit"] == 1
    assert quota.reserve_llm_call("tenant-two", config)["allowed"] is True
    with pytest.raises(RuntimeError):
        quota.reserve_llm_call(None, config)


def test_llm_request_pins_free_model_even_with_paid_override(monkeypatch):
    class Router:
        def resolve(self, request):
            return "paid-model-x"

    class Provider:
        name = "test"
        model_router = Router()

        async def complete(self, request):  # pragma: no cover - must never run
            raise AssertionError("should not call the paid model")

    monkeypatch.setattr(service, "create_llm_provider", lambda: Provider())
    with pytest.raises(RuntimeError, match="owner-approved"):
        asyncio.run(service._analyze_with_llm("payload"))


def test_llm_request_uses_registered_prompt_and_traces_it(monkeypatch):
    from app.services import prompt_registry

    seen = []

    class Router:
        def resolve(self, request):
            seen.append(request)
            return "paid-model-x"  # corta antes de llamar al proveedor

    class Provider:
        name = "test"
        model_router = Router()

    monkeypatch.setattr(service, "create_llm_provider", lambda: Provider())
    with pytest.raises(RuntimeError, match="owner-approved"):
        asyncio.run(service._analyze_with_llm("payload"))
    resolved = prompt_registry.get_prompt("asts_llm_service", allow_remote=False)
    assert seen[0].messages[0].content == resolved.text
    assert seen[0].metadata == resolved.trace_metadata()


def test_requires_tenant(db):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        with pytest.raises(ValueError, match="Tenant"):
            service.analyze_asts_catalog(session)
    engine.dispose()


def scripted_llm(monkeypatch, texts, *, db=None, budget_allowed=None):
    import json
    from types import SimpleNamespace

    from app.llm import LLMResponse, Message, Usage

    calls = []
    reservations = []
    monkeypatch.setenv("ASTS_LLM_ENABLED", "1")

    def reserve(tenant_id, _settings):
        reservations.append(tenant_id)
        return {"allowed": True, "minute_used": len(reservations), "minute_limit": 4,
                "day_used": len(reservations), "day_limit": 100}

    class Provider:
        name = "test"
        model_router = SimpleNamespace(resolve=lambda request: request.model)

        async def complete(self, request):
            if db is not None:
                assert not db.in_transaction()
                pool = db.get_bind().pool
                if hasattr(pool, "checkedout"):
                    assert pool.checkedout() == 0
            calls.append(request)
            value = texts[len(calls) - 1]
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
            return LLMResponse(message=Message("assistant", text), model="space-bunny-free",
                               provider="test", usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30))

    monkeypatch.setattr(service, "reserve_llm_call", reserve)
    monkeypatch.setattr(service, "create_llm_provider", lambda: Provider())
    if budget_allowed is not None:
        monkeypatch.setattr(service.BudgetController, "can_spend", budget_allowed)
    return calls, reservations


def good_analysis(fetched):
    return {"summary": f"Catálogo CelesTrak descargado el {fetched.isoformat()[:10]}: 3 objetos.",
            "observations": [{"text": "Inclinación uniforme de 53.22°."}]}


def usage_rows(db):
    from sqlalchemy import select

    from app.models import BudgetUsage

    return list(db.scalars(select(BudgetUsage).order_by(BudgetUsage.id)).all())


@pytest.mark.parametrize("bad_text", ["中文模型", "The catalog is available and the satellites are active.",
                                     "La inclinación?depende del catálogo."])
def test_guard_retries_once_and_records_both_responses(db, monkeypatch, bad_text):
    fetched = fresh_catalog(db)
    bad = good_analysis(fetched)
    bad["observations"] = [{"text": bad_text}]
    calls, reservations = scripted_llm(monkeypatch, [bad, good_analysis(fetched)], db=db)
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "llm"
    assert result["analysis"]["llm_interpretation"]["summary"] == good_analysis(fetched)["summary"]
    assert len(calls) == 2 and reservations == [1, 1]
    assert "REINTENTO" in calls[1].messages[0].content
    assert result["llm_quota"]["day_used"] == 2
    rows = usage_rows(db)
    assert len(rows) == 2
    assert all(r.tenant_id == 1 and r.workflow == "asts_catalog_analysis" for r in rows)
    assert all(r.token_count == 30 for r in rows)
    expected = service.BudgetController.estimate_cost_eur("space-bunny-free", 10, 20)
    assert all(float(r.cost_eur) == pytest.approx(expected) for r in rows)


def test_double_guard_rejection_stays_deterministic_and_records_cost(db, monkeypatch):
    fresh_catalog(db)
    calls, reservations = scripted_llm(monkeypatch, ["中文模型", "中文模型"])
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista" and len(calls) == 2
    assert reservations == [1, 1] and len(usage_rows(db)) == 2
    assert result["analysis"]["llm_interpretation"] is None
    assert "resumen determinista" in result["note"]


def test_guard_retry_reserves_quota_and_stops_when_denied(db, monkeypatch):
    fetched = fresh_catalog(db)
    calls, reservations = scripted_llm(monkeypatch, ["中文模型", good_analysis(fetched)])

    def reserve(tenant_id, _settings):
        reservations.append(tenant_id)
        return {"allowed": len(reservations) == 1, "day_used": 1, "day_limit": 1}

    monkeypatch.setattr(service, "reserve_llm_call", reserve)
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista" and len(calls) == 1
    assert reservations == [1, 1] and len(usage_rows(db)) == 1
    assert result["llm_quota"]["allowed"] is False


def test_budget_exhausted_before_first_call_is_optional_fallback(db, monkeypatch):
    fresh_catalog(db)
    budget = service.BudgetController()
    budget.record(db, "space-bunny-free", "other", budget.settings.llm_daily_cap_eur, 1)
    calls, reservations = scripted_llm(monkeypatch, [])
    result = service.analyze_asts_catalog(db)
    assert result["status"] == "disponible" and result["mode"] == "determinista"
    assert result["analysis"]["llm_interpretation"] is None
    assert not calls and not reservations and result["llm_quota"] is None
    assert not db.in_transaction()


def test_budget_exhausted_before_retry_records_first_and_stops(db, monkeypatch):
    fresh_catalog(db)
    checks = []

    def allowed(_budget, usage_db, _estimate):
        checks.append(usage_db.info["tenant_id"])
        # Real SELECT abre una transaccion: comprobar que se libera antes del LLM.
        _budget.current_usage(usage_db)
        return len(checks) == 1

    calls, reservations = scripted_llm(monkeypatch, ["中文模型"], db=db, budget_allowed=allowed)
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista" and len(calls) == 1
    assert checks == [1, 1] and reservations == [1] and len(usage_rows(db)) == 1


@pytest.mark.parametrize("text", ["not json", '{"observations": []}'])
def test_invalid_json_or_schema_is_recorded_but_never_published(db, monkeypatch, text):
    fresh_catalog(db)
    calls, reservations = scripted_llm(monkeypatch, [text])
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista" and result["analysis"]["llm_interpretation"] is None
    assert len(calls) == 1 and reservations == [1] and len(usage_rows(db)) == 1


def test_verified_values_check_still_runs_after_guard(db, monkeypatch):
    fetched = fresh_catalog(db)
    value = good_analysis(fetched)
    value["observations"] = [{"text": "Inclinación de 99.99°."}]
    calls, reservations = scripted_llm(monkeypatch, [value])
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista" and "no contrastados" in result["note"]
    assert len(calls) == 1 and reservations == [1] and len(usage_rows(db)) == 1


@pytest.mark.parametrize("active_loop", [False, True])
def test_releases_connections_and_records_in_separate_sessions(tmp_path, monkeypatch, active_loop):
    import threading

    engine = create_engine(f"sqlite:///{tmp_path / 'asts.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        session.info["tenant_id"] = 1
        session.add(Tenant(id=1, external_id="one"))
        session.commit()
        fetched = fresh_catalog(session)
        calls, reservations = scripted_llm(monkeypatch, ["中文模型", good_analysis(fetched)], db=session)
        owner_thread = threading.get_ident()
        real_record = service.BudgetController.record
        callback_threads = []

        def record(budget, usage_db, *args, **kwargs):
            assert usage_db is not session
            callback_threads.append(threading.get_ident())
            real_record(budget, usage_db, *args, **kwargs)

        monkeypatch.setattr(service.BudgetController, "record", record)
        if active_loop:
            async def run():
                return service.analyze_asts_catalog(session)
            result = asyncio.run(run())
        else:
            result = service.analyze_asts_catalog(session)
        assert result["mode"] == "llm" and len(calls) == 2 and reservations == [1, 1]
        assert all((tid != owner_thread) == active_loop for tid in callback_threads)
        assert not session.in_transaction() and engine.pool.checkedout() == 0
        assert len(usage_rows(session)) == 2
    engine.dispose()


def test_catalog_snapshot_is_copied_before_commit(db, monkeypatch):
    fetched = fresh_catalog(db)
    snapshot = service.read_catalog(db)
    monkeypatch.setattr(service, "read_catalog", lambda _db: snapshot)
    real_commit = db.commit

    def commit():
        snapshot["satellites"][0]["inclination"] = 99.99
        real_commit()

    monkeypatch.setattr(db, "commit", commit)
    scripted_llm(monkeypatch, [good_analysis(fetched)])
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "llm"
    assert result["analysis"]["aggregates"]["inclination_deg_max"] == 53.22


def test_other_tenants_budget_does_not_block_asts(db, monkeypatch):
    from app.models import BudgetUsage

    fetched = fresh_catalog(db)
    budget = service.BudgetController()
    with sessionmaker(db.get_bind())() as other:
        other.info["tenant_id"] = 2
        budget.record(other, "space-bunny-free", "other", budget.settings.llm_daily_cap_eur, 1)
    scripted_llm(monkeypatch, [good_analysis(fetched)])
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "llm"
    rows = usage_rows(db)
    assert len(rows) == 1 and rows[0].tenant_id == 1
    with sessionmaker(db.get_bind())() as other:
        other.info["tenant_id"] = 2
        assert other.query(BudgetUsage).count() == 1


def test_upstream_error_does_not_retry_or_record_missing_response(db, monkeypatch):
    from types import SimpleNamespace

    fresh_catalog(db)
    calls, reservations = scripted_llm(monkeypatch, [])

    class Provider:
        name = "test"
        model_router = SimpleNamespace(resolve=lambda request: request.model)

        async def complete(self, request):
            calls.append(request)
            raise RuntimeError("provider down")

    monkeypatch.setattr(service, "create_llm_provider", lambda: Provider())
    result = service.analyze_asts_catalog(db)
    assert result["mode"] == "determinista" and len(calls) == 1 and reservations == [1]
    assert not usage_rows(db)
