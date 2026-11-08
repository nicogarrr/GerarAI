"""Historial de la guía reconstruido desde los 8-K antiguos de EDGAR (gratis, sin clave).

Para medir cuánto bate (o falla) una empresa su propia guía no hace falta esperar años:
se pasa el extractor determinista de #4749 (:func:`company_guidance.extract_guidance`)
por las notas de resultados (8-K con el punto 2.02, anexo EX-99.1) de los últimos
``YEARS`` años. Cada previsión queda como fila HISTÓRICA de ``declared_input_values``
(``guidance.<métrica>.<periodo>``, ``superseded_at`` = la fecha del documento siguiente
con la misma clave, o la de la reconstrucción), con su URL, fecha y cita, sin tocar la
fila vigente. Así ``own_consensus.guidance_beat`` y :mod:`estimate_accuracy` la ven
congelada en su fecha: solo cuenta la guía emitida antes del cierre del periodo.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from app.services.company_guidance import EXTRACTOR_VERSION, extract_guidance

YEARS = 6
MAX_FILINGS = 40
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_EX991 = re.compile(r'<a href="(/Archives/edgar/data/[^"]+\.htm)">[^<]*</a>\s*</td>\s*<td scope="row">'
                    r"(EX-99\.1|EX-99|EX-99\.01)</td>", re.I)


def html_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", ". ", text)
    text = _TAG.sub(" ", text)
    for a, b in (("&nbsp;", " "), ("&#160;", " "), ("&amp;", "&"), ("&#8217;", "'"), ("&#8211;", "–"),
                 ("&#8212;", "—"), ("&#36;", "$"), ("&#8220;", '"'), ("&#8221;", '"')):
        text = text.replace(a, b)
    return _WS.sub(" ", text)


def earnings_8ks(submissions: dict[str, Any], *, since: date, older: Sequence[dict[str, Any]] = ()
                 ) -> list[dict[str, Any]]:
    """8-K con punto 2.02 (resultados) desde ``since``, del más antiguo al más nuevo.

    ``older``: las páginas antiguas del mismo emisor (``filings.files``), con las mismas columnas."""
    out: list[dict[str, Any]] = []
    for page in [(submissions.get("filings") or {}).get("recent") or {}, *older]:
        out.extend(_earnings_rows(page, since))
    unique = {f["accession"]: f for f in out}
    return sorted(unique.values(), key=lambda f: f["filed"])[-MAX_FILINGS:]


def _earnings_rows(recent: dict[str, Any], since: date) -> list[dict[str, Any]]:
    out = []
    for i, accn in enumerate(recent.get("accessionNumber") or []):
        form = (recent.get("form") or [""])[i] if i < len(recent.get("form") or []) else ""
        items = str((recent.get("items") or [""])[i] if i < len(recent.get("items") or []) else "")
        filed = (recent.get("filingDate") or [""])[i] if i < len(recent.get("filingDate") or []) else ""
        if form != "8-K" or "2.02" not in items or not filed:
            continue
        d = date.fromisoformat(filed)
        if d >= since:
            out.append({"accession": accn, "filed": d})
    return out


def ex991_url(index_html: str) -> str | None:
    m = _EX991.search(index_html)
    return f"https://www.sec.gov{m.group(1)}" if m else None


def backfill_rows(docs: list[tuple[date, str, str]]) -> list[dict[str, Any]]:
    """``(fecha, url, texto)`` del más antiguo al más nuevo → filas históricas por clave,
    cada una vigente hasta el documento siguiente que trae la misma clave. Puro."""
    seen: dict[str, list[dict[str, Any]]] = {}
    for published, url, text in sorted(docs, key=lambda d: d[0]):
        best: dict[str, Any] = {}
        for g in extract_guidance(text, published=published):
            best.setdefault(g.input_key, g)
        for key, g in best.items():
            seen.setdefault(key, []).append({"key": key, "item": g, "published": published, "url": url})
    rows: list[dict[str, Any]] = []
    for revisions in seen.values():
        for i, rev in enumerate(revisions):
            nxt = revisions[i + 1]["published"] if i + 1 < len(revisions) else None
            rows.append({**rev, "superseded": nxt})
    return rows


def fetch_documents(cik: str | int, *, today: date | None = None, get_text: Any = None) -> dict[str, Any]:
    """Descarga las notas de resultados de ``YEARS`` años (ritmo y UA de la SEC del conector)."""
    from app.services.connectors import form4
    from app.services.connectors.edgar_common import SUBMISSIONS_URL, filing_index_url

    today = today or date.today()
    get = get_text or (lambda url: form4._get_text(url, None))  # noqa: SLF001 - mismo ritmo y UA que Form 4
    import json

    since = date(today.year - YEARS, 1, 1)
    sub = json.loads(get(SUBMISSIONS_URL.format(cik=str(int(str(cik))).zfill(10))))
    older = []
    for page in (sub.get("filings") or {}).get("files") or []:
        if str(page.get("filingTo") or "") >= since.isoformat() and page.get("name"):
            older.append(json.loads(get(f"https://data.sec.gov/submissions/{page['name']}")))
    filings = earnings_8ks(sub, since=since, older=older)
    docs: list[tuple[date, str, str]] = []
    misses = 0
    for f in filings:
        try:
            index = get(filing_index_url(cik, f["accession"]) + f"{f['accession']}-index.htm")
            url = ex991_url(index)
            if url is None:
                misses += 1
                continue
            docs.append((f["filed"], url, html_text(get(url))))
        except Exception:  # noqa: BLE001 - un 8-K ilegible no para los demás
            misses += 1
    return {"filings": len(filings), "documents": docs, "misses": misses}


def store_backfill(db: Any, company: Any, tenant_id: int, rows: list[dict[str, Any]], *,
                   now: datetime | None = None) -> dict[str, Any]:
    """Guarda las filas como históricas (nunca toca la vigente) y sin duplicar."""
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue
    from app.services.declared_input_service import DeclaredInput, DeclaredInputService

    now = now or datetime.now(UTC)
    service = DeclaredInputService()
    existing = {(r.input_key, r.as_of) for r in db.scalars(select(DeclaredInputValue).where(
        DeclaredInputValue.tenant_id == tenant_id, DeclaredInputValue.company_id == company.id,
        DeclaredInputValue.input_key.like("guidance.%"))).all()}
    stored = 0
    for row in rows:
        g = row["item"]
        if (row["key"], row["published"]) in existing:
            continue
        item = DeclaredInput(input_key=row["key"], segment_key="", low=g.low, base=g.base, high=g.high,
                             unit=g.currency if g.metric != "eps" else f"{g.currency}/share", method="extract",
                             source_url=row["url"], source_quote=g.quote, as_of=row["published"],
                             metadata={"kind": "company_guidance", "metric": g.metric, "period": g.period,
                                       "period_read": g.period_read, "extractor": EXTRACTOR_VERSION,
                                       "backfill": True})
        if service.validate(item):
            continue
        sup = row["superseded"]
        db.add(DeclaredInputValue(
            tenant_id=tenant_id, company_id=company.id, input_key=item.input_key, segment_key="",
            low=item.low, base=item.base, high=item.high, unit=item.unit, status=item.status, method=item.method,
            source_url=item.source_url, source_quote=item.source_quote, as_of=item.as_of,
            superseded_at=datetime(sup.year, sup.month, sup.day, tzinfo=UTC) if sup else now,
            metadata_=dict(item.metadata)))
        stored += 1
    db.flush()
    return {"stored": stored, "rows": len(rows)}


def ensure_backfill(db: Any, company: Any, tenant_id: int, *, today: date | None = None,
                    fetch: Any = None) -> dict[str, Any]:
    """Reconstruye el historial UNA vez por empresa (si ya hay filas de backfill, no hace nada)."""
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue

    cik = (getattr(company, "cik", None) or "").strip()
    if not cik.isdigit():
        return {"status": "skipped", "reason": "sin CIK de la SEC"}
    rows = db.scalars(select(DeclaredInputValue.metadata_).where(
        DeclaredInputValue.tenant_id == tenant_id, DeclaredInputValue.company_id == company.id,
        DeclaredInputValue.input_key.like("guidance.%"), DeclaredInputValue.superseded_at.is_not(None))).all()
    if any((m or {}).get("backfill") for m in rows):
        return {"status": "done_before"}
    got = (fetch or fetch_documents)(cik, today=today)
    result = store_backfill(db, company, tenant_id, backfill_rows(got["documents"]))
    return {"status": "ok", "filings": got["filings"], "documents": len(got["documents"]), **result}
