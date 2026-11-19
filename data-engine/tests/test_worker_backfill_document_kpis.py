"""backfill_document_kpis: ramas que test_kpi_backpressure no cubre:
cola no disponible, cortes por capacidad (entre tenants y dentro del
lote), guarda in-loop de agotados con JSON no canonico y QueueCapacityError
que revierte la reserva."""

import datetime as dt
from unittest.mock import patch

from app.workers import dramatiq_app as workers
from app.workers.bounded_broker import QueueCapacityError


def _db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import Document  # noqa: F401 - registra la tabla

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Document.__table__])
    return sessionmaker(bind=engine)()


def _doc(db, title, deferred, created=None):
    from app.models import Document

    doc = Document(
        title=title,
        source_type="sec",
        tenant_id=1,
        metadata_={"kpi_deferred": deferred} if deferred is not None else {},
        created_at=created or dt.datetime(2026, 1, 1),
    )
    db.add(doc)
    db.commit()
    return doc


def _run(db, depth=0, max_pending=10, tenants=((1, "u"),), send_side_effect=None):
    with (
        patch.object(workers, "tenant_contexts", return_value=list(tenants)),
        patch.object(workers, "_session", return_value=db),
        patch.object(workers, "_redis_client", return_value=None),
        patch.object(workers, "kpi_queue_depth", return_value=depth),
        patch.object(workers, "kpi_queue_max_pending", return_value=max_pending),
        patch.object(workers.extract_document_kpis, "send") as send,
    ):
        if send_side_effect is not None:
            send.side_effect = send_side_effect
        result = workers.backfill_document_kpis()
    return result, send


def test_cola_no_disponible_skips():
    db = _db()
    with (
        patch.object(workers, "_redis_client", return_value=None),
        patch.object(workers, "kpi_queue_depth", return_value=None),
    ):
        result = workers.backfill_document_kpis()
    assert result["status"] == "skipped" and result["reason"] == "queue_unavailable"


def test_capacidad_llena_corta_entre_tenants():
    db = _db()
    _doc(db, "d1", {"attempts": 0})
    result, send = _run(db, max_pending=1, tenants=((1, "u"), (2, "u")))
    assert result["queued"] == 1 and send.call_count == 1


def test_capacidad_llena_corta_dentro_del_lote():
    db = _db()
    _doc(db, "d1", {"attempts": 0})
    _doc(db, "d2", {"attempts": 0})
    result, send = _run(db, max_pending=1)
    assert result["queued"] == 1 and send.call_count == 1


def test_guarda_in_loop_de_agotados_con_json_no_canonico():
    """El filtro SQL y la guarda in-loop leen el mismo path, pero coercionan
    distinto: SQLite CAST('0_5' AS INTEGER)=0 (pasa el filtro) mientras
    int('0_5')=5 (agotado). La guarda in-loop es la definitiva."""
    db = _db()
    _doc(db, "d1", {"attempts": "0_5"})
    result, send = _run(db)
    assert result["queued"] == 0 and result["exhausted"] == 1
    assert send.call_count == 0


def test_queue_capacity_revierte_la_reserva_y_devuelve_parcial():
    db = _db()
    doc = _doc(db, "d1", {"attempts": 0})
    doc_id = doc.id  # el actor cierra la sesion: doc queda detachado
    result, send = _run(db, send_side_effect=QueueCapacityError("llena"))
    assert result["status"] == "ok" and result["queued"] == 0
    from app.models import Document

    stored = db.query(Document).filter_by(id=doc_id).one()
    deferred = stored.metadata_["kpi_deferred"]
    # La reserva se revierte: attempts como estaba y sin queued_at, para
    # reintentarlo como nunca enviado en la pasada siguiente.
    assert deferred.get("attempts") == 0 and "queued_at" not in deferred
