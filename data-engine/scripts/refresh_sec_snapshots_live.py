"""Re-descarga los snapshots locales de companyfacts desde SEC live.

Los snapshots horneados en la imagen (data/sec_snapshots/companyfacts/)
se construyeron desde un parquet espejo que perdia la columna `start`:
sin fecha de inicio no hay duracion verificable y el filtro anti-segmentos
de financial_ingestion (300-380 dias para hechos anuales) quedaba vencido
(F28). Este script re-descarga cada CIK desde data.sec.gov con el
User-Agent declarado, pacing fair-access y escritura atomica.

Uso (dentro del contenedor backend o con httpx disponible):
    PYTHONPATH=/app python3 /app/scripts/refresh_sec_snapshots_live.py
    PYTHONPATH=/app python3 /app/scripts/refresh_sec_snapshots_live.py --resume-hours 2

Tras completar, persistir en el host (la imagen hornea ese directorio):
    docker cp cavaai-backend:/app/data/sec_snapshots/companyfacts/. \\
        ~/GerarAI/data-engine/data/sec_snapshots/companyfacts/
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

_BASE_DIR = Path(os.environ.get("SEC_SNAPSHOT_DIR", "/app/data/sec_snapshots"))
# Layout oficial: $SEC_SNAPSHOT_DIR/companyfacts/CIK##########.json
SNAPSHOT_DIR = (
    _BASE_DIR / "companyfacts" if (_BASE_DIR / "companyfacts").is_dir() else _BASE_DIR
)
BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"
PACE_SECONDS = 0.12  # ~8 req/s, por debajo del fair-access de la SEC (10/s)
TIMEOUT = 60.0
MAX_ATTEMPTS = 4


def _user_agent() -> str:
    try:
        from app.core.config import Settings

        return Settings().sec_user_agent
    except Exception:
        return os.environ.get("SEC_USER_AGENT", "GerarAI research contact@gerarai.local")


async def _fetch_one(
    client: httpx.AsyncClient, cik: str, dest: Path, sem: asyncio.Semaphore
) -> str:
    url = f"{BASE_URL}/{cik}.json"
    tmp = dest.with_suffix(".json.tmp")
    async with sem:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.get(url)
                if response.status_code == 404:
                    return "missing"
                if response.status_code in (429, 500, 502, 503):
                    await asyncio.sleep(2**attempt)
                    continue
                response.raise_for_status()
                tmp.write_bytes(response.content)
                os.replace(tmp, dest)
                return "ok"
            except (httpx.HTTPError, OSError):
                await asyncio.sleep(2**attempt)
        if tmp.exists():
            tmp.unlink()
        return "failed"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume-hours",
        type=float,
        default=0,
        help="Saltar CIKs cuyo snapshot tenga menos de N horas (0 = re-descargar todo).",
    )
    parser.add_argument(
        "--only", nargs="*", default=None, help="Limitar a CIKs concretos (pruebas)."
    )
    args = parser.parse_args()

    files = sorted(SNAPSHOT_DIR.glob("CIK*.json"))
    ciks = [f.stem for f in files]
    if args.only:
        wanted = set(args.only)
        ciks = [c for c in ciks if c in wanted]
    if args.resume_hours > 0:
        cutoff = time.time() - args.resume_hours * 3600
        before = len(ciks)
        ciks = [
            c
            for c in ciks
            if (SNAPSHOT_DIR / f"{c}.json").stat().st_mtime < cutoff
        ]
        print(f"resume: saltados {before - len(ciks)} CIKs frescos", flush=True)

    total = len(ciks)
    print(f"snapshots a refrescar: {total} (UA: {_user_agent()!r})", flush=True)
    counts = {"ok": 0, "missing": 0, "failed": 0}
    failures: list[str] = []
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(
        headers={"User-Agent": _user_agent()}, timeout=TIMEOUT
    ) as client:
        for index, cik in enumerate(ciks, 1):
            result = await _fetch_one(client, cik, SNAPSHOT_DIR / f"{cik}.json", sem)
            counts[result] += 1
            if result == "failed":
                failures.append(cik)
            if index % 100 == 0 or index == total:
                print(
                    f"{index}/{total} ok={counts['ok']} missing={counts['missing']} failed={counts['failed']}",
                    flush=True,
                )
            await asyncio.sleep(PACE_SECONDS)
    print(f"RESUMEN: {counts}", flush=True)
    if failures:
        print(f"CIKs fallidos: {','.join(failures[:50])}", flush=True)
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
