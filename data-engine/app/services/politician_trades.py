"""Operaciones de politicos (Camara de EE. UU., PTR del STOCK Act): ingesta y lecturas.

Sin migracion: cada PTR es una fila de ``documents`` (source_type
``house_ptr``, sin empresa) con la declaracion parseada en ``metadata``:
miembro, estado/distrito, partido, fecha de presentacion, enlace al PDF y
sus filas. Inmutable por DocID (un PTR enmendado tiene su propio DocID).

Todas las cifras salen de aqui y son deterministas: retraso = dias entre la
operacion y la presentacion por encima de los 45 del STOCK Act; «a tiempo» =
retraso 0; el importe es el rango declarado (la ley no pide la cifra exacta).

Senado (efdsearch.senate.gov): su CDN responde 403 a la aceptacion de las
condiciones desde un programa, asi que no se automatiza. Ejecutivo (OGE
278-T): sin descarga masiva gratuita. Ambos quedan fuera y se dice.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import Document
from app.services.connectors import house_ptr

logger = logging.getLogger(__name__)

SOURCE_TYPE = "house_ptr"
SOURCE_LABEL = "Clerk of the House · Periodic Transaction Reports (STOCK Act)"
LATE_OVER_30 = 30
LEGISLATORS_URL = "https://unitedstates.github.io/congress-legislators/legislators-current.json"
PARTY_LABELS = {"Democrat": "D", "Republican": "R", "Independent": "I"}


def _stored_doc_ids(db: Session, tenant_id: int | None) -> set[str]:
    rows = db.execute(
        select(Document.metadata_["doc_id"].as_string()).where(
            Document.source_type == SOURCE_TYPE,
            Document.tenant_id.is_(None) if tenant_id is None else Document.tenant_id == tenant_id,
        )
    ).all()
    return {str(r[0]) for r in rows if r[0]}


def _name_tokens(value: Any) -> set[str]:
    """Apellido sin tildes y por palabras: «Sánchez» = «Sanchez», «McClain Delaney» ~ «Delaney»."""
    plain = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return {token for token in re.split(r"[^a-z]+", plain) if len(token) >= 3}


def house_party_map(payload: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """(estado+distrito) -> partido y bioguide de los representantes actuales."""
    out: dict[str, dict[str, Any]] = {}
    for person in payload:
        terms = person.get("terms") or []
        if not terms:
            continue
        term = terms[-1]
        if term.get("type") != "rep":
            continue
        district = term.get("district")
        key = f"{term.get('state', '')}{int(district):02d}" if isinstance(district, int) else str(term.get("state", ""))
        if district == 0:
            key = f"{term.get('state', '')}00"
        out[key] = {
            "party": PARTY_LABELS.get(term.get("party", ""), term.get("party")),
            "bioguide": (person.get("id") or {}).get("bioguide"),
            "last": (person.get("name") or {}).get("last"),
        }
    return out


def fetch_party_map(client: httpx.Client | None = None) -> dict[str, dict[str, Any]]:
    """Lista publica (dominio publico) de unitedstates/congress-legislators."""
    try:
        if client is not None:
            response = client.get(LEGISLATORS_URL)
        else:
            with httpx.Client(timeout=30, follow_redirects=False) as owned:
                response = owned.get(LEGISLATORS_URL)
        response.raise_for_status()
        return house_party_map(response.json())
    except Exception as exc:  # noqa: BLE001 - sin partido no se cae la ingesta
        logger.warning("congress-legislators no disponible: %s", type(exc).__name__)
        return {}


def build_record(index_row: dict[str, Any], parsed: dict[str, Any] | None, party: dict[str, Any] | None) -> dict[str, Any]:
    filed = index_row.get("filing_date")
    trades = []
    for trade in (parsed or {}).get("trades", []):
        late = house_ptr.days_late(trade.get("tx_date"), filed)
        trades.append({**trade, "days_late": late})
    party = party or {}
    party_last = _name_tokens(party.get("last"))
    party_matches = bool(party) and (not party_last or bool(party_last & _name_tokens(index_row.get("last"))))
    name = " ".join(p for p in (index_row.get("first"), index_row.get("last"), index_row.get("suffix")) if p)
    return {
        "doc_id": index_row["doc_id"],
        "year": index_row.get("year"),
        "chamber": "house",
        "member": name or (parsed or {}).get("member"),
        "member_key": f"house:{index_row.get('state_district')}:{index_row.get('last', '').lower()}",
        "last": index_row.get("last"),
        "first": index_row.get("first"),
        "state": index_row.get("state"),
        "district": index_row.get("district"),
        "state_district": index_row.get("state_district"),
        "party": party.get("party") if party_matches else None,
        "bioguide": party.get("bioguide") if party_matches else None,
        "filing_date": filed,
        "source_url": index_row.get("source_url"),
        "electronic": bool(index_row.get("electronic")),
        "readable": parsed is not None,
        "trades": trades,
        "unparsed_blocks": (parsed or {}).get("unparsed_blocks", 0),
        "parser_version": house_ptr.PARSER_VERSION,
    }


def ingest_year(
    db: Session,
    year: int,
    *,
    tenant_id: int | None = None,
    max_new: int = 120,
    client: httpx.Client | None = None,
    index_rows: list[dict[str, Any]] | None = None,
    pdf_fetcher=None,
    party_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Guarda los PTR del ano que aun no estan. Acotado por ``max_new`` PDFs."""
    effective_tenant = tenant_id if tenant_id is not None else db.info.get("tenant_id")
    rows = index_rows if index_rows is not None else house_ptr.fetch_index(year, client)
    known = _stored_doc_ids(db, effective_tenant)
    parties = party_map if party_map is not None else fetch_party_map()
    stats = {"year": year, "index_ptrs": len(rows), "new": 0, "scanned": 0, "trades": 0, "errors": []}
    budget = max_new
    # Mas recientes primero: lo nuevo llega antes que el atraso historico.
    for row in sorted(rows, key=lambda r: (r.get("filing_date") or "", r["doc_id"]), reverse=True):
        if row["doc_id"] in known:
            continue
        parsed = None
        checksum = None
        if row.get("electronic"):
            if budget <= 0:
                continue
            budget -= 1
            try:
                pdf = pdf_fetcher(row) if pdf_fetcher else house_ptr.fetch_ptr_pdf(row["year"] or year, row["doc_id"], client)
                checksum = hashlib.sha256(pdf).hexdigest()
                parsed = house_ptr.parse_ptr_text(house_ptr.pdf_text(pdf))
            except Exception as exc:  # noqa: BLE001 - best-effort por PTR
                stats["errors"].append(f"{row['doc_id']}: {type(exc).__name__}")
                continue
        else:
            # PTR en papel escaneado: la cuadricula de importes no se lee de forma
            # fiable por OCR; se guarda la declaracion (quien, cuando, enlace) sin filas.
            stats["scanned"] += 1
        record = build_record(row, parsed, parties.get(row.get("state_district") or ""))
        published = None
        if record["filing_date"]:
            published = datetime.combine(date.fromisoformat(record["filing_date"]), datetime.min.time(), tzinfo=UTC)
        db.add(Document(
            tenant_id=effective_tenant,
            company_id=None,
            title=f"PTR {record['member']} ({record['state_district']}) {record['filing_date'] or ''}".strip()[:400],
            source_type=SOURCE_TYPE,
            source_url=record["source_url"],
            published_at=published,
            checksum=checksum,
            metadata_=record,
        ))
        known.add(row["doc_id"])
        stats["new"] += 1
        stats["trades"] += len(record["trades"])
    db.commit()
    return stats


