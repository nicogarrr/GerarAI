"""Recoge notas de prensa oficiales (propias o de la contraparte) de una empresa y lista sus catalizadores.

Uso: python scripts/collect_official_catalysts.py TICKER [--url URL ...] [--no-discover] [--dry-run]
Gratis: Bing News RSS + la página oficial (respetando robots.txt). Sin modelo.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal  # noqa: E402
from app.services.company_resolver import resolve_company  # noqa: E402
from app.services.official_catalysts import catalysts_for, collect  # noqa: E402


def main() -> None:
    argv = sys.argv[1:]
    urls = [argv[i + 1] for i, a in enumerate(argv) if a == "--url" and i + 1 < len(argv)]
    rest = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--url")]
    tenant = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--tenant=")), "1"))
    db = SessionLocal()
    db.info["tenant_id"] = tenant
    try:
        company = resolve_company(db, rest[0])
        if company is None:
            raise SystemExit(f"sin ficha: {rest[0]}")
        report = collect(db, company, tenant, urls=urls, discover_news="--no-discover" not in argv)
        if "--dry-run" in argv:
            db.rollback()
        else:
            db.commit()
        print(json.dumps({"collect": report, "catalysts": catalysts_for(db, company)}, ensure_ascii=False, indent=1))
    finally:
        db.close()


if __name__ == "__main__":
    main()
