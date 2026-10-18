"""CLI de la ingesta del corpus libre de cartas (ver app/services/corpus_ingestion_service.py).

Uso (dentro del contenedor backend):
    python scripts/ingest_corpus.py --tenant-external-id <ext> [--dry-run]
    python scripts/ingest_corpus.py --tenant-external-id <ext> --from-dir <dir>

--from-dir ingiere ficheros locales declarados en <dir>/manifest.json (para
fuentes que bloquean la IP del servidor; el manifest declara titulo, autor y
URL de origen: descargar a mano no convierte la procedencia en implicita).
Formato: [{"file": "Berkshire2023.pdf", "title": "...", "author": "...",
"source_url": "https://...", "document_type": "fund_letter", "language": "en"}].
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Tenant
from app.services.corpus_ingestion_service import (
    get_or_create_corpus_collection,
    ingest_free_corpus,
)
from app.services.knowledge_library_service import KnowledgeLibraryService


def _ingest_from_dir(db, service, collection, directory: Path, dry_run: bool) -> dict:
    stats = {"ingested": 0, "duplicates": 0, "failed": [], "skipped_sources": []}
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        stats["failed"].append({"title": str(manifest_path), "error": "manifest.json no encontrado"})
        return stats
    entries = json.loads(manifest_path.read_text())
    for entry in entries:
        file_path = directory / entry["file"]
        if dry_run:
            print(f"DRY: {entry['title']} <- {file_path.name} (origen: {entry.get('source_url')})")
            continue
        try:
            result = service.ingest_bytes(
                db,
                title=entry["title"],
                content=file_path.read_bytes(),
                filename=entry["file"],
                document_type=entry.get("document_type", "fund_letter"),
                collection_id=collection.id,
                author=entry.get("author"),
                source_url=entry.get("source_url"),
                language=entry.get("language", "en"),
            )
            db.commit()
            if result["status"] == "duplicate":
                stats["duplicates"] += 1
            else:
                stats["ingested"] += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            stats["failed"].append({"title": entry.get("title"), "error": str(exc)[:200]})
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-external-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--from-dir",
        help="Ingiere ficheros locales con manifest.json (para fuentes que bloquean "
        "la IP del servidor; el manifest declara titulo, autor y URL de origen).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.scalar(
            select(Tenant).where(Tenant.external_id == args.tenant_external_id)
        )
        if tenant is None:
            print(f"Tenant no encontrado: {args.tenant_external_id}")
            return 1
        db.info["tenant_id"] = tenant.id

        if args.from_dir:
            service = KnowledgeLibraryService()
            collection = get_or_create_corpus_collection(db)
            db.commit()
            stats = _ingest_from_dir(db, service, collection, Path(args.from_dir), args.dry_run)
            print("RESULTADO:", json.dumps(stats, indent=2, ensure_ascii=False))
            return 0

        if args.dry_run:
            # Solo descubrimiento: reutiliza los discoverers del servicio.
            import httpx

            from app.services import corpus_ingestion_service as corpus

            with httpx.Client(
                headers={"User-Agent": corpus.USER_AGENT}, timeout=60, follow_redirects=True
            ) as client:
                sources = corpus._discover_numantia_sources(client)
                sources += corpus._discover_buffett_sources(client)
                sources += corpus._discover_azvalor_sources(client)
                sources += corpus._discover_magallanes_sources(client)
            for source in sources:
                print(f"DRY: {source['title']} <- {source['url']}")
            print(f"TOTAL: {len(sources)} fuentes descubiertas")
            return 0

        stats = ingest_free_corpus(db)
    finally:
        db.close()

    print("RESULTADO:", json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
