"""Reaplica normalize_scraped_text() a los resúmenes de ThesisChange persistidos.

Las tarjetas «Deterioro de tesis» mostraban texto pegado del scrape
(«StockCurrent Price: $210. 32Target Price…», «(FY)..») porque el summary se
guardaba sin sanear. El fix de ingesta ya sanea los nuevos; este script corrige
los existentes. Idempotente: normalize_scraped_text es idempotente y solo se
toca una fila si el saneado la cambia.

Uso:
    # dry-run (por defecto): cuenta filas afectadas y muestra 5 antes/después
    python scripts/backfill_thesis_change_summary_normalize.py
    # aplica los cambios
    python scripts/backfill_thesis_change_summary_normalize.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import ThesisChange
from app.services.text_clip import normalize_scraped_text

SAMPLE = 5
BATCH = 500


def find_dirty_ids(db) -> list[int]:
    ids = []
    for row_id, summary in db.execute(select(ThesisChange.id, ThesisChange.summary)):
        if summary and normalize_scraped_text(summary) != summary:
            ids.append(row_id)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="escribe los cambios (por defecto dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        dirty = find_dirty_ids(db)
        print(f"Filas ThesisChange con summary sin sanear: {len(dirty)}")
        for row_id in dirty[:SAMPLE]:
            before = db.get(ThesisChange, row_id).summary
            print(f"--- id={row_id}\nANTES:   {before[:220]}\nDESPUÉS: {normalize_scraped_text(before)[:220]}")
        if not args.apply:
            print("Dry-run: sin cambios. Repite con --apply para escribir.")
            return 0
        done = 0
        for row_id in dirty:
            obj = db.get(ThesisChange, row_id)
            obj.summary = normalize_scraped_text(obj.summary)
            done += 1
            if done % BATCH == 0:
                db.commit()
        db.commit()
        print(f"Aplicado: {done} filas actualizadas.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
