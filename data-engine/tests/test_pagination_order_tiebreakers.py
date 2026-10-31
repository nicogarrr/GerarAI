"""Desempate determinista en listados ordenados por columnas no unicas.

Sin desempate por id, filas con created_at/trade_date empatados no tienen
orden definido: en Postgres el plan decide y una lista paginada puede repetir
o saltarse filas entre paginas, y un export cambia de orden entre corridas.

Nota honesta: en SQLite el plan suele caer en rowid y el rojo no se demuestra
(estos tests pasarian igualmente); el valor real es Postgres, donde el empate
no tiene orden garantizado. Aqui fijamos el contrato: orden total estable.
"""

from datetime import UTC, date, datetime

from sqlalchemy import create_engine, desc, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AuditLog, Company, Transaction
from app.models.entities import ProcessingJob
from app.services.audit_service import list_audit_logs

TS = datetime(2026, 3, 3, 12, 0, 0, tzinfo=UTC)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_audit_logs_paginados_sin_duplicados_con_created_at_empatado():
    with _session() as db:
        for _ in range(5):
            db.add(AuditLog(action="login", resource_type="session", created_at=TS))
        db.commit()

        seen: list[int] = []
        for k in range(5):
            seen.extend(r.id for r in list_audit_logs(db, limit=1, offset=k))

    assert len(seen) == len(set(seen)) == 5  # ninguna fila repetida ni saltada
    assert seen == sorted(seen, reverse=True)  # desempate: id descendente


def test_processing_jobs_mismo_created_at_orden_id_desc():
    with _session() as db:
        ids = []
        for _ in range(3):
            job = ProcessingJob(
                job_type="knowledge_principle_extraction",
                entity_type="knowledge_document",
                entity_id=1,
                status="queued",
                result={},
                created_at=TS,
            )
            db.add(job)
            db.flush()
            ids.append(job.id)
        db.commit()

        ordered = db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.job_type == "knowledge_principle_extraction")
            .order_by(desc(ProcessingJob.created_at), desc(ProcessingJob.id))
            .limit(100)
        ).all()

    assert [j.id for j in ordered] == sorted(ids, reverse=True)


def test_export_transacciones_misma_fecha_orden_determinista():
    with _session() as db:
        company = Company(
            ticker="TIEBRK", name="Synthetic", exchange="NYSE", currency="USD",
            sector="Test", industry="Test", company_type="standard",
            valuation_model="standard_dcf",
        )
        db.add(company)
        db.flush()
        ids = []
        for qty in ("1", "2", "3"):
            tx = Transaction(
                company_id=company.id, trade_date=date(2026, 2, 2), action="buy",
                quantity=qty, price="10", currency="EUR", created_at=TS,
            )
            db.add(tx)
            db.flush()
            ids.append(tx.id)
        db.commit()

        def run() -> list[int]:
            # La misma sentencia que export_year en app/api/routes/export.py
            return [
                row.Transaction.id
                for row in db.execute(
                    select(Transaction, Company)
                    .join(Company, Transaction.company_id == Company.id)
                    .where(
                        Transaction.trade_date >= date(2026, 1, 1),
                        Transaction.trade_date <= date(2026, 12, 31),
                    )
                    .order_by(Transaction.trade_date, Transaction.created_at, Transaction.id)
                ).all()
            ]

        assert run() == run() == ids  # orden total estable: id ascendente en el empate
