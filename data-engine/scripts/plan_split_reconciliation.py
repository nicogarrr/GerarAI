"""Plan DRY-RUN de reconciliación de splits duplicados (solo lectura).

Imprime un JSON con los grupos duplicados de ``corporate_actions`` y qué
filas SIN aplicar se podrían retirar. NO borra, NO aplica y NO escribe: la
sesión se abre en modo solo lectura (PostgreSQL: ``SET TRANSACTION READ ONLY``)
y se hace rollback al final. El saneamiento, si procede, es un paso aparte.

Uso:
    python scripts/plan_split_reconciliation.py --tenant-external-id <ext>
    python scripts/plan_split_reconciliation.py --all-tenants

Sin ``--tenant-external-id`` ni ``--all-tenants`` no hace nada (falla cerrado).
Para ejecutarlo contra una base restaurada, apunta DATABASE_URL a la copia.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Tenant
from app.services.split_reconciliation import plan_split_reconciliation


def run(db: Session, *, tenant_external_id: str | None, all_tenants: bool) -> dict:
    """Calcula el plan en una transacción de solo lectura y la revierte siempre."""
    if not tenant_external_id and not all_tenants:
        raise SystemExit("Indica --tenant-external-id <ext> o --all-tenants")
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        tenant_id = None
        if tenant_external_id:
            tenant = db.scalar(select(Tenant).where(Tenant.external_id == tenant_external_id))
            if tenant is None:
                raise SystemExit(f"Tenant no encontrado: {tenant_external_id}")
            tenant_id = tenant.id
        plan = plan_split_reconciliation(db, tenant_id=tenant_id, all_tenants=all_tenants)
        return plan.as_dict()
    finally:
        db.rollback()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-external-id", default=None)
    parser.add_argument("--all-tenants", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = run(db, tenant_external_id=args.tenant_external_id, all_tenants=args.all_tenants)
    finally:
        db.close()
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
