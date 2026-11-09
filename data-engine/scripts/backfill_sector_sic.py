"""Rellena sector e industria «Unknown» con el SIC de la SEC (data.sec.gov/submissions), sin pisar curados.

Uso: python scripts/backfill_sector_sic.py [--dry-run] [TICKER ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.entities import Company  # noqa: E402
from app.services.sic_classification import fill_from_sic  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        companies = None
        if args:
            companies = list(db.scalars(select(Company).where(Company.ticker.in_([a.upper() for a in args]))).all())
        out = fill_from_sic(db, companies=companies)
        if dry:
            db.rollback()
        else:
            db.commit()
        print(json.dumps({**out, "dry_run": dry}, ensure_ascii=False, indent=1))
    finally:
        db.close()


if __name__ == "__main__":
    main()
