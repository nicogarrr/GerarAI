"""Dry-run by default. Apply only after restored backup and consumer deployment.

The backup evidence argument records the operator's verified restore receipt;
this script cannot validate a restore itself. It never changes source ESEF rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal  # noqa: E402
from app.services.reviewed_eps_repair import repair_reviewed_eps  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restored-backup-evidence")
    args = parser.parse_args()
    if args.apply and not args.restored_backup_evidence:
        parser.error("--apply requires the path/reference of the verified restore receipt")
    with SessionLocal() as db:
        db.info["tenant_id"] = args.tenant_id
        try:
            result = repair_reviewed_eps(db, tenant_id=args.tenant_id, apply=args.apply)
            result["restored_backup_evidence"] = args.restored_backup_evidence
            if args.apply:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            raise
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
