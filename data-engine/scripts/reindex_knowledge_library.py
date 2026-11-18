"""Reindex MASIVO de la biblioteca de conocimiento (re-encolado a la cola `knowledge`).

Reconstruye la coleccion Qdrant `knowledge_rag_v2` re-encolando cada fuente
candidata al actor `ingest_knowledge_source`, que repite la ingesta completa
(extraccion -> chunks -> embeddings locales -> Qdrant) de forma idempotente.
Pensado para dos escenarios: perdida del volumen de Qdrant y cambio del modelo
de embeddings. Los embeddings son locales (fastembed): el reindex cuesta CPU,
0 EUR.

Cada fuente se encola con el tenant que la posee y el usuario del operador
(--user-id): es el mismo contrato que el flujo API (routes._dispatch envia
db.info['tenant_id']/['user_id']) y el actor abre sesion con
_session(tenant_id, user_id), que RECHAZA entregas sin tenant o sin usuario.
Las fuentes globales (tenant_id NULL) no tienen contexto valido bajo ese
contrato: se saltan y se reportan, no se encolan.

Por defecto es DRY-RUN (imprime lo que encolaria); `--apply` encola de verdad.
Por defecto solo re-encola fuentes `indexed` (las `queued`/`processing` son
trabajo en vuelo del pipeline); `--include-failed` suma las `failed` y
`--source-id` relanza ids concretos sin filtro de estado.

Uso (dentro del contenedor backend, con Postgres y Redis alcanzables):
    python scripts/reindex_knowledge_library.py                    # dry-run
    python scripts/reindex_knowledge_library.py --user-id nico@gerar.ai --apply
    python scripts/reindex_knowledge_library.py --tenant-id 3 --limit 50 --user-id op --apply
    python scripts/reindex_knowledge_library.py --source-id 12 --source-id 30 --user-id op --apply
    python scripts/reindex_knowledge_library.py --include-failed --sleep-ms 100 --user-id op --apply

Salida: 0 si todo encolado (o dry-run), 1 si algun envio fallo. Las fuentes
saltadas por globales NO son error: se listan en skipped_no_tenant.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-encola fuentes de la biblioteca de conocimiento al actor de ingesta."
    )
    parser.add_argument("--tenant-id", type=int, default=None,
                        help="Solo fuentes de este tenant (por defecto: todas, incluidas las globales).")
    parser.add_argument("--include-failed", action="store_true",
                        help="Re-encola tambien las fuentes en estado failed.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Maximo de fuentes a re-encolar (por id ascendente).")
    parser.add_argument("--source-id", type=int, action="append", default=[],
                        help="Re-lanza este id concreto (repetible); prescinde del filtro de estado.")
    parser.add_argument("--user-id", default=None,
                        help="Usuario de contexto para el actor (obligatorio con --apply): "
                             "el actor abre sesion con _session(tenant_id, user_id) y rechaza "
                             "entregas sin usuario. Equivale al principal del flujo API.")
    parser.add_argument("--sleep-ms", type=float, default=0.0,
                        help="Pausa entre envios para no inundar Redis (defecto: 0).")
    parser.add_argument("--apply", action="store_true",
                        help="Encola de verdad. Sin esta flag es un dry-run.")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit debe ser >= 1")
    if args.sleep_ms < 0:
        parser.error("--sleep-ms debe ser >= 0")
    if args.apply and not args.user_id:
        parser.error("--user-id es obligatorio con --apply: el actor rechaza entregas sin usuario")
    return args


def _default_send():
    """Import perezoso: el actor tira del broker (Redis) y no debe importarse en tests."""
    from app.workers.knowledge_rag_actors import ingest_knowledge_source

    return ingest_knowledge_source.send


def main(argv: list[str] | None = None, *, db=None, send=None) -> int:
    from app.services.knowledge_rag.reindex import enqueue_sources, select_candidates

    args = _parse_args(argv)
    own_session = db is None
    if own_session:
        from app.core.database import SessionLocal

        db = SessionLocal()
    try:
        candidates = select_candidates(
            db,
            tenant_id=args.tenant_id,
            include_failed=args.include_failed,
            limit=args.limit,
            source_ids=tuple(args.source_id),
        )
        if not args.apply:
            ids = [s.id for s in candidates]
            print(f"DRY-RUN: {len(ids)} fuentes candidatas (sin --apply no se encola nada)")
            print(f"ids: {ids[:50]}{' ...' if len(ids) > 50 else ''}")
            return 0
        if send is None:
            send = _default_send()
        result = enqueue_sources(candidates, send, user_id=args.user_id, sleep_s=args.sleep_ms / 1000)
        if result.skipped_no_tenant:
            print(
                "AVISO: fuentes globales (tenant_id NULL) NO encoladas: el actor exige "
                f"tenant y usuario ({len(result.skipped_no_tenant)}): {result.skipped_no_tenant}"
            )
        summary = {
            "candidates": result.candidates,
            "enqueued": result.enqueued,
            "skipped_no_tenant": result.skipped_no_tenant,
            "errors": [{"source_id": e.source_id, "detail": e.detail} for e in result.errors],
        }
        print(f"RESULTADO_REINDEX: {json.dumps(summary)}", flush=True)
        return 1 if result.errors else 0
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())  # pragma: no cover - entrada de proceso, testeada via main()
