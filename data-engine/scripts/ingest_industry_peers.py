"""Ingesta por grupo de industria SIC: descubre en la SEC las cotizadas del grupo de un emisor (o de los códigos
dados) y crea/actualiza sus fichas con hechos SEC, precios y etiqueta ``sic:``. Sin lista de tickers.

Después guarda en cada ficha del grupo sus afines de negocio (``afin:<CIK>:<coseno>``, regla
«afinidad-negocio-v1»: descripción del 10-K/20-F de la SEC, dos peticiones por emisor). ``--affinity-only``
hace solo ese paso sobre las fichas que ya están en la base.

Uso: python scripts/ingest_industry_peers.py (--ticker ASTS | --sic 4899,3663,3760-3769) [--dry-run] [--max N]
     [--tenant N] [--affinity-only | --no-affinity]
"""
import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.entities import Company  # noqa: E402
from app.services import business_affinity as ba  # noqa: E402
from app.services import industry_peer_ingest as ipi  # noqa: E402
from app.services import sic_classification as sc  # noqa: E402
from app.services.connectors.sec_edgar import default_headers  # noqa: E402


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=default_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - https de la SEC
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip

                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise ipi.SecRefused(f"SEC {exc.code} en {url}") from exc
        raise


def _ranges(arg: str) -> tuple[tuple[int, int], ...]:
    out = []
    for part in arg.split(","):
        lo, _, hi = part.strip().partition("-")
        out.append((int(lo), int(hi or lo)))
    return tuple(out)


async def _ingest(db, row: dict) -> dict:
    from app.services.company_enrichment_service import ensure_company_stub
    from app.services.financial_ingestion_service import FinancialIngestionService
    from app.services.market_close_sync import backfill_company_history

    company = db.scalar(select(Company).where(Company.cik.in_([str(row["cik"]), str(row["cik"]).zfill(10)])))
    company = company or ensure_company_stub(db, row["ticker"])
    if not company.cik:
        company.cik = str(row["cik"]).zfill(10)
    if company.name in (None, "", company.ticker):
        company.name = row["name"]
    if str(company.exchange or "").upper() in ("", "UNKNOWN"):
        company.exchange = row["exchange"].upper()
    company.currency = company.currency or "USD"
    sc.tag_sic(company, row["sic"])
    db.commit()
    res = {"ticker": company.ticker, "sic": row["sic"]}
    try:
        r = await FinancialIngestionService().refresh_from_sec(db=db, company=company)
        db.commit()
        res["sec"] = r.get("status")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        res["sec"] = f"error: {type(exc).__name__}"
    try:
        res["prices"] = str(backfill_company_history(db, company, period="2y"))[:80]
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        res["prices"] = f"error: {type(exc).__name__}"
    return res


def _affinity(db, ranges) -> dict:
    """Afines de negocio de cada ficha del grupo (con CIK), por la descripción de su informe anual."""
    members = [c for c in db.scalars(select(Company).where(Company.cik.is_not(None))).all()
               if (s := sc.company_sic(c)) is not None and any(lo <= s <= hi for lo, hi in ranges)]
    docs: dict[int, list[str]] = {}
    missing: dict[str, str] = {}
    by_cik: dict[int, Company] = {}
    for c in members:
        try:
            cik = int(str(c.cik))
        except ValueError:
            continue
        by_cik[cik] = c
        d = ba.describe(cik, c.name, _get)  # SecRefused corta la pasada (sin reintentos)
        time.sleep(0.25)
        if d.get("tokens"):
            docs[cik] = d["tokens"]
        else:
            missing[c.ticker] = d.get("missing") or "sin texto"
    sets = ba.affine_sets(docs)
    changed = 0
    for cik, c in by_cik.items():
        changed += ba.tag_affine(c, sets.get(cik, []))
    db.commit()
    return {"rule": ba.RULE, "members": len(by_cik), "with_text": len(docs), "tagged": changed,
            "missing": missing}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--sic")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--tenant", type=int, help="tenant de la sesión (por defecto, el de SessionLocal)")
    ap.add_argument("--affinity-only", action="store_true", help="solo los afines de negocio de las fichas ya en base")
    ap.add_argument("--no-affinity", action="store_true", help="sin el paso de afines de negocio")
    a = ap.parse_args()
    db = SessionLocal()
    if a.tenant:
        db.info["tenant_id"] = a.tenant
    try:
        if a.sic:
            ranges = _ranges(a.sic)
        else:
            company = db.scalar(select(Company).where(Company.ticker == (a.ticker or "").upper()))
            sic = sc.company_sic(company) if company is not None else None
            if company is not None and sic is None and company.cik:
                sic, _desc = sc.sec_submissions_sic(company.cik)
                if sc.tag_sic(company, sic) and not a.dry_run:
                    db.commit()
            group = sc.industry_group(sic)
            ranges = group[1] if group else (((sic, sic),) if sic else ())
        if not ranges:
            print(json.dumps({"error": "sin SIC ni grupo"}))
            return
        if a.affinity_only:
            print(json.dumps(_affinity(db, ranges), ensure_ascii=False, indent=1, default=str))
            return
        tickers = json.loads(_get(ipi.TICKERS_URL))
        cands = ipi.group_candidates(ranges, _get, tickers, pause=lambda: time.sleep(0.15))
        out = {"ranges": ranges, "candidates": [c["ticker"] for c in cands], "ingested": []}
        if not a.dry_run:
            for row in cands[: a.max]:
                out["ingested"].append(asyncio.run(_ingest(db, row)))
                time.sleep(0.3)
            sc.fill_from_sic(db, companies=list(db.scalars(select(Company).where(
                Company.ticker.in_([c["ticker"] for c in cands]))).all()))
            db.commit()
            if not a.no_affinity:
                out["affinity"] = _affinity(db, ranges)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    except ipi.SecRefused as exc:
        db.rollback()
        print(json.dumps({"stopped": str(exc)}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
