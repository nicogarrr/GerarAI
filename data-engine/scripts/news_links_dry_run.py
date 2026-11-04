"""Simulación SOLO LECTURA de los vínculos por alias/relaciones sobre noticias guardadas.

Uso (lo decide Nico; no escribe nada, hace rollback al final):

    python scripts/news_links_dry_run.py --limit 5000 [--ticker ASTS] [--muestras 20]

Para cada noticia (titular + resumen guardados) compara la empresa que tiene
hoy con la que daría la vinculación nueva y cuenta: sin cambio, nueva
«sobre» (alias), nueva «relacionada», y relacionadas anotadas. Sirve para
medir precisión real antes de mergear.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.entities import Company, NewsEvent  # noqa: E402
from app.services.news_service import NewsService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--muestras", type=int, default=20)
    args = parser.parse_args()
    service = NewsService()
    db = SessionLocal()
    try:
        by_id = {c.id: c.ticker for c in db.scalars(select(Company))}
        rows = db.execute(
            select(NewsEvent.id, NewsEvent.company_id, NewsEvent.title, NewsEvent.summary)
            .where(NewsEvent.company_id.is_(None))
            .order_by(NewsEvent.id.desc())
            .limit(args.limit)
        ).all()
        counts: Counter[str] = Counter()
        samples: list[dict] = []
        for news_id, _company_id, title, summary in rows:
            text = f"{title or ''} {summary or ''}"
            primary, related = service.detect_company_links(db, text)
            kind = primary.link_type if primary else "sin_empresa"
            counts[kind] += 1
            counts["con_relacionadas_anotadas"] += bool(related)
            tickers = {primary.company.ticker} if primary else set()
            tickers |= {r.company.ticker for r in related}
            if primary and (args.ticker is None or args.ticker in tickers) and len(samples) < args.muestras:
                samples.append(
                    {
                        "id": news_id,
                        "titulo": (title or "")[:140],
                        "vinculo": primary.as_metadata(),
                        "relacionadas": [r.as_metadata() for r in related],
                    }
                )
        print(
            json.dumps(
                {
                    "noticias_sin_empresa_leidas": len(rows),
                    "empresas": len(by_id),
                    "resultado_nuevo": dict(counts),
                    "muestras": samples,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    finally:
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