# --- lecturas -------------------------------------------------------------------

def _records(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Document.metadata_).where(
            Document.source_type == SOURCE_TYPE,
            *tenant_filters(db, Document),
        )
    ).all()
    return [dict(r) for r in rows if isinstance(r, dict)]


def _flat_trades(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for rec in records:
        for trade in rec.get("trades") or []:
            out.append({
                **trade,
                "member": rec.get("member"),
                "member_key": rec.get("member_key"),
                "chamber": rec.get("chamber"),
                "state_district": rec.get("state_district"),
                "party": rec.get("party"),
                "filing_date": rec.get("filing_date"),
                "doc_id": rec.get("doc_id"),
                "source_url": rec.get("source_url"),
            })
    return out


def _member_card(key: str, recs: list[dict[str, Any]]) -> dict[str, Any]:
    trades = _flat_trades(recs)
    dated = [t for t in trades if t.get("days_late") is not None]
    late = [t for t in dated if (t["days_late"] or 0) > 0]
    late30 = [t for t in dated if (t["days_late"] or 0) > LATE_OVER_30]
    tickers = Counter(t["ticker"] for t in trades if t.get("ticker"))
    last_trade = max((t["tx_date"] for t in trades if t.get("tx_date")), default=None)
    head = max(recs, key=lambda r: r.get("filing_date") or "")
    vol_min = sum(int(t.get("amount_min") or 0) for t in trades)
    open_ended = any(t.get("amount_min") is not None and t.get("amount_max") is None for t in trades)
    vol_max = None if open_ended else sum(int(t.get("amount_max") or 0) for t in trades)
    return {
        "member_key": key,
        "member": head.get("member"),
        "chamber": head.get("chamber"),
        "state": head.get("state"),
        "district": head.get("district"),
        "state_district": head.get("state_district"),
        "party": head.get("party"),
        "bioguide": head.get("bioguide"),
        "filings": len(recs),
        "scanned_filings": sum(1 for r in recs if not r.get("readable")),
        "trades": len(trades),
        "tickers": len(tickers),
        "top_tickers": [{"ticker": t, "trades": n} for t, n in sorted(tickers.items(), key=lambda kv: (-kv[1], kv[0]))[:5]],
        "last_trade": last_trade,
        "last_filing": head.get("filing_date"),
        "late": len(late),
        "late_over_30": len(late30),
        "on_time_pct": round((len(dated) - len(late)) / len(dated) * 100, 1) if dated else None,
        "volume_min": vol_min,
        "volume_max": vol_max,
    }


SORTS = {
    "trades": lambda c: (-c["trades"], c["member"] or ""),
    "late": lambda c: (-(c["late"]), c["member"] or ""),
    "on_time": lambda c: (-(c["on_time_pct"] if c["on_time_pct"] is not None else -1), c["member"] or ""),
}


def politicians(
    db: Session,
    *,
    chamber: str = "all",
    party: str | None = None,
    sort: str = "trades",
    query: str | None = None,
    limit: int = 60,
    offset: int = 0,
) -> dict[str, Any]:
    records = _records(db)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        grouped.setdefault(str(rec.get("member_key")), []).append(rec)
    cards = [_member_card(k, v) for k, v in grouped.items()]
    if chamber != "all":
        cards = [c for c in cards if c["chamber"] == chamber]
    if party:
        cards = [c for c in cards if (c["party"] or "") == party.upper()]
    if query:
        q = query.strip().lower()
        cards = [c for c in cards if q in (c["member"] or "").lower() or q == (c["state"] or "").lower()]
    if sort == "recent":
        cards.sort(key=lambda c: c["member"] or "")
        cards.sort(key=lambda c: c["last_trade"] or "", reverse=True)
    else:
        cards.sort(key=SORTS.get(sort, SORTS["trades"]))
    years = sorted({int(r["year"]) for r in records if r.get("year")})
    return {
        "source": SOURCE_LABEL,
        "chambers": {"house": "ok", "senate": "no_disponible", "executive": "no_disponible"},
        "coverage": {"years": years, "filings": len(records), "scanned_filings": sum(1 for r in records if not r.get("readable"))},
        "rules": {"stock_act_due_days": house_ptr.STOCK_ACT_DUE_DAYS, "late_over_days": LATE_OVER_30},
        "total": len(cards),
        "politicians": cards[offset: offset + limit],
    }


def ticker_trades(db: Session, ticker: str, *, limit: int = 200) -> dict[str, Any]:
    wanted = ticker.strip().upper()
    trades = [t for t in _flat_trades(_records(db)) if (t.get("ticker") or "").upper() == wanted]
    trades.sort(key=lambda t: (t.get("tx_date") or "", t.get("doc_id") or ""), reverse=True)
    by_member: dict[str, dict[str, Any]] = {}
    for t in trades:
        slot = by_member.setdefault(str(t["member_key"]), {
            "member_key": t["member_key"], "member": t["member"], "party": t["party"],
            "state_district": t["state_district"], "buys": 0, "sells": 0, "last_trade": None,
        })
        if t.get("type") == "P":
            slot["buys"] += 1
        elif str(t.get("type") or "").startswith("S"):
            slot["sells"] += 1
        if t.get("tx_date") and (slot["last_trade"] is None or t["tx_date"] > slot["last_trade"]):
            slot["last_trade"] = t["tx_date"]
    return {
        "ticker": wanted,
        "source": SOURCE_LABEL,
        "status": "ok" if trades else "sin_datos",
        "trades_total": len(trades),
        "buys": sum(1 for t in trades if t.get("type") == "P"),
        "sells": sum(1 for t in trades if str(t.get("type") or "").startswith("S")),
        "members": sorted(by_member.values(), key=lambda m: (m["last_trade"] or ""), reverse=True),
        "trades": trades[:limit],
    }


def member_detail(db: Session, member_key: str) -> dict[str, Any] | None:
    recs = [r for r in _records(db) if r.get("member_key") == member_key]
    if not recs:
        return None
    trades = _flat_trades(recs)
    trades.sort(key=lambda t: (t.get("tx_date") or "", t.get("doc_id") or ""), reverse=True)
    filings = sorted(
        ({"doc_id": r.get("doc_id"), "filing_date": r.get("filing_date"), "source_url": r.get("source_url"),
          "readable": r.get("readable"), "trades": len(r.get("trades") or [])} for r in recs),
        key=lambda f: f["filing_date"] or "", reverse=True,
    )
    return {**_member_card(member_key, recs), "source": SOURCE_LABEL, "trades_list": trades, "filings_list": filings}
