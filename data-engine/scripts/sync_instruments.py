"""Seed idempotente de instrument_references desde FinanceDatabase.

Fuente: FinanceDatabase (MIT, 300k+ simbolos, CSVs comunitarios):
  https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/database/equities/<EXCHANGE>.csv
Fecha del snapshot: la de descarga (se guarda en `as_of` y se reporta);
  el dump vive en data-engine/data/ (ignorado por .gitignore, viaja como
  volumen, nunca se commitea).

Normalizacion: symbol -> ticker_normalized (strip+upper, con punto intacto:
"BRK.B" nunca se toca); celdas vacias o placeholders ("nan", "Unknown") ->
NULL (fuente sin dato, nunca un default inventado). Opcionalmente
--enrich-openfigi rellena FIGI via OpenFIGI (25 req/min sin key, key gratis
opcional en OPENFIGI_API_KEY) solo para filas sin FIGI.

Uso:
    python scripts/sync_instruments.py --exchanges NMS NYQ PAR --limit 500
    python scripts/sync_instruments.py --csv tests/fixtures/instruments/equities_sample.csv --dry-run
    python scripts/sync_instruments.py --exchanges NMS --enrich-openfigi --limit 50

Idempotente: re-ejecutar inserta lo nuevo y actualiza lo cambiado; reporta
inserted/updated/skipped.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.services.instrument_reference import normalize_row, upsert_rows  # noqa: E402

FINANCEDATABASE_EQUITIES_BASE_URL = (
    "https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/database/equities"
)
DEFAULT_EXCHANGES = ["NMS", "NYQ", "PAR", "AMS", "MCE", "LSE"]


def download_csv(url: str, dest: Path, timeout_seconds: float = 60.0) -> Path:
    """Descarga un CSV a dest (crea el directorio). El dump nunca se commitea."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=timeout_seconds, follow_redirects=True) as response:
        response.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in response.iter_bytes(chunk_size=65536):
                fh.write(chunk)
    return dest


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def normalize_csv_rows(raw_rows: list[dict], *, as_of: date, source: str) -> tuple[list[dict], int]:
    """Normaliza filas crudas; devuelve (validas, skipped_sin_ticker)."""
    valid: list[dict] = []
    skipped = 0
    for raw in raw_rows:
        row = normalize_row(raw, as_of=as_of, source=source)
        if row is None:
            skipped += 1
        else:
            valid.append(row)
    return valid, skipped


def enrich_figi_openfigi(
    rows: list[dict], *, api_key: str | None = None, requests_per_minute: int = 25
) -> int:
    """Rellena FIGI via OpenFIGI solo para filas sin FIGI pero con ISIN.

    Devuelve cuantas filas se enriquecieron. Respeta 25 req/min sin key y
    cachea por ISIN en memoria. Nunca inventa: si OpenFIGI no devuelve match
    unico, la fila queda como esta (FIGI NULL).
    """
    from app.services.connectors.openfigi import OpenFIGIConnector

    connector = OpenFIGIConnector(
        api_key=api_key, requests_per_minute=requests_per_minute
    )
    enriched = 0
    for row in rows:
        if row.get("figi") or not row.get("isin"):
            continue
        try:
            result = connector.map_identifier(row["isin"], id_type="ID_ISIN")
        except Exception:
            continue
        matches = result.get("matches") or []
        if result.get("status") == "matched" and len(matches) == 1:
            match = matches[0]
            if match.get("figi"):
                row["figi"] = str(match["figi"]).strip().upper()[:12]
                if match.get("compositeFIGI"):
                    row["composite_figi"] = str(match["compositeFIGI"]).strip().upper()[:12]
                if match.get("shareClassFIGI"):
                    row["shareclass_figi"] = str(match["shareClassFIGI"]).strip().upper()[:12]
                row["source"] = "financedatabase+openfigi"
                enriched += 1
    return enriched


