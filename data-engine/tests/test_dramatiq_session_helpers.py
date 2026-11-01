"""Tests de helpers de sesion/consulta de app/workers/dramatiq_app.py.

_session (validacion de tenant activo, herencia de idioma, commit inicial),
tenant_contexts (solo activos con created_by), _companies (filtro y orden),
_emit_fingerprint/_message_id/_rollback. Base de datos SQLite de test real
via init_db()/SessionLocal, como hace el worker.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

import app.workers.dramatiq_app as da
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant


def _tenant(ext: str, status: str = "active", metadata: dict | None = None) -> int:
    db = SessionLocal()
    try:
        t = Tenant(external_id=ext, name=ext, status=status, metadata_=metadata or {})
        db.add(t)
        db.commit()
        return t.id
    finally:
        db.close()


@pytest.fixture
def _init():
    init_db()


def test_session_exige_tenant_y_usuario(_init):
    with pytest.raises(ValueError, match="tenant_id and user_id"):
        da._session(None, "user-1")
    with pytest.raises(ValueError, match="tenant_id and user_id"):
        da._session(1, "")


def test_session_rechaza_tenant_inexistente_o_inactivo(_init):
    with pytest.raises(ValueError, match="Active tenant"):
        da._session(999999, "user-1")
    inactive_id = _tenant(f"inactivo-{uuid4().hex[:8]}", status="suspended")
    with pytest.raises(ValueError, match="Active tenant"):
        da._session(inactive_id, "user-1")


def test_session_propaga_contexto_e_idioma(_init):
    tenant_id = _tenant(f"activo-{uuid4().hex[:8]}", metadata={"language": "es", "created_by": "user-1"})
    db = da._session(tenant_id, "user-1")
    try:
        assert db.info["tenant_id"] == tenant_id
        assert db.info["user_id"] == "user-1"
        assert db.info["language"] == "es"
        # el commit inicial cierra la transaccion de lectura del tenant
        assert not db.in_transaction()
    finally:
        db.close()


def test_session_sin_idioma_soportado_no_lo_fija(_init):
    tenant_id = _tenant(f"sinlang-{uuid4().hex[:8]}", metadata={"language": "klingon"})
    db = da._session(tenant_id, "user-1")
    try:
        assert "language" not in db.info
    finally:
        db.close()


def test_tenant_contexts_solo_activos_con_created_by(_init):
    _tenant(f"ctx-a-{uuid4().hex[:8]}", metadata={"created_by": "user-a"})
    _tenant(f"ctx-b-{uuid4().hex[:8]}", metadata={})
    _tenant(f"ctx-c-{uuid4().hex[:8]}", status="suspended", metadata={"created_by": "user-c"})
    contexts = da.tenant_contexts()
    user_ids = {user for _, user in contexts}
    assert "user-a" in user_ids
    assert "user-c" not in user_ids
    # todos los contextos corresponden a tenants con created_by no vacio
    assert all(user.strip() for _, user in contexts)


def test_companies_filtra_por_ticker_y_ordena(_init):
    db = SessionLocal()
    try:
        db.info["tenant_id"] = 1
        for ticker in ["ZZTEST2", "ZZTEST1"]:
            db.add(Company(
                ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
                sector="Tech", industry="Tech", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
            ))
        db.commit()
        tickers = [c.ticker for c in da._companies(db)]
        assert tickers == sorted(tickers)  # orden por ticker
        assert {"ZZTEST1", "ZZTEST2"} <= set(tickers)
        assert [c.ticker for c in da._companies(db, ticker="zztest1")] == ["ZZTEST1"]  # filtro upper
    finally:
        db.close()


def test_emit_fingerprint_estable_y_sensible_a_partes():
    a = da._emit_fingerprint("regla", 1, "doc")
    assert a == da._emit_fingerprint("regla", 1, "doc")
    assert a != da._emit_fingerprint("regla", 2, "doc")
    assert a != da._emit_fingerprint("regla", 1, "otro")
    assert len(a) == 64


def test_message_id_none_si_falta():
    assert da._message_id(type("M", (), {"message_id": None})()) is None
    assert da._message_id(type("M", (), {"message_id": "abc"})()) == "abc"
    assert da._message_id(object()) is None


def test_rollback_traga_errores():
    class _DB:
        def rollback(self):
            raise RuntimeError("caido")

    da._rollback(_DB())  # no propaga
