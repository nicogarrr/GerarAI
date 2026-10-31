"""Material oficial de un evento de resultados, emparejado con su filing real de la SEC.

Usa ``SECClient`` (identidad/User-Agent configurada, ritmo compartido, cache y mirror
existentes). Solo se enlaza el documento presentado a la SEC; no se copia ni resume.

Reglas (comprobadas con 8-K reales de TSLA, META y ASTS el 21-oct-2026):
- Un 8-K con Item 2.02 no siempre es un resultado trimestral (Tesla presenta un 2.02
  con produccion y entregas el dia 2 del trimestre): se empareja por ventana de fechas
  del evento (presentado entre D y D+2), no por "el ultimo 2.02".
- EX-99.1/99.2 no dicen si es nota o presentacion (Tesla trae el deck en 99.1, META solo
  la nota, ASTS nota en 99.1 y deck en 99.2): se clasifica por el encabezado real.
- Solo se enlaza un documento si su propio texto confirma el periodo del evento; si lo
  contradice o no lo confirma, ante la duda no hay enlace.
- Estados: ``ok``, ``sin_filing`` (leido bien, emisor domestico, nada en D..D+2),
  ``no_disponible`` (fallo de red/SEC: NO es ausencia), ``sin_cobertura_sec`` (emisor
  extranjero, ticker sin CIK o fecha estimada) y ``periodo_no_coincide``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, timedelta
from html import unescape
from typing import Any

logger = logging.getLogger(__name__)

HISTORY_DAYS = 7
MATCH_WINDOW_AFTER_DAYS = 2
MAX_EXHIBITS_PER_FILING = 4
MAX_EVENTS = 8
# < 15 s: el cliente del frontend corta a los 15 s; asi siempre llega un parcial y no un {} por abort.
TOTAL_BUDGET_S = 12.0
HEAD_BYTES = 32_768
HEAD_CHARS = 12_000
OK_TTL_S = 24 * 3600
MISS_TTL_S = 10 * 60

KIND_LABEL = {"nota_prensa": "Nota de resultados", "presentacion": "Presentación", "documento": "Documento SEC"}
_EXHIBIT_RE = re.compile(r"^EX-99(\.\d+)?$", re.IGNORECASE)
_PRESS_RE = re.compile(
    r"press release|\b(reports?|announces?|provides?|reported|announced)\b[^.]{0,160}\bresults\b"
    r"|\bresults\b[^.]{0,80}\b(quarter|fiscal)\b",
    re.IGNORECASE,
)
_DECK_RE = re.compile(
    r"presentation|slides|\bbusiness update\b|\bq[1-4]\s*\d{4}\s*update\b"
    r"|\b(first|second|third|fourth) quarter \d{4}\s*(update|presentation)\b",
    re.IGNORECASE,
)
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]
_ORDINALS = ["first", "second", "third", "fourth"]
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

# L2 Redis compartida entre workers y usuarios (misma frescura por estado que
# la L1: ok 24 h / miss 10 min). Sin ella cada worker de gunicorn frio repetia
# las llamadas a la SEC para los mismos eventos: /api/calendar/followed/materials
# media 2.346 ms en el barrido del piloto (2026-10-31). Fail-open siempre:
# Redis caido degrada a la L1 + SEC exactamente como antes.
_MATERIALS_REDIS_PREFIX = "cavaai:earnings-materials:"


def _materials_redis_key(key: str) -> str:
    return f"{_MATERIALS_REDIS_PREFIX}{key}"


def _materials_redis():
    """Cliente Redis del cache layer (backoff interno); None si no disponible."""
    try:
        from app.core.cache import _redis_client

        return _redis_client()
    except Exception:  # noqa: BLE001 - cache best-effort
        return None


def _redis_ttl_for(value: dict[str, Any]) -> int:
    return OK_TTL_S if value.get("status") == "ok" else MISS_TTL_S


def reset_cache() -> None:
    _cache.clear()


def _col(recent: dict[str, Any], name: str, index: int) -> Any:
    values = recent.get(name) or []
    return values[index] if index < len(values) else None


def _text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.IGNORECASE)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def is_foreign_private_issuer(submissions: dict[str, Any]) -> bool:
    forms = set(((submissions.get("filings") or {}).get("recent") or {}).get("form") or [])
    return bool(forms & {"6-K", "20-F", "40-F"}) and not (forms & {"8-K", "10-Q", "10-K"})


def pick_results_filing(submissions: dict[str, Any], event_date: date) -> dict[str, str] | None:
    """8-K con Item 2.02 presentado entre ``event_date`` y +2 dias (el mas cercano; 8-K gana a 8-K/A)."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    best: dict[str, str] | None = None
    last = event_date + timedelta(days=MATCH_WINDOW_AFTER_DAYS)
    for index, form in enumerate(recent.get("form") or []):
        if form not in ("8-K", "8-K/A"):
            continue
        items = [i.strip() for i in str(_col(recent, "items", index) or "").split(",")]
        if "2.02" not in items:
            continue
        try:
            filed = date.fromisoformat(str(_col(recent, "filingDate", index)))
        except ValueError:
            continue
        accession = str(_col(recent, "accessionNumber", index) or "")
        if not accession or not event_date <= filed <= last:
            continue
        if best is None or filed.isoformat() < best["filed_at"] or (
            filed.isoformat() == best["filed_at"] and form == "8-K"
        ):
            best = {"accession": accession, "filed_at": filed.isoformat(), "form": str(form)}
    return best


