"""Reconstruye la serie de snapshots/TWR de la cartera por defecto del tenant.

Dry-run por defecto; solo escribe con --write y siempre deja backup JSON.
NO ejecutar en produccion sin orden expresa de Nico (regla vigente).

Plan de backup y restauración:
1. Dry-run: revisar el plan (rango, fotos existentes, chequeo de valor final).
2. Backup adicional recomendado a nivel base de datos antes de --write:
   scripts/backup/backup_postgres.py (ver docs/BACKUP_RESTORE.md).
3. --write: la herramienta guarda las fotos reemplazadas en
   --backup (por defecto logs/twr_rebuild_backup_<ts>.json) y reemplaza la
   serie en una sola transacción del ORM.
4. Restauración: --restore <backup.json> repone las fotos guardadas
   (borra las del rango, incluidas las reconstruidas).
5. Verificación posterior: la primera captura real (market_refresh) tras la
   serie reconstruida NO encadena sobre ella (cambio de alcance declarado):
   queda marcada como nueva base y la cadena vuelve a crecer desde ahí.

Uso:
    python scripts/rebuild_portfolio_twr_snapshots.py --tenant-external-id <ext>
    python scripts/rebuild_portfolio_twr_snapshots.py --tenant-external-id <ext> --write
    python scripts/rebuild_portfolio_twr_snapshots.py --tenant-external-id <ext> --restore ruta/backup.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Tenant
from app.services.twr_rebuild_service import TwrRebuildService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-external-id", required=True)
    parser.add_argument("--desde", default=None, help="AAAA-MM-DD; por defecto, la primera operación")
    parser.add_argument("--write", action="store_true", help="aplica los cambios (por defecto es dry-run)")
    parser.add_argument("--backup", default=None, help="ruta del backup JSON (con --write)")
    parser.add_argument("--restore", default=None, help="restaura un backup JSON y termina")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == args.tenant_external_id))
        if tenant is None:
            print(f"Tenant no encontrado: {args.tenant_external_id}")
            return 1
        db.info["tenant_id"] = tenant.id
        service = TwrRebuildService()
        start = date.fromisoformat(args.desde) if args.desde else None

        if args.restore:
            result = service.restore_backup(db, backup_path=args.restore)
            db.commit()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result.get("status") == "restored" else 1

        if not args.write:
            print(json.dumps(service.plan(db, start=start), indent=2, ensure_ascii=False))
            print("DRY-RUN: nada escrito. Repite con --write para aplicar.")
            return 0

        backup = args.backup or f"logs/twr_rebuild_backup_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
        result = service.apply(db, start=start, backup_path=backup)
        if result.get("applied"):
            db.commit()
        else:
            db.rollback()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("applied") else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
