"""get_db de app/core/database.py llamado como funcion generadora, sin FastAPI.

Dobles declarados (ninguno sustituye el mecanismo bajo prueba):
- ``principal``: SimpleNamespace con la forma de ResearchPrincipal
  (tenant_external_id, user_id, email). La identidad firmada NO se prueba.
- ``request``: SimpleNamespace con method/url.path/state.
- ``SessionLocal``: se revia a un engine SQLite real en memoria; las
  sesiones son reales y los listeners de tenant siguen activos.
- ``settings``: SimpleNamespace con research_auth_required / is_production.
- ``sync_binding`` (email_alerts): espia que registra la llamada; no se
  prueba el binding de email real.
- La carrera de creacion de tenant se simula con un commit que falla una
  vez con IntegrityError tras crear la fila rival por otra conexion.

NO se prueba: la resolucion del principal desde cabeceras
(get_research_principal) ni el rebuild forward-compat de init_db (lote 3).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.core.database as coredb
from app.models.entities import Base, Tenant

EXT = "ext-workspace-1"
USER = "user-1"


@pytest.fixture
def entorno(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(coredb, "SessionLocal", factory)
    monkeypatch.setattr(
        coredb,
        "settings",
        SimpleNamespace(research_auth_required=False, is_production=False),
    )
    try:
        yield engine
    finally:
        engine.dispose()


def _principal(email=None):
    return SimpleNamespace(tenant_external_id=EXT, user_id=USER, email=email)


def _request(method="GET", path="/api/cualquiera"):
    return SimpleNamespace(
        method=method, url=SimpleNamespace(path=path), state=SimpleNamespace()
    )


def _agota(gen):
    db = next(gen)
    with pytest.raises(StopIteration):
        next(gen)
    return db


def test_sin_principal_y_auth_obligatoria_da_401(entorno):
    coredb.settings.research_auth_required = True
    with pytest.raises(HTTPException) as exc:
        next(coredb.get_db(principal=None, request=None))
    assert exc.value.status_code == 401


def test_sin_principal_en_produccion_da_401(entorno):
    coredb.settings.is_production = True
    with pytest.raises(HTTPException) as exc:
        next(coredb.get_db(principal=None, request=None))
    assert exc.value.status_code == 401


def test_sin_principal_sin_auth_sesion_anonima(entorno):
    db = _agota(coredb.get_db(principal=None, request=None))
    assert "tenant_id" not in db.info
    assert db.info["language"]  # idioma siempre presente


def test_tenant_nuevo_se_materializa_y_liga(entorno):
    req = _request()
    db = _agota(coredb.get_db(principal=_principal(), request=req))
    # la sesion esta cerrada tras agotar: releer con una nueva
    with Session(entorno) as s2:
        tenant = s2.scalar(coredb.select(Tenant).where(Tenant.external_id == EXT))
        assert tenant is not None
        assert tenant.name == f"Workspace {EXT[:80]}"
        assert tenant.metadata_ == {"created_by": USER}
        assert db.info["tenant_id"] == tenant.id
        assert req.state.tenant_id == tenant.id
    assert db.info["user_id"] == USER


def test_tenant_existente_activo_se_reutiliza(entorno):
    with Session(entorno) as s:
        s.add(Tenant(external_id=EXT, name="Ya existia"))
        s.commit()
    db = _agota(coredb.get_db(principal=_principal(), request=_request()))
    with Session(entorno) as s2:
        tenants = s2.scalars(coredb.select(Tenant).where(Tenant.external_id == EXT)).all()
        assert len(tenants) == 1
        assert tenants[0].name == "Ya existia"
        assert db.info["tenant_id"] == tenants[0].id


def test_tenant_no_activo_da_403(entorno):
    with Session(entorno) as s:
        s.add(Tenant(external_id=EXT, status="suspended"))
        s.commit()
    with pytest.raises(HTTPException) as exc:
        next(coredb.get_db(principal=_principal(), request=_request()))
    assert exc.value.status_code == 403


def test_tenant_borrado_solo_admite_el_delete_de_privacidad(entorno):
    with Session(entorno) as s:
        s.add(Tenant(external_id=EXT, status="deleted"))
        s.commit()
    # cualquier otro endpoint: 403
    with pytest.raises(HTTPException) as exc:
        next(coredb.get_db(principal=_principal(), request=_request()))
    assert exc.value.status_code == 403
    # el DELETE idempotente de privacidad si pasa
    req = _request(method="DELETE", path="/api/privacy/account")
    db = _agota(coredb.get_db(principal=_principal(), request=req))
    assert db.info["user_id"] == USER


def test_carrera_de_creacion_relee_el_tenant_rival(entorno, monkeypatch):
    creados = {"n": 0}
    factory_real = coredb.SessionLocal

    def factory_con_commit_fallido():
        s = factory_real()
        commit_real = s.commit

        def flaky_commit():
            creados["n"] += 1
            if creados["n"] == 1:
                # el "rival" crea el tenant por otra conexion primero
                with factory_real() as rival:
                    rival.add(Tenant(external_id=EXT, name="Rival"))
                    rival.commit()
                raise IntegrityError("INSERT INTO tenants", {}, Exception("unique"))
            return commit_real()

        s.commit = flaky_commit
        return s

    monkeypatch.setattr(coredb, "SessionLocal", factory_con_commit_fallido)
    db = _agota(coredb.get_db(principal=_principal(), request=_request()))
    with Session(entorno) as s2:
        tenants = s2.scalars(coredb.select(Tenant).where(Tenant.external_id == EXT)).all()
        assert len(tenants) == 1
        assert tenants[0].name == "Rival"
        assert db.info["tenant_id"] == tenants[0].id


def test_email_del_principal_dispara_sync_binding(entorno, monkeypatch):
    llamadas = []
    import app.services.email_alerts as email_alerts

    monkeypatch.setattr(
        email_alerts,
        "sync_binding",
        lambda db, tenant_id, user_id, email: llamadas.append(
            (tenant_id, user_id, email)
        ),
    )
    db = _agota(
        coredb.get_db(principal=_principal(email="nico@example.com"), request=_request())
    )
    assert llamadas == [(db.info["tenant_id"], USER, "nico@example.com")]
    assert db.info["user_email"] == "nico@example.com"


def test_sin_email_no_llama_a_sync_binding(entorno, monkeypatch):
    llamadas = []
    import app.services.email_alerts as email_alerts

    monkeypatch.setattr(
        email_alerts,
        "sync_binding",
        lambda *args: llamadas.append(args),
    )
    db = _agota(
        coredb.get_db(principal=_principal(email=None), request=_request())
    )
    assert llamadas == []
    assert "user_email" not in db.info


def test_sync_binding_en_carrera_hace_rollback_sin_romper(entorno, monkeypatch):
    llamadas = []
    import app.services.email_alerts as email_alerts

    def binding_conflictivo(db, tenant_id, user_id, email):
        llamadas.append((tenant_id, user_id, email))
        raise IntegrityError("INSERT INTO email_bindings", {}, Exception("unique"))

    monkeypatch.setattr(email_alerts, "sync_binding", binding_conflictivo)
    db = _agota(
        coredb.get_db(principal=_principal(email="nico@example.com"), request=_request())
    )
    assert len(llamadas) == 1
    assert db.info["user_email"] == "nico@example.com"


def test_idioma_de_peticion_entra_en_db_info(entorno, monkeypatch):
    import app.core.i18n as i18n

    monkeypatch.setattr(
        i18n, "get_settings", lambda: SimpleNamespace(i18n_generation_enabled=True)
    )
    token = i18n.set_language_scope("en")
    try:
        db = _agota(coredb.get_db(principal=_principal(), request=_request()))
        assert db.info["language"] == "en"
    finally:
        i18n.reset_language_scope(token)