def parse_filing_index(html: str) -> list[dict[str, str]]:
    """Exhibits EX-99.x de ``<accession>-index.htm``: solo nombres simples .htm/.html/.pdf."""
    out: list[dict[str, str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.IGNORECASE):
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.IGNORECASE)]
        if len(cells) < 4 or not _EXHIBIT_RE.match(cells[3]):
            continue
        filename = cells[2].split(" ")[0] if cells[2] else ""
        if not filename or "/" in filename or not re.search(r"\.(htm|html|pdf)$", filename, re.IGNORECASE):
            continue
        out.append({"type": cells[3].upper(), "filename": filename})
    return out


def classify_exhibit(head_html: str) -> str:
    head = _text(head_html)[:420]
    if _PRESS_RE.search(head):
        return "nota_prensa"
    if _DECK_RE.search(head):
        return "presentacion"
    return "documento"


def check_period(doc_html: str, fiscal_label: str | None) -> str:
    """``confirmado`` / ``contradice`` / ``no_verificado`` frente al cierre del calendario ("Sep/2026")."""
    match = re.match(r"^([A-Za-z]{3})/(\d{4})$", fiscal_label or "")
    if not match:
        return "no_verificado"
    abbr = [m[:3] for m in _MONTHS]
    if match.group(1).lower() not in abbr:
        return "no_verificado"
    month_index = abbr.index(match.group(1).lower())
    year = match.group(2)
    month = _MONTHS[month_index]
    text = _text(doc_html)[:6000].lower()
    if re.search(rf"{month}\s+\d{{1,2}},?\s+{year}", text):
        return "confirmado"
    if month_index % 3 == 2:
        quarter = month_index // 3
        if re.search(rf"\b{_ORDINALS[quarter]} quarter,? (?:of )?{year}\b|\bq{quarter + 1}\s*{year}\b", text):
            return "confirmado"
    for ended in re.finditer(r"(?:quarter|period|months?)\s+(?:ended|ending)\s+([a-z]+)\s+\d{1,2},?\s+(\d{4})", text):
        if ended.group(1) in _MONTHS and (ended.group(1) != month or ended.group(2) != year):
            return "contradice"
    return "no_verificado"


def _result(status: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "filed_at": None, "filing_url": None, "documents": [], **extra}


