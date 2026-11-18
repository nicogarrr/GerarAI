"""Tests del reindex masivo de la biblioteca de conocimiento.

Cubre el servicio (app/services/knowledge_rag/reindex.py) y el script CLI
(scripts/reindex_knowledge_library.py) con SQLite en memoria y un send falso,
MAS el contrato real del actor: `_session` (dramatiq_app) e
`ingest_knowledge_source.fn` se ejercitan de verdad, sin Redis ni Qdrant
(SessionLocal parcheado a SQLite; la fuente inexistente corta antes de Qdrant).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import Tenant
from app.models.knowledge_rag import KnowledgeRagSource
from app.services.knowledge_rag import reindex as svc

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reindex_knowledge_library", ROOT / "scripts" / "reindex_knowledge_library.py"
)
assert SPEC and SPEC.loader
SCRIPT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCRIPT
SPEC.loader.exec_module(SCRIPT)

OP = "operador@gerar.ai"


def _source(id_: int, status: str, tenant_id: int | None = None) -> KnowledgeRagSource:
    return KnowledgeRagSource(
        id=id_,
        tenant_id=tenant_id,
        sha256=f"{id_:064x}",
        title=f"doc {id_}",
        source_uri=f"https://example.test/{id_}",
        filename=f"doc{id_}.pdf",
        language="es",
        doc_type="informe",
        corpus="library",
        rights="owned",
        status=status,
        warnings=[],
    )


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[Tenant.__table__, KnowledgeRagSource.__table__])
    session = Session(eng)
    session.add(Tenant(id=1, external_id="t1"))
    session.add(Tenant(id=2, external_id="t2"))
    for id_, status, tenant in [
        (1, "indexed", 1),
        (2, "indexed", 1),
        (3, "failed", 1),
        (4, "queued", 1),
        (5, "processing", 1),
        (6, "indexed", 2),
        (7, "indexed", None),  # fuente global: sin contexto de despacho valido
    ]:
        session.add(_source(id_, status, tenant))
    session.commit()
    session.close()
    yield eng


@pytest.fixture()
def db(engine):
    session = Session(engine)
    yield session
    session.close()


# ---------- servicio: select_candidates ----------


def test_select_default_solo_indexed_ordenado(db):
    got = svc.select_candidates(db)
    assert [s.id for s in got] == [1, 2, 6, 7]


def test_select_include_failed(db):
    got = svc.select_candidates(db, include_failed=True)
    assert [s.id for s in got] == [1, 2, 3, 6, 7]


def test_select_no_toca_queued_ni_processing_aunque_se_pida_failed(db):
    got = svc.select_candidates(db, include_failed=True)
    assert 4 not in [s.id for s in got]
    assert 5 not in [s.id for s in got]


def test_select_filtra_tenant(db):
    got = svc.select_candidates(db, tenant_id=2)
    assert [s.id for s in got] == [6]


def test_select_limit(db):
    got = svc.select_candidates(db, limit=2)
    assert [s.id for s in got] == [1, 2]


def test_select_source_ids_prescinde_del_estado(db):
    got = svc.select_candidates(db, source_ids=(5, 3))
    assert [s.id for s in got] == [3, 5]  # orden por id, incluye failed y processing


def test_select_source_id_desconocido_no_rompe(db):
    got = svc.select_candidates(db, source_ids=(999,))
    assert got == []


# ---------- servicio: enqueue_sources (contrato del actor) ----------


def test_enqueue_envia_id_con_su_tenant_y_el_user_id(db):
    sent = []
    sources = svc.select_candidates(db, tenant_id=1)
    result = svc.enqueue_sources(sources, lambda *a, **kw: sent.append((a, kw)), user_id=OP)
    assert result.candidates == 2
    assert result.enqueued == 2
    assert result.errors == []
    assert result.skipped_no_tenant == []
    assert sent[0] == ((1,), {"tenant_id": 1, "user_id": OP})
    assert sent[1] == ((2,), {"tenant_id": 1, "user_id": OP})


def test_enqueue_cada_fuente_viaja_con_el_tenant_que_la_posee(db):
    sent = []
    sources = svc.select_candidates(db, source_ids=(1, 6))
    svc.enqueue_sources(sources, lambda *a, **kw: sent.append((a, kw)), user_id=OP)
    assert sent == [((1,), {"tenant_id": 1, "user_id": OP}), ((6,), {"tenant_id": 2, "user_id": OP})]


def test_enqueue_global_se_salta_y_se_reporta_sin_encolar(db):
    sent = []
    sources = svc.select_candidates(db, source_ids=(1, 7))
    result = svc.enqueue_sources(sources, lambda *a, **kw: sent.append(a), user_id=OP)
    assert sent == [(1,)]
    assert result.enqueued == 1
    assert result.skipped_no_tenant == [7]


def test_enqueue_user_id_obligatorio(db):
    sources = svc.select_candidates(db, tenant_id=1)
    with pytest.raises(ValueError, match="user_id es obligatorio"):
        svc.enqueue_sources(sources, lambda *a, **kw: None, user_id=None)
    with pytest.raises(ValueError, match="user_id es obligatorio"):
        svc.enqueue_sources(sources, lambda *a, **kw: None, user_id="")


def test_enqueue_un_fallo_no_detiene_el_lote(db):
    def send_flaky(source_id, **_kw):
        if source_id == 2:
            raise RuntimeError("broker caido")

    sources = svc.select_candidates(db, tenant_id=1)
    result = svc.enqueue_sources(sources, send_flaky, user_id=OP)
    assert result.enqueued == 1
    assert len(result.errors) == 1
    assert result.errors[0].source_id == 2
    assert result.errors[0].detail.startswith("RuntimeError: broker caido")


def test_enqueue_sleep_entre_items_no_tras_el_ultimo(db):
    pauses = []
    sources = svc.select_candidates(db, tenant_id=1, limit=2)
    svc.enqueue_sources(sources, lambda *a, **kw: None, user_id=OP, sleep_s=0.05, sleep=pauses.append)
    assert pauses == [0.05]


def test_enqueue_sin_sleep_no_duerme(db):
    pauses = []
    sources = svc.select_candidates(db, tenant_id=1, limit=2)
    svc.enqueue_sources(sources, lambda *a, **kw: None, user_id=OP, sleep_s=0.0, sleep=pauses.append)
    assert pauses == []


# ---------- contrato real: _session y el actor, sin Redis ni Qdrant ----------


@pytest.fixture()
def session_local_sqlite(engine, monkeypatch):
    """SessionLocal parcheado a SQLite: _session valida contra tenants reales."""
    import app.core.database as core_db

    monkeypatch.setattr(core_db, "SessionLocal", lambda: Session(engine))
    return core_db.SessionLocal


def test_session_real_exige_tenant_y_usuario(session_local_sqlite):
    from app.workers.dramatiq_app import _session

    with pytest.raises(ValueError, match="tenant_id and user_id are required"):
        _session(None, OP)
    with pytest.raises(ValueError, match="tenant_id and user_id are required"):
        _session(1, None)
    with pytest.raises(ValueError, match="tenant_id and user_id are required"):
        _session(1, "")
    with pytest.raises(ValueError, match="Active tenant 999"):
        _session(999, OP)


def test_session_real_abre_con_contexto_valido(session_local_sqlite):
    from app.workers.dramatiq_app import _session

    db = _session(1, OP)
    try:
        assert db.info["tenant_id"] == 1
        assert db.info["user_id"] == OP
    finally:
        db.close()


def test_actor_real_rechaza_entrega_sin_contexto(session_local_sqlite):
    """El bug del FAV: user_id=None. El actor REAL lo rechaza, no lo cuenta como ok."""
    from app.workers.knowledge_rag_actors import ingest_knowledge_source

    result = ingest_knowledge_source.fn(1, tenant_id=1, user_id=None)
    assert isinstance(result, dict)
    assert result.get("status") in ("error", "failed")


def test_actor_real_fuente_inexistente_sin_tocar_qdrant(session_local_sqlite):
    """Camino feliz de validacion: sesion abierta, fuente ausente, corte limpio."""
    from app.workers.knowledge_rag_actors import ingest_knowledge_source

    result = ingest_knowledge_source.fn(999, tenant_id=1, user_id=OP)
    assert result["status"] == "error"
    assert result["error"] == "source not found"


def test_actor_real_fuente_de_otro_tenant_es_invisible(session_local_sqlite):
    """La fuente 1 es del tenant 1: bajo sesion del tenant 2 el job no la ve.

    Por eso enqueue_sources despacha cada fuente con el tenant que la posee.
    """
    from app.workers.knowledge_rag_actors import ingest_knowledge_source

    result = ingest_knowledge_source.fn(1, tenant_id=2, user_id=OP)
    assert result["status"] == "error"
    assert result["error"] == "source not found"


def test_reindex_dispatch_matches_actual_actor_context_contract(session_local_sqlite):
    """Repro del Auditor (test_reindex_actor_contract_audit), adaptado al fix.

    El repro original (sin user_id) probaba que 2 fuentes "encoladas" eran
    rechazadas por el actor con 2 ValueError de _session mientras el resultado
    contaba 2 encoladas / 0 errores. Aqui va el actor REAL (su .fn, sin broker)
    con una fuente de tenant 1 y una global:
    - ninguna entrega es rechazada por el contrato de sesion (failures == []);
    - la global NI SE ENTREGA (skipped_no_tenant);
    - y un status error devuelto por el actor se cuenta como fallo, no como ok.
    """
    from unittest.mock import patch

    from app.workers import knowledge_rag_actors as actors

    failures = []

    def record(actor, error, **kw):
        failures.append((type(error).__name__, str(error)))
        return {"status": "error"}

    with patch.object(actors, "_handle_actor_error", record):
        result = svc.enqueue_sources(
            [
                KnowledgeRagSource(id=999, tenant_id=1),
                KnowledgeRagSource(id=124, tenant_id=None),
            ],
            actors.ingest_knowledge_source.fn,
            user_id=OP,
        )
    assert failures == [], f"Actor refused supposedly enqueued work: {failures}; result={result}"
    assert result.skipped_no_tenant == [124]
    assert result.enqueued == 0
    assert len(result.errors) == 1
    assert "source not found" in result.errors[0].detail


def test_enqueue_status_error_del_actor_cuenta_como_fallo(db):
    """Un sender sincrono que devuelve status error NO cuenta como encolado."""
    sources = svc.select_candidates(db, tenant_id=1, limit=2)
    result = svc.enqueue_sources(
        sources, lambda *a, **kw: {"status": "error", "error": "job fallo"}, user_id=OP
    )
    assert result.enqueued == 0
    assert len(result.errors) == 2
    assert result.errors[0].detail.startswith("status=error: job fallo")


def test_enqueue_status_ok_dict_cuenta_como_encolado(db):
    sources = svc.select_candidates(db, tenant_id=1, limit=1)
    result = svc.enqueue_sources(sources, lambda *a, **kw: {"status": "ok"}, user_id=OP)
    assert result.enqueued == 1
    assert result.errors == []


# ---------- script CLI ----------


def test_cli_dry_run_no_encola_y_sale_0(db, capsys):
    sent = []
    rc = SCRIPT.main([], db=db, send=lambda *a, **kw: sent.append(a))
    out = capsys.readouterr().out
    assert rc == 0
    assert sent == []
    assert "DRY-RUN: 4 fuentes candidatas" in out
    assert "[1, 2, 6, 7]" in out


def test_cli_apply_exige_user_id(db):
    with pytest.raises(SystemExit):
        SCRIPT.main(["--apply"], db=db, send=lambda *a, **kw: None)


def test_cli_apply_encola_con_user_id_y_reporta_globales(db, capsys):
    sent = []
    rc = SCRIPT.main(["--apply", "--user-id", OP], db=db, send=lambda *a, **kw: sent.append((a, kw)))
    out = capsys.readouterr().out
    assert rc == 0
    assert sent == [
        ((1,), {"tenant_id": 1, "user_id": OP}),
        ((2,), {"tenant_id": 1, "user_id": OP}),
        ((6,), {"tenant_id": 2, "user_id": OP}),
    ]
    assert '"enqueued": 3' in out
    assert '"skipped_no_tenant": [7]' in out
    assert "AVISO: fuentes globales" in out


def test_cli_apply_con_fallo_sale_1(db, capsys):
    def send_flaky(source_id, **_kw):
        if source_id == 6:
            raise ValueError("boom")

    rc = SCRIPT.main(["--apply", "--user-id", OP], db=db, send=send_flaky)
    out = capsys.readouterr().out
    assert rc == 1
    assert '"enqueued": 2' in out
    assert '"source_id": 6' in out


def test_cli_sin_candidatas_dry_run(db, capsys):
    rc = SCRIPT.main(["--tenant-id", "999"], db=db, send=lambda *a, **kw: None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN: 0 fuentes candidatas" in out


def test_cli_filtros_combinados(db):
    sent = []
    rc = SCRIPT.main(
        ["--include-failed", "--tenant-id", "1", "--limit", "2", "--user-id", OP, "--apply"],
        db=db,
        send=lambda *a, **kw: sent.append(a),
    )
    assert rc == 0
    assert sent == [(1,), (2,)]


def test_cli_source_id_relanza_processing(db):
    sent = []
    rc = SCRIPT.main(
        ["--source-id", "5", "--user-id", OP, "--apply"], db=db, send=lambda *a, **kw: sent.append(a)
    )
    assert rc == 0
    assert sent == [(5,)]


def test_cli_limit_invalido():
    with pytest.raises(SystemExit):
        SCRIPT.main(["--limit", "0"], db=None)


def test_cli_sleep_ms_invalido():
    with pytest.raises(SystemExit):
        SCRIPT.main(["--sleep-ms", "-1"], db=None)


# ---------- script CLI: importaciones perezosas y sesion propia ----------


def test_default_send_devuelve_el_send_del_actor(monkeypatch):
    import types

    fake_module = types.ModuleType("app.workers.knowledge_rag_actors")
    fake_actor = types.SimpleNamespace(send=lambda *a, **kw: None)
    fake_module.ingest_knowledge_source = fake_actor
    monkeypatch.setitem(sys.modules, "app.workers.knowledge_rag_actors", fake_module)
    assert SCRIPT._default_send() is fake_actor.send


def test_cli_apply_sin_send_usa_default_send(db, monkeypatch):
    sent = []
    monkeypatch.setattr(SCRIPT, "_default_send", lambda: lambda *a, **kw: sent.append(a))
    rc = SCRIPT.main(["--apply", "--user-id", OP], db=db)
    assert rc == 0
    assert len(sent) == 3  # la global (7) se salta


def test_cli_propia_sesion_abre_y_cierra(engine, monkeypatch):
    closed = []
    session = Session(engine)
    original_close = session.close
    monkeypatch.setattr(session, "close", lambda: (closed.append(True), original_close()))
    import app.core.database as core_db

    monkeypatch.setattr(core_db, "SessionLocal", lambda: session)
    rc = SCRIPT.main([], db=None)
    assert rc == 0
    assert closed == [True]


def test_cli_dry_run_mas_de_50_ids_recorta_la_lista(db, capsys):
    for id_ in range(100, 160):
        db.add(_source(id_, "indexed", 1))
    db.commit()
    rc = SCRIPT.main([], db=db)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN: 64 fuentes candidatas" in out
    assert " ..." in out
