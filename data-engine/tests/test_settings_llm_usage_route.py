"""Panel /settings/llm/usage y raiz /settings: cuotas, breaker y fuga entre tenants.

Sobre main (55.1%) faltaban el endpoint de uso LLM entero, el saneado de la
cuota Go, los contadores propios por tenant y la raiz de /settings. Los
proveedores se sustituyen por dobles; aqui se fija el contrato de la ruta
(solo contadores del PROPIO tenant, estados ok/limited/off, nunca claves).
"""
from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import settings as mod
from app.api.routes.settings import (
    _require_tenant,
    _sanitize_go_quota,
    _tenant_usage_today,
    get_llm_usage,
    maf_version,
    settings,
)
from app.models.entities import Base, BudgetUsage, Tenant


@pytest.fixture
def db():
    # check_same_thread=False: los handlers IBKR sueltan la sesion al pool
    # de hilos (run_in_threadpool) y SQLite por defecto ata la conexion al hilo.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        db.info["tenant_id"] = 1
        db.add(Tenant(external_id="t1", name="T1"))
        db.commit()
        yield db
    engine.dispose()


def _app_settings(**overrides):
    base = {
        "chat_go_subscription_enabled": False,
        "chat_go_subscription_base_url": "https://go.example",
        "opencode_go_api_key": "",
        "opencode_go_model": "go-model",
        "opencode_go_session": "",
        "opencode_free_chat_fallback_active": True,
        "opencode_free_model": "free-model",
        "gemini_chat_fallback_active": False,
        "app_env": "test",
        "fmp_api_key": "",
        "ibkr_flex_token": "",
        "ibkr_flex_query_id": "",
        "fred_api_key": "",
        "langfuse_enabled": False,
        "qdrant_url": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# --- helpers ------------------------------------------------------------


def test_require_tenant_sin_contexto_es_401(db):
    db.info.pop("tenant_id", None)
    with pytest.raises(HTTPException) as exc:
        _require_tenant(db)
    assert exc.value.status_code == 401


def test_require_tenant_devuelve_el_id(db):
    assert _require_tenant(db) == 1


def test_maf_version_con_paquete_instalado(monkeypatch):
    monkeypatch.setattr(mod, "_pkg_version", lambda name: "1.2.3")
    assert maf_version() == "agent-framework-core==1.2.3"


def test_maf_version_sin_paquete_es_unknown(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    def boom(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(mod, "_pkg_version", boom)
    assert maf_version() == "agent-framework-core==unknown"


def test_sanitize_go_quota_rechaza_formas_raras():
    assert _sanitize_go_quota(None) is None
    assert _sanitize_go_quota("texto") is None
    assert _sanitize_go_quota({"usage": "no-dict"}) is None
    assert _sanitize_go_quota({"usage": {}}) == {}


def test_sanitize_go_quota_filtra_campos_invalidos():
    raw = {
        "usage": {
            "rolling": {
                "percent": 42.5,
                "status": "ok",
                "resetsAt": "2026-11-09T00:00:00Z",
                "extra": "se pierde",
            },
            "weekly": {"percent": "mucho"},  # percent no numerico: fuera
            "monthly": {"percent": True},  # bool no cuenta como numero
            "quarterly": {"percent": 1},  # ventana desconocida: fuera
            "bad": "no-dict",
        }
    }
    clean = _sanitize_go_quota(raw)
    assert clean is not None
    assert clean["rolling"] == {
        "percent": 42.5,
        "status": "ok",
        "resetsAt": "2026-11-09T00:00:00Z",
    }
    assert clean["weekly"] == {}
    assert clean["monthly"] == {}
    assert "quarterly" not in clean


def test_sanitize_go_quota_percent_no_finito_fuera():
    raw = {"usage": {"rolling": {"percent": math.inf}}}
    assert _sanitize_go_quota(raw) == {"rolling": {}}


# --- contadores propios por tenant --------------------------------------


def test_tenant_usage_today_solo_cuenta_lo_propio(db):
    today = date.today()
    db.add_all(
        [
            BudgetUsage(tenant_id=1, usage_date=today, model="go-model", workflow="chat", token_count=10),
            BudgetUsage(tenant_id=1, usage_date=today, model="go-model", workflow="chat", token_count=5),
            # Otro modelo: fuera del filtro.
            BudgetUsage(tenant_id=1, usage_date=today, model="otro", workflow="chat", token_count=99),

            # Otro dia: fuera.
            BudgetUsage(tenant_id=1, usage_date=today - timedelta(days=1), model="go-model", workflow="chat", token_count=99),
        ]
    )
    db.commit()
    # Otro tenant: NUNCA se agrega (fuga entre clientes). El guard de
    # sesion exige escribirlo con SU contexto de tenant.
    db.info["tenant_id"] = 2
    db.add(BudgetUsage(tenant_id=2, usage_date=today, model="go-model", workflow="chat", token_count=99))
    db.commit()
    db.info["tenant_id"] = 1
    out = _tenant_usage_today(db, 1, ["go-model"])
    assert out == {"date": today.isoformat(), "calls": 2, "tokens": 15}


# --- /settings/llm (GET/PUT) y /llm/test ----------------------------------


def test_get_llm_settings_delega_en_la_vista(db, monkeypatch):
    monkeypatch.setattr(mod, "settings_view", lambda db_, s: {"view": True})
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    assert mod.get_llm_settings(db=db) == {"view": True}


def _update_payload(**overrides):
    base = {"provider": "openai", "model": "gpt-x"}
    base.update(overrides)
    return mod.LLMSettingsUpdateRequest(**base)


def test_update_llm_api_key_sin_cifrado_es_503(db, monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(mod, "encryption_available", lambda s: False)
    with pytest.raises(HTTPException) as exc:
        mod.update_llm_settings(_update_payload(api_key="sk-1"), db=db)
    assert exc.value.status_code == 503


def test_update_llm_error_de_validacion_es_422_con_rollback(db, monkeypatch):
    rolled_back = []
    monkeypatch.setattr(db, "rollback", lambda: rolled_back.append(True))
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())

    def boom(db_, update, s):
        raise ValueError("proveedor no soportado")

    monkeypatch.setattr(mod, "save_tenant_settings", boom)
    with pytest.raises(HTTPException) as exc:
        mod.update_llm_settings(_update_payload(), db=db)
    assert exc.value.status_code == 422
    assert rolled_back == [True]


def test_update_llm_cifrado_roto_es_503(db, monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())

    def boom(db_, update, s):
        raise mod.LLMSettingsCryptoError("sin claves")

    monkeypatch.setattr(mod, "save_tenant_settings", boom)
    monkeypatch.setattr(db, "rollback", lambda: None)
    with pytest.raises(HTTPException) as exc:
        mod.update_llm_settings(_update_payload(), db=db)
    assert exc.value.status_code == 503


def test_update_llm_camino_feliz_devuelve_la_vista(db, monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(mod, "save_tenant_settings", lambda db_, update, s: None)
    monkeypatch.setattr(mod, "settings_view", lambda db_, s: {"saved": True})
    assert mod.update_llm_settings(_update_payload(), db=db) == {"saved": True}


def test_llm_test_sin_clave_ni_guardada_es_422(db, monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(mod, "stored_api_key", lambda db_, s, **kw: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.test_llm_settings(mod.LLMTestRequest(provider="openai", model="gpt-x"), db=db))
    assert exc.value.status_code == 422


def test_llm_test_clave_guardada_de_otro_endpoint_es_422(db, monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())

    def boom(db_, s, **kw):
        raise mod.StoredKeyEndpointMismatch("la clave es de otro endpoint")

    monkeypatch.setattr(mod, "stored_api_key", boom)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.test_llm_settings(mod.LLMTestRequest(provider="openai", model="gpt-x"), db=db))
    assert exc.value.status_code == 422


def test_llm_test_sonda_fallida_es_422(db, monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())

    async def boom(**kw):
        raise ValueError("credenciales rechazadas")

    monkeypatch.setattr(mod, "probe_connection", boom)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            mod.test_llm_settings(
                mod.LLMTestRequest(provider="openai", model="gpt-x", api_key="sk-1"), db=db
            )
        )
    assert exc.value.status_code == 422


def test_llm_test_camino_feliz(db, monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())

    async def fake_probe(**kw):
        return {"ok": True, "model": kw["model"]}

    monkeypatch.setattr(mod, "probe_connection", fake_probe)
    out = asyncio.run(
        mod.test_llm_settings(
            mod.LLMTestRequest(provider="openai", model="gpt-x", api_key="sk-1"), db=db
        )
    )
    assert out == {"ok": True, "model": "gpt-x"}


# --- /settings/llm/usage -------------------------------------------------


def test_llm_usage_tenant_byok_corta_en_seco(db, monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(
        mod,
        "current_tenant_llm_config",
        lambda: SimpleNamespace(provider="openai", model="gpt", has_api_key=True),
    )
    out = asyncio.run(get_llm_usage(db=db))
    assert out["source"] == "tenant"
    assert out["legs"] == []
    assert out["message"] == "tenant_byok"


def _usage_platform(monkeypatch, db, *, snapshot=(), go_quota=None, **settings_overrides):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings(**settings_overrides))
    monkeypatch.setattr(mod, "current_tenant_llm_config", lambda: None)
    monkeypatch.setattr(mod, "breaker_snapshot", lambda: list(snapshot))

    async def fake_fetch(base_url, key, *, session=None):
        return go_quota

    monkeypatch.setattr(mod, "fetch_go_usage", fake_fetch)
    return asyncio.run(get_llm_usage(db=db))


def test_llm_usage_plataforma_sin_go_ni_gemini(db, monkeypatch):
    out = _usage_platform(monkeypatch, db)
    assert out["source"] == "platform"
    legs = {leg["id"]: leg for leg in out["legs"]}
    assert legs["opencode-go"]["active"] is False
    assert legs["opencode-go"]["state"] == "off"
    assert legs["opencode-go"]["estimated"] is False
    assert legs["opencode-free"]["state"] == "ok"
    assert legs["opencode-free"]["estimated"] is True
    assert legs["opencode-free"]["today"]["calls"] == 0
    assert legs["gemini"]["state"] == "off"
    assert legs["gemini"]["published_limits"]


def test_llm_usage_go_activo_con_cuota_real(db, monkeypatch):
    raw = {"usage": {"weekly": {"percent": 40.0, "status": "ok"}}}
    out = _usage_platform(
        monkeypatch,
        db,
        go_quota=raw,
        chat_go_subscription_enabled=True,
        opencode_go_api_key="k",
    )
    go = {leg["id"]: leg for leg in out["legs"]}["opencode-go"]
    assert go["active"] is True
    assert go["state"] == "ok"
    assert go["quota"] == {"weekly": {"percent": 40.0, "status": "ok"}}
    assert go["today"]["calls"] == 0


def test_llm_usage_go_limitado_por_cuota_semanal(db, monkeypatch):
    out = _usage_platform(
        monkeypatch,
        db,
        go_quota={"usage": {"weekly": {"percent": 100}}},
        chat_go_subscription_enabled=True,
        opencode_go_api_key="k",
    )
    go = {leg["id"]: leg for leg in out["legs"]}["opencode-go"]
    assert go["state"] == "limited"


def test_llm_usage_breaker_abierto_marca_limited_until(db, monkeypatch):
    until = (datetime.now(UTC) + timedelta(hours=1)).timestamp()
    out = _usage_platform(
        monkeypatch,
        db,
        snapshot=[
            {"provider": "opencode-free", "until": until},
            {"provider": "gemini", "until": until},
        ],
        gemini_chat_fallback_active=True,
    )
    legs = {leg["id"]: leg for leg in out["legs"]}
    assert legs["opencode-free"]["state"] == "limited"
    assert legs["opencode-free"]["limited_until"] is not None
    assert legs["gemini"]["state"] == "limited"
    # Go inactivo sigue off aunque no tenga breaker.
    assert legs["opencode-go"]["state"] == "off"


# --- /settings raiz -------------------------------------------------------


def _settings_root_mocks(monkeypatch, provider, tenant):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(mod, "create_llm_provider", lambda s: provider)
    monkeypatch.setattr(mod, "current_tenant_llm_config", lambda: tenant)
    monkeypatch.setattr(
        mod,
        "BudgetController",
        lambda: SimpleNamespace(current_usage=lambda db, admin=False: {"admin": admin}),
    )
    monkeypatch.setattr(mod, "route_table", lambda: [])
    monkeypatch.setattr(mod, "credit_status", lambda: {"ok": True})


def test_settings_raiz_plataforma_con_cascada(db, monkeypatch):
    provider = SimpleNamespace(name="cascade", member_names=["go", "free"])
    _settings_root_mocks(monkeypatch, provider, None)
    out = settings(db=db)
    assert out["llm"]["configured"] is True
    assert out["llm"]["members"] == ["go", "free"]
    assert out["llm"]["model"] is None  # el modelo depende del miembro
    assert out["connectors"]["ibkr"] is False
    assert "api_key" not in str(out["llm"])  # nunca claves por la API


def test_settings_raiz_proveedor_desactivado_declara_razon(db, monkeypatch):
    provider = SimpleNamespace(name="disabled", reason="sin clave", member_names=None)
    _settings_root_mocks(monkeypatch, provider, None)
    out = settings(db=db)
    assert out["llm"]["configured"] is False
    assert out["llm"]["reason"] == "sin clave"
    assert out["llm"]["model"] is None


def test_settings_raiz_tenant_byok_expone_solo_last4(db, monkeypatch):
    provider = SimpleNamespace(name="disabled", reason="sin clave", member_names=None)
    tenant = SimpleNamespace(
        provider="openai", model="gpt-x", has_api_key=True, api_key_last4="1234"
    )
    _settings_root_mocks(monkeypatch, provider, tenant)
    out = settings(db=db)
    assert out["llm"]["source"] == "tenant"
    assert out["llm"]["billing_scope"] == "tenant"
    assert out["llm"]["api_key_last4"] == "1234"
    assert out["llm"]["reason"] == "sin clave"


# --- /settings/ibkr ------------------------------------------------------


@pytest.fixture
def ibkr(monkeypatch):
    import app.services.ibkr_connection_service as ibkr_mod

    return ibkr_mod


def _ibkr_payload(**overrides):
    base = {"token": "tok", "query_id": "q1", "account_id": "U123"}
    base.update(overrides)
    return mod.IBKRConnectRequest(**base)


def test_get_ibkr_connection_delega_en_la_vista(db, monkeypatch, ibkr):
    monkeypatch.setattr(ibkr, "view", lambda db_: {"connected": False})
    assert mod.get_ibkr_connection(db=db) == {"connected": False}


def test_connect_ibkr_sin_cifrado_es_503(db, monkeypatch, ibkr):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(mod, "encryption_available", lambda s: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.connect_ibkr(_ibkr_payload(), db=db))
    assert exc.value.status_code == 503


def test_connect_ibkr_camino_feliz(db, monkeypatch, ibkr):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(mod, "encryption_available", lambda s: True)
    monkeypatch.setattr(ibkr, "validate_input", lambda t, q, a: (t, q, a))

    async def fake_download(token, query_id):
        return "<xml/>"

    monkeypatch.setattr(ibkr, "download", fake_download)
    monkeypatch.setattr(ibkr, "check_report", lambda xml, account: date(2026, 11, 8))
    monkeypatch.setattr(
        ibkr, "save_connection", lambda db_, s, **kw: {"connected": True, "account": kw["account_id"]}
    )
    out = asyncio.run(mod.connect_ibkr(_ibkr_payload(), db=db))
    assert out == {"connected": True, "account": "U123"}


def test_connect_ibkr_sincronizacion_ocupada_es_409(db, monkeypatch, ibkr):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(mod, "encryption_available", lambda s: True)
    monkeypatch.setattr(ibkr, "validate_input", lambda t, q, a: (t, q, a))

    async def busy(token, query_id):
        raise ibkr.SyncBusy("sync en curso")

    monkeypatch.setattr(ibkr, "download", busy)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.connect_ibkr(_ibkr_payload(), db=db))
    assert exc.value.status_code == 409


def test_connect_ibkr_error_de_conexion_es_422(db, monkeypatch, ibkr):
    monkeypatch.setattr(mod, "get_settings", lambda: _app_settings())
    monkeypatch.setattr(mod, "encryption_available", lambda s: True)
    monkeypatch.setattr(ibkr, "validate_input", lambda t, q, a: (t, q, a))

    async def boom(token, query_id):
        raise ibkr.ConnectionError("IBKR no responde")

    monkeypatch.setattr(ibkr, "download", boom)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.connect_ibkr(_ibkr_payload(), db=db))
    assert exc.value.status_code == 422
    assert "IBKR no responde" in exc.value.detail


def test_disconnect_ibkr_camino_feliz(db, monkeypatch, ibkr):
    monkeypatch.setattr(ibkr, "disconnect", lambda db_: {"disconnected": True})
    assert mod.disconnect_ibkr(db=db) == {"disconnected": True}


def test_disconnect_ibkr_ocupado_es_409(db, monkeypatch, ibkr):
    def busy(db_):
        raise ibkr.SyncBusy("sync en curso")

    monkeypatch.setattr(ibkr, "disconnect", busy)
    monkeypatch.setattr(db, "rollback", lambda: None)
    with pytest.raises(HTTPException) as exc:
        mod.disconnect_ibkr(db=db)
    assert exc.value.status_code == 409


class _FakeLease:
    def __init__(self, error=None):
        self.error = error
        self.exited = False

    def __enter__(self):
        if self.error:
            raise self.error
        return self

    def __exit__(self, *args):
        self.exited = True


def _sync_mocks(monkeypatch, ibkr, lease, *, import_result=None, import_error=None):
    monkeypatch.setattr(ibkr, "sync_lease", lambda db_: lease)
    monkeypatch.setattr(ibkr, "credentials", lambda db_, s: ("t", "q", "U123", 7))
    monkeypatch.setattr(ibkr, "start_receipt", lambda db_, **kw: 33)

    async def fake_download(token, query_id):
        return "<xml/>"

    monkeypatch.setattr(ibkr, "download", fake_download)
    if import_error:
        def boom(db_, xml, account, revision, *, receipt_id=None):
            raise import_error
        monkeypatch.setattr(ibkr, "import_report", boom)
    else:
        monkeypatch.setattr(
            ibkr, "import_report", lambda db_, xml, account, revision, **kw: import_result
        )


def test_sync_ibkr_camino_feliz_cierra_el_lease(db, monkeypatch, ibkr):
    lease = _FakeLease()
    _sync_mocks(monkeypatch, ibkr, lease, import_result={"imported": 3})
    out = asyncio.run(mod.sync_ibkr_connection(db=db))
    assert out == {"imported": 3}
    assert lease.exited is True


def test_sync_ibkr_lease_ocupado_es_409(db, monkeypatch, ibkr):
    lease = _FakeLease(error=None)
    busy = ibkr.SyncBusy("sync en curso")
    lease.error = busy
    _sync_mocks(monkeypatch, ibkr, lease, import_result={})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.sync_ibkr_connection(db=db))
    assert exc.value.status_code == 409


def test_sync_ibkr_fallo_registra_y_conserva_datos(db, monkeypatch, ibkr):
    lease = _FakeLease()
    _sync_mocks(monkeypatch, ibkr, lease, import_error=RuntimeError("xml corrupto"))
    fallos = []
    monkeypatch.setattr(
        ibkr,
        "record_failure",
        lambda db_, **kw: fallos.append(kw),
    )
    monkeypatch.setattr(ibkr, "error_kind", lambda exc: "unknown")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.sync_ibkr_connection(db=db))
    assert exc.value.status_code == 422
    assert "Conservamos los datos anteriores" in exc.value.detail
    assert fallos and fallos[0]["revision"] == 7 and fallos[0]["receipt_id"] == 33
    assert lease.exited is True