async def resolve_materials(
    *, sec: Any, ticker: str, event_date: date, fiscal_label: str | None, confirmed: bool | None
) -> dict[str, Any] | None:
    """Materiales del evento. ``None`` = resultado incompleto que no debe memorizarse."""
    if confirmed is False:
        return _result("sin_cobertura_sec")
    try:
        cik = await sec.cik_for_ticker(ticker)
    except Exception as exc:  # noqa: BLE001 - fallo de transporte != ausencia
        logger.warning("materiales: cik %s fallo: %s", ticker, exc)
        return _result("no_disponible")
    if not cik:
        return _result("sin_cobertura_sec")
    try:
        submissions = await sec.submissions(cik)
    except Exception as exc:  # noqa: BLE001
        logger.warning("materiales: submissions %s fallo: %s", ticker, exc)
        return _result("no_disponible")
    # Reconstruccion parcial (EFTS) sin items/formas completos: no se puede afirmar nada.
    if not isinstance(submissions, dict) or submissions.get("_fallback"):
        return _result("no_disponible")
    if is_foreign_private_issuer(submissions):
        return _result("sin_cobertura_sec")
    filing = pick_results_filing(submissions, event_date)
    if filing is None:
        return _result("sin_filing")
    base = sec.filing_index_url(cik, filing["accession"])
    index_url = f"{base}{filing['accession']}-index.htm"
    try:
        raw, _ = await sec.filing_document(index_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("materiales: indice %s fallo: %s", index_url, exc)
        return _result("no_disponible", filed_at=filing["filed_at"], filing_url=index_url)
    documents: list[dict[str, str]] = []
    incomplete = False
    for exhibit in parse_filing_index(raw.decode("utf-8", "replace"))[:MAX_EXHIBITS_PER_FILING]:
        url = f"{base}{exhibit['filename']}"
        try:
            doc = await sec.filing_document_head(url, HEAD_BYTES)
        except Exception as exc:  # noqa: BLE001
            logger.warning("materiales: exhibit %s fallo: %s", url, exc)
            incomplete = True
            continue
        head = doc.decode("utf-8", "replace")[:HEAD_CHARS]
        # Sin el periodo confirmado en el texto del propio documento, ante la duda no se enlaza.
        if check_period(head, fiscal_label) != "confirmado":
            continue
        kind = classify_exhibit(head)
        documents.append({"kind": kind, "label": KIND_LABEL[kind], "exhibit": exhibit["type"], "url": url})
    if incomplete and not documents:
        return None
    if not documents:
        return _result("periodo_no_coincide", filed_at=filing["filed_at"], filing_url=index_url)
    return _result("ok", filed_at=filing["filed_at"], filing_url=index_url, documents=documents)


async def materials_for_events(events: list[dict[str, Any]], today: date, *, sec: Any) -> dict[str, dict[str, Any]]:
    """Resuelve (con cache) el material de eventos ya ocurridos; nunca excede ``TOTAL_BUDGET_S``."""
    due = [
        e for e in events
        if today - timedelta(days=HISTORY_DAYS) <= date.fromisoformat(e["date"]) <= today
    ][:MAX_EVENTS]
    out: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    now = time.monotonic()
    redis_client = _materials_redis()
    for event in due:
        key = f"{event['ticker']}|{event['date']}"
        hit = _cache.get(key)
        if hit and now - hit[0] < (OK_TTL_S if hit[1]["status"] == "ok" else MISS_TTL_S):
            out[key] = hit[1]
            continue
        redis_hit = None
        redis_age_s = 0.0
        if redis_client is not None:
            rkey = _materials_redis_key(key)
            try:
                raw = redis_client.get(rkey)
                redis_hit = json.loads(raw) if raw else None
            except Exception:  # noqa: BLE001 - fail-open a la resolucion
                redis_hit = None
            if redis_hit is not None:
                # PTTL: la L1 hereda la EDAD de la entrada de Redis. Sin esto,
                # rehidratar reinicia la frescura y un miss llega a 10+10 min.
                try:
                    pttl_ms = redis_client.pttl(rkey)
                    if pttl_ms and pttl_ms > 0:
                        redis_age_s = max(
                            0.0, _redis_ttl_for(redis_hit) - pttl_ms / 1000.0
                        )
                except Exception:  # noqa: BLE001 - sin PTTL, frescura actual
                    redis_age_s = 0.0
        if redis_hit is not None:
            out[key] = redis_hit
            # Rehidrata la L1 del worker conservando el TTL restante de L2.
            _cache[key] = (now - redis_age_s, redis_hit)
        else:
            pending.append(event)

    async def one(event: dict[str, Any]) -> None:
        key = f"{event['ticker']}|{event['date']}"
        value = await resolve_materials(
            sec=sec, ticker=event["ticker"], event_date=date.fromisoformat(event["date"]),
            fiscal_label=event.get("fiscal_label"), confirmed=event.get("confirmed"),
        )
        if value is None:
            return
        out[key] = value
        _cache[key] = (time.monotonic(), value)
        if redis_client is not None:
            try:
                redis_client.setex(_materials_redis_key(key), _redis_ttl_for(value), json.dumps(value))
            except Exception:  # noqa: BLE001 - no cachear nunca rompe la lectura
                logger.warning("materials cache: escritura Redis fallo; se sirve sin cache", exc_info=True)

    if pending:
        tasks = [asyncio.create_task(one(e)) for e in pending]
        _, not_done = await asyncio.wait(tasks, timeout=TOTAL_BUDGET_S)
        for task in not_done:
            task.cancel()
    return dict(out)
