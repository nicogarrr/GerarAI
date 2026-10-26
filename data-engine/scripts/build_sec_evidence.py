"""Descarga indice + documentos de filings SEC y escribe el manifiesto.

Se ejecuta desde una red que llegue a sec.gov (el VM de produccion no llega).
No ingiere nada: solo deja en --out los ficheros y un manifest.json con
SHA-256 del indice y de cada documento. La verificacion contra el indice la
hace scripts/ingest_sec_filings.py (app.services.sec_filing_evidence).

    python scripts/build_sec_evidence.py --out /tmp/asts \
        --filing 1780312:0001193125-26-342540:asts-20260810.htm:asts-ex99_1.htm:asts-ex99_2.htm
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

USER_AGENT = os.environ.get("SEC_USER_AGENT", "GerarAI research evidence (contact: owner-configured)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--filing", action="append", required=True,
                        help="CIK:ACCESSION:doc1.htm[:doc2.htm...]")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    submissions_cache: dict[str, tuple[str, str]] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=False) as client:
        for spec in args.filing:
            cik, accession, *docs = spec.split(":")
            folder = accession.replace("-", "")
            base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{folder}"
            index_name = f"index-{folder}.htm"
            index = client.get(f"{base}/{accession}-index.htm")
            index.raise_for_status()
            (out / index_name).write_bytes(index.content)
            if cik not in submissions_cache:
                sub = client.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
                sub.raise_for_status()
                sub_name = f"submissions-{int(cik):010d}.json"
                (out / sub_name).write_bytes(sub.content)
                submissions_cache[cik] = (sub_name, hashlib.sha256(sub.content).hexdigest())
                recent = sub.json()["filings"]["recent"]
            else:
                recent = json.loads((out / submissions_cache[cik][0]).read_bytes())["filings"]["recent"]
            primary = (
                recent["primaryDocument"][recent["accessionNumber"].index(accession)]
                if accession in recent["accessionNumber"]
                else None
            )
            for doc in docs:
                response = client.get(f"{base}/{doc}")
                response.raise_for_status()
                second = client.get(f"{base}/{doc}")
                second.raise_for_status()
                file_name = f"{folder}-{doc}"
                (out / file_name).write_bytes(response.content)
                entries.append({
                    "file": file_name,
                    "url": f"{base}/{doc}",
                    "index_file": index_name,
                    "index_url": f"{base}/{accession}-index.htm",
                    "index_sha256": hashlib.sha256(index.content).hexdigest(),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "bytes_served": len(response.content),
                    "capture": {
                        "fetched_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                        "host": "www.sec.gov",
                        "http_status": response.status_code,
                        "second_fetch_identical": second.content == response.content,
                        "last_modified": response.headers.get("last-modified"),
                        "submissions_file": submissions_cache[cik][0],
                        "submissions_sha256": submissions_cache[cik][1],
                        "is_primary_document": doc == primary,
                    },
                })
    (out / "manifest.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
    print(f"{len(entries)} documentos; manifiesto en {out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