def sync(
    *,
    exchanges: list[str] | None = None,
    csv_paths: list[Path] | None = None,
    data_dir: Path,
    as_of: date,
    limit: int | None = None,
    dry_run: bool = False,
    enrich_openfigi: bool = False,
    api_key: str | None = None,
) -> dict:
    """Descarga (o lee) + normaliza + upsert. Retorna estadisticas."""
    data_dir.mkdir(parents=True, exist_ok=True)
    per_file: list[dict] = []
    raw_rows: list[dict] = []
    if csv_paths:
        for path in csv_paths:
            rows = read_csv_rows(path)
            per_file.append({"file": str(path), "raw": len(rows)})
            raw_rows.extend(rows)
    else:
        for exchange in (exchanges or DEFAULT_EXCHANGES):
            url = f"{FINANCEDATABASE_EQUITIES_BASE_URL}/{exchange}.csv"
            dest = data_dir / f"equities_{exchange}.csv"
            download_csv(url, dest)
            rows = read_csv_rows(dest)
            per_file.append({"file": str(dest), "url": url, "raw": len(rows)})
            raw_rows.extend(rows)
    if limit is not None:
        raw_rows = raw_rows[:limit]
    valid, skipped_invalid = normalize_csv_rows(raw_rows, as_of=as_of, source="financedatabase")
    enriched = enrich_figi_openfigi(valid, api_key=api_key) if enrich_openfigi else 0
    if dry_run:
        return {
            "source_base_url": FINANCEDATABASE_EQUITIES_BASE_URL,
            "as_of": as_of.isoformat(),
            "files": per_file,
            "raw": len(raw_rows),
            "valid": len(valid),
            "skipped_invalid": skipped_invalid,
            "enriched_openfigi": enriched,
            "inserted": 0,
            "updated": 0,
            "dry_run": True,
        }
    init_db()
    db = SessionLocal()
    try:
        stats = upsert_rows(db, valid, commit=True)
    finally:
        db.close()
    return {
        "source_base_url": FINANCEDATABASE_EQUITIES_BASE_URL,
        "as_of": as_of.isoformat(),
        "files": per_file,
        "raw": len(raw_rows),
        "valid": len(valid),
        "skipped_invalid": skipped_invalid,
        "enriched_openfigi": enriched,
        **stats,
        "dry_run": False,
    }


DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "instruments"


def refresh_weekly() -> dict:
    """Refresco semanal sin argumentos para el scheduler (APScheduler llama sin args).

    Descarga los CSV por defecto de FinanceDatabase (1 GET por bolsa y
    semana, gratis) y upserta instrument_references de forma idempotente.
    OpenFIGI queda fuera a proposito: sin key son 25 req/min y el universo
    sin FIGI agotaria la cuota; el enriquecido sigue disponible manual con
    --enrich-openfigi y OPENFIGI_API_KEY.
    """
    return sync(data_dir=DEFAULT_DATA_DIR, as_of=date.today())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchanges", nargs="*", default=None)
    parser.add_argument("--csv", dest="csv_paths", nargs="*", default=None)
    parser.add_argument("--data-dir", default="data/instruments")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enrich-openfigi", action="store_true")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = Path(__file__).resolve().parent.parent / data_dir
    as_of = date.fromisoformat(args.as_of)
    csv_paths = [Path(p) for p in args.csv_paths] if args.csv_paths else None
    import os

    stats = sync(
        exchanges=args.exchanges,
        csv_paths=csv_paths,
        data_dir=data_dir,
        as_of=as_of,
        limit=args.limit,
        dry_run=args.dry_run,
        enrich_openfigi=args.enrich_openfigi,
        api_key=os.environ.get("OPENFIGI_API_KEY"),
    )
    print(
        f"[sync_instruments] fuente={stats['source_base_url']} as_of={stats['as_of']} "
        f"raw={stats['raw']} valid={stats.get('valid', 0)} "
        f"inserted={stats.get('inserted', 0)} updated={stats.get('updated', 0)} "
        f"skipped_invalid={stats.get('skipped_invalid', 0)} "
        f"enriched_openfigi={stats.get('enriched_openfigi', 0)} "
        f"dry_run={stats.get('dry_run', False)}"
    )
    for item in stats.get("files", []):
        print(f"  - {item.get('url', item.get('file'))} raw={item.get('raw')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
