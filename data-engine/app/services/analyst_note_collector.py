"""Recolector de notas de analista desde fuentes gratuitas (PR 2 de 2).

Feature aprobada por Nico (4-nov-2026): las notas de analista se rellenan solas,
sin fuentes de pago, para que la mezcla de analistas del equipo de expertos
lea argumentos y no solo precios objetivo. Dos fuentes, las dos ya alcanzables
por la app:

1. **Esqueleto Yahoo** (``upgrades_downgrades``, el mismo origen gratuito que
   #4543): firma, fecha, acción, rating anterior→nuevo y precio objetivo
   anterior→nuevo, más el cierre de ese día. Sin LLM. Queda como
   ``fragmento`` (no trae cita) con la URL de la página de análisis de Yahoo.
2. **Noticias ya ingeridas** del tenant (``news_events`` de la empresa): un LLM
   acotado (``ANALYST_NOTE_CONTRACT``) saca de titulares y resúmenes la casa,
   el analista, la acción, los ratings, los objetivos, los argumentos y una
   cita literal. Fail-closed por nota: se descarta si cita una noticia que no
   es de esta corrida, si la cita no aparece palabra por palabra en ella, si la
   casa no aparece en ella o si un número (objetivo, estimación…) no aparece
   en ella. JSON inválido → no se guarda nada de noticias. Un post de redes o
   de un foro va como ``social`` (el servicio lo deja «rumor/no verificado»).

Todo se guarda con :class:`AnalystNoteService` (idempotente, por tenant). Una
nota de noticia del mismo día ±3 que un esqueleto Yahoo de la misma casa se
fusiona con él (misma fecha y acción): la fila pasa a ``verificado`` y la URL
de Yahoo queda en ``links``.

Límites: cada llamada de red con tiempo máximo, a lo sumo
``YAHOO_MAX_RECORDS`` filas de Yahoo de los últimos ``YAHOO_LOOKBACK_DAYS``,
``NEWS_MAX_ITEMS`` noticias de ``NEWS_LOOKBACK_DAYS`` días, una llamada al LLM
(dos si el JSON no se puede leer) y ``MAX_EXTRACTED_NOTES`` notas. La parte LLM
solo corre con ``EXPERT_TEAM_ENABLED`` (presupuesto de LLM del equipo).
Nada por ticker: las mismas reglas para todas las empresas y tenants.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalystNote
from app.models.entities import Company, NewsEvent
from app.services.analyst_history_service import normalize_firm
from app.services.analyst_note_service import (
    AnalystNoteError,
    AnalystNoteInput,
    AnalystNoteService,
    normalize_action,
)
from app.services.analyst_yahoo import fetch_upgrades_downgrades_records
from app.services.inferred_input_service import is_valid_https_url

Reasoner = Callable[[str, str, int, str], Awaitable[str]]

YAHOO_SOURCE_URL = "https://finance.yahoo.com/quote/{symbol}/analysis/"
YAHOO_LOOKBACK_DAYS = 365
YAHOO_MAX_RECORDS = 200
FETCH_TIMEOUT_SECONDS = 20.0
NEWS_LOOKBACK_DAYS = 120
NEWS_MAX_ITEMS = 25
NEWS_TEXT_CHARS = 1500
MAX_EXTRACTED_NOTES = 40
MAX_ATTEMPTS = 2
LLM_MAX_TOKENS = 4000
LLM_TASK = "analyst_notes.extract"
PROMPT_VERSION = "analyst_note_extract.v1"
#: Una noticia y un esqueleto Yahoo de la misma casa a esta distancia son la misma nota.
SKELETON_MATCH_DAYS = 3
#: Señales genéricas (es/en) de que un titular habla de una nota de analista.
ANALYST_SIGNAL_WORDS: tuple[str, ...] = (
    "price target",
    "price objective",
    "upgrade",
    "downgrade",
    "initiat",
    "reiterat",
    "maintains",
    "overweight",
    "underweight",
    "outperform",
    "underperform",
    "buy rating",
    "sell rating",
    "hold rating",
    "neutral rating",
    "analyst",
    "precio objetivo",
    "recomendación",
    "sobreponderar",
    "infraponderar",
    "analista",
)
#: Redes sociales y foros: lo que dicen es rumor hasta que lo confirme otra fuente.
SOCIAL_HOSTS: tuple[str, ...] = (
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "threads.net",
    "tiktok.com",
    "linkedin.com",
    "youtube.com",
    "t.me",
    "bsky.app",
    "truthsocial.com",
    "reddit.com",
    "stocktwits.com",
    "discord.com",
)
_ACTIONS = ("initiate", "reiterate", "upgrade", "downgrade", "maintain")
_SENTIMENTS = ("positive", "neutral", "negative")

ANALYST_NOTE_PROMPT = (
    "Eres un extractor de notas de analistas de bolsa. Lees titulares y resúmenes de noticias "
    "ya guardadas y devuelves solo las notas de casas de análisis (bancos, brókers, firmas de "
    "research) que aparezcan en ellos. No inventas nada: si un dato no está en el texto citado, "
    "va a null o a una lista vacía. No mezclas datos de dos noticias en una nota."
)
ANALYST_NOTE_CONTRACT = (
    'Responde SOLO con JSON: {"notes": [{"evidence": "n-ID" (la noticia de la que sale), '
    '"firm": str (tal como aparece en el texto), "analyst": str|null, '
    '"action": "initiate|reiterate|upgrade|downgrade|maintain", "rating_old": str|null, '
    '"rating_new": str|null, "pt_old": numero|null, "pt_new": numero|null, "currency": str|null, '
    '"key_arguments": [str], "sentiment": "positive|neutral|negative"|null, '
    '"quote": str (copiada palabra por palabra de esa noticia), "estimates": {}|null, '
    '"valuation": {}|null, "catalysts": [str], "risks": [str], "bull_target": numero|null, '
    '"bear_target": numero|null}]}. Una nota por casa y noticia. Si ninguna noticia trae una nota '
    'de analista, {"notes": []}.'
)

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class CollectResult:
    """Qué hizo el recolector en una corrida (para logs y la respuesta de un job)."""

    status: str  # stored | no_company | no_tenant | nothing
    yahoo_status: str = "skipped"  # ok | empty | unavailable | not_equity | skipped
    news_status: str = "skipped"  # disabled | no_news | ok | rejected | error | skipped
    stored: int = 0
    unchanged: int = 0
    rejected: list[str] = field(default_factory=list)
    llm_calls: int = 0
    prompt_version: str = PROMPT_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "yahoo_status": self.yahoo_status,
            "news_status": self.news_status,
            "stored": self.stored,
            "unchanged": self.unchanged,
            "rejected": list(self.rejected),
            "llm_calls": self.llm_calls,
            "prompt_version": self.prompt_version,
        }


# ---------------------------------------------------------------------------
# Utilidades puras
# ---------------------------------------------------------------------------


def _fold(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _as_date(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    to_pydatetime = getattr(raw, "to_pydatetime", None)
    if callable(to_pydatetime):
        value = to_pydatetime()
        return value.date() if isinstance(value, datetime) else None
    if isinstance(raw, str) and raw.strip():
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0 or number in (float("inf"),):
        return None
    return number


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def is_social_url(url: str | None) -> bool:
    """True si la URL es de una red social o un foro (rumor hasta que se confirme)."""
    if not url:
        return False
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == d or host.endswith("." + d) for d in SOCIAL_HOSTS)


def numbers_in(text: str) -> set[float]:
    """Números que aparecen en el texto («$1,268.50» → 1268.5)."""
    out: set[float] = set()
    for raw in _NUMBER_RE.findall(text or ""):
        try:
            out.add(round(float(raw.replace(",", "")), 4))
        except ValueError:
            continue
    return out


def _number_found(value: float, found: set[float]) -> bool:
    return any(abs(value - n) <= max(0.005, abs(value) * 1e-6) for n in found)


def _leaf_numbers(obj: Any) -> list[float]:
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _leaf_numbers(v)]
    if isinstance(obj, list):
        return [n for v in obj for n in _leaf_numbers(v)]
    return []


# ---------------------------------------------------------------------------
# 1. Esqueleto Yahoo (puro + red acotada)
# ---------------------------------------------------------------------------


def _close_on_or_before(closes: Sequence[tuple[date, float]], day: date) -> float | None:
    best: float | None = None
    for d, close in closes:
        if d <= day:
            best = close
        else:
            break
    return best


def yahoo_note_inputs(
    ticker: str,
    records: Sequence[dict[str, Any]],
    closes: Sequence[tuple[date, float]] = (),
    *,
    today: date,
    currency: str | None = None,
    lookback_days: int = YAHOO_LOOKBACK_DAYS,
    max_records: int = YAHOO_MAX_RECORDS,
) -> list[AnalystNoteInput]:
    """Filas de ``upgrades_downgrades`` → esqueletos de nota (más recientes primero).

    Una fila sin casa o sin fecha se ignora; la acción desconocida queda
    ``other`` (nunca se inventa). El precio del día es el último cierre en o
    antes de la fecha de la nota.
    """
    symbol = ticker.strip().upper()
    since = today - timedelta(days=lookback_days)
    ordered_closes = sorted(closes)
    out: list[AnalystNoteInput] = []
    rows = []
    for record in records:
        day = _as_date(record.get("date"))
        firm = normalize_firm(record.get("firm"))
        if day is None or firm is None or day < since or day > today:
            continue
        rows.append((day, firm, record))
    rows.sort(key=lambda r: r[0], reverse=True)
    for day, firm, record in rows[:max_records]:
        out.append(
            AnalystNoteInput(
                ticker=symbol,
                firm=firm,
                note_date=day,
                action=normalize_action(record.get("action")),
                source_type="yahoo_upgrades_downgrades",
                verification="fragmento",
                rating_old=_clean_str(record.get("from_grade")),
                rating_new=_clean_str(record.get("to_grade")),
                pt_old=_positive(record.get("prior_target")),
                pt_new=_positive(record.get("price_target")),
                currency=currency,
                price_at_note=_close_on_or_before(ordered_closes, day),
                source_url=YAHOO_SOURCE_URL.format(symbol=symbol),
                extras={"yahoo_price_target_action": _clean_str(record.get("price_target_action"))}
                if _clean_str(record.get("price_target_action"))
                else {},
            )
        )
    return out


def _fetch_yahoo_sync(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    from app.services.analyst_targets_service import _fetch_currency_and_type

    ticker = yf.Ticker(symbol)
    records = fetch_upgrades_downgrades_records(ticker)
    closes: list[tuple[date, float]] = []
    history: Any = ticker.history(period="2y", auto_adjust=False)
    if history is not None and len(history) > 0:
        for index, item in history.iterrows():
            day = _as_date(index)
            close = _positive(item.get("Close"))
            if day is not None and close is not None:
                closes.append((day, close))
    declared = _fetch_currency_and_type(symbol)
    return {"records": records, "closes": closes, **declared}


YahooFetch = Callable[[str], dict[str, Any]]


async def fetch_yahoo(symbol: str, fetch: YahooFetch | None = None) -> dict[str, Any] | None:
    """Lectura de Yahoo con tiempo máximo; ``None`` si falla (nunca lanza)."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fetch or _fetch_yahoo_sync, symbol), timeout=FETCH_TIMEOUT_SECONDS
        )
    except Exception:  # noqa: BLE001 - Yahoo es no oficial y puede fallar
        return None


# ---------------------------------------------------------------------------
# 2. Noticias ingeridas + LLM acotado
# ---------------------------------------------------------------------------


def news_evidence(
    db: Session, tenant_id: int, company: Company, *, today: date, limit: int = NEWS_MAX_ITEMS
) -> list[dict[str, Any]]:
    """Noticias del tenant sobre la empresa que hablan de analistas, recientes primero."""
    since = datetime.combine(today - timedelta(days=NEWS_LOOKBACK_DAYS), datetime.min.time())
    rows = db.scalars(
        select(NewsEvent)
        .where(
            NewsEvent.tenant_id == tenant_id,
            NewsEvent.company_id == company.id,
            NewsEvent.date >= since,
        )
        .order_by(NewsEvent.date.desc(), NewsEvent.id.desc())
        .limit(limit * 8)
    ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        text = f"{row.title or ''}\n{row.summary or ''}".strip()[:NEWS_TEXT_CHARS]
        if not any(w in _fold(text) for w in ANALYST_SIGNAL_WORDS):
            continue
        url = (row.url or "").strip()
        if not is_valid_https_url(url):
            continue
        day = _as_date(row.date)
        if day is None:
            continue
        out.append(
            {
                "id": f"n-{row.id}",
                "date": day.isoformat(),
                "source": row.source or "",
                "url": url,
                "text": text,
            }
        )
        if len(out) >= limit:
            break
    return out


def parse_extraction(
    parsed: Any, evidence: Sequence[dict[str, Any]], ticker: str
) -> tuple[list[AnalystNoteInput], list[str]]:
    """JSON del modelo → notas validadas y motivos de descarte (fail-closed por nota)."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("notes"), list):
        raise ValueError("el JSON no trae la lista «notes»")
    by_id = {e["id"]: e for e in evidence}
    notes: list[AnalystNoteInput] = []
    rejected: list[str] = []
    for index, raw in enumerate(parsed["notes"][:MAX_EXTRACTED_NOTES]):
        label = f"#{index + 1}"
        if not isinstance(raw, dict):
            rejected.append(f"{label}: no es un objeto")
            continue
        ev = by_id.get(str(raw.get("evidence") or ""))
        if ev is None:
            rejected.append(f"{label}: no cita una noticia de esta corrida")
            continue
        label = f"{label} ({ev['id']})"
        text = ev["text"]
        folded = _fold(text)
        quote = _clean_str(raw.get("quote"))
        if not quote or _fold(quote) not in folded:
            rejected.append(f"{label}: la cita no aparece literal en la noticia")
            continue
        firm_raw = _clean_str(raw.get("firm"))
        firm = normalize_firm(firm_raw)
        if not firm_raw or not firm or _fold(firm_raw) not in folded:
            rejected.append(f"{label}: la casa no aparece en la noticia")
            continue
        action = normalize_action(raw.get("action"))
        if action not in _ACTIONS:
            rejected.append(f"{label}: acción no válida")
            continue
        found = numbers_in(text)
        numeric = {k: _positive(raw.get(k)) for k in ("pt_old", "pt_new", "bull_target", "bear_target")}
        missing = [k for k, v in numeric.items() if v is not None and not _number_found(v, found)]
        raw_estimates = raw.get("estimates")
        estimates: dict[str, Any] = raw_estimates if isinstance(raw_estimates, dict) else {}
        raw_valuation = raw.get("valuation")
        valuation: dict[str, Any] = raw_valuation if isinstance(raw_valuation, dict) else {}
        for name, blob in (("estimates", estimates), ("valuation", valuation)):
            if any(not _number_found(n, found) for n in _leaf_numbers(blob) if n > 0):
                missing.append(name)
        if missing:
            rejected.append(f"{label}: números que no están en la noticia ({', '.join(missing)})")
            continue
        sentiment = _clean_str(raw.get("sentiment"))
        notes.append(
            AnalystNoteInput(
                ticker=ticker,
                firm=firm,
                note_date=date.fromisoformat(ev["date"]),
                action=action,
                source_type="social" if is_social_url(ev["url"]) else "news",
                analyst=_clean_str(raw.get("analyst")),
                rating_old=_clean_str(raw.get("rating_old")),
                rating_new=_clean_str(raw.get("rating_new")),
                pt_old=numeric["pt_old"],
                pt_new=numeric["pt_new"],
                currency=_clean_str(raw.get("currency")),
                key_arguments=[a for a in raw.get("key_arguments") or [] if isinstance(a, str)],
                sentiment=sentiment if sentiment in _SENTIMENTS else None,
                quote=quote,
                source_url=ev["url"],
                estimates=estimates,
                valuation=valuation,
                catalysts=[a for a in raw.get("catalysts") or [] if isinstance(a, str)],
                risks=[a for a in raw.get("risks") or [] if isinstance(a, str)],
                bull_target=numeric["bull_target"],
                bear_target=numeric["bear_target"],
                extras={"news_source": ev["source"], "evidence": ev["id"], "prompt": PROMPT_VERSION},
            )
        )
    return notes, rejected


def align_with_skeletons(
    db: Session, tenant_id: int, notes: list[AnalystNoteInput]
) -> list[AnalystNoteInput]:
    """Una nota de noticia toma la fecha y la acción del esqueleto Yahoo de la misma
    casa a ±``SKELETON_MATCH_DAYS`` días (el más cercano), para enriquecer esa fila
    en vez de crear otra."""
    for note in notes:
        firm_key = note.firm.lower()
        window = timedelta(days=SKELETON_MATCH_DAYS)
        rows = db.scalars(
            select(AnalystNote).where(
                AnalystNote.tenant_id == tenant_id,
                AnalystNote.ticker == note.ticker,
                AnalystNote.firm_key == firm_key,
                AnalystNote.source_type == "yahoo_upgrades_downgrades",
                AnalystNote.note_date >= note.note_date - window,
                AnalystNote.note_date <= note.note_date + window,
            )
        ).all()
        if not rows:
            continue
        best = min(
            rows,
            key=lambda r: (abs((r.note_date - note.note_date).days), r.action != note.action, -r.id),
        )
        note.note_date = best.note_date
        note.action = best.action
    return notes


def _default_reasoner(db: Session) -> Reasoner:
    from app.services.expert_team.service import provider_reasoner

    return provider_reasoner(db=db)


async def extract_from_news(
    evidence: Sequence[dict[str, Any]],
    ticker: str,
    company_name: str,
    reasoner: Reasoner,
    result: CollectResult,
) -> list[AnalystNoteInput]:
    from app.llm.json import parse_json_response

    system = f"{ANALYST_NOTE_PROMPT}\n\n{ANALYST_NOTE_CONTRACT}"
    payload: dict[str, Any] = {"ticker": ticker, "company": company_name, "news": list(evidence)}
    for _ in range(MAX_ATTEMPTS):
        result.llm_calls += 1
        try:
            text = await reasoner(
                system, json.dumps(payload, ensure_ascii=False, default=str), LLM_MAX_TOKENS, LLM_TASK
            )
        except Exception as exc:  # sin LLM o sin presupuesto: no se escribe nada de noticias
            result.news_status = "error"
            result.rejected.append(f"llm:{type(exc).__name__}")
            return []
        try:
            parsed = parse_json_response(text)
            notes, rejected = parse_extraction(parsed, evidence, ticker)
        except Exception as exc:  # noqa: BLE001 - JSON ilegible: un reintento
            payload["problems_previous_answer"] = [str(exc)[:200]]
            continue
        result.news_status = "ok"
        result.rejected.extend(rejected)
        return notes
    result.news_status = "rejected"
    result.rejected.append("el modelo no devolvió un JSON válido")
    return []


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


async def collect_for_ticker(
    db: Session,
    tenant_id: int,
    ticker: str,
    *,
    reasoner: Reasoner | None = None,
    enabled: bool | None = None,
    today: date | None = None,
    yahoo_fetch: YahooFetch | None = None,
    service: AnalystNoteService | None = None,
) -> CollectResult:
    """Recoge y guarda las notas de ``ticker`` para ``tenant_id``.

    ``enabled`` None = ``EXPERT_TEAM_ENABLED``: decide solo la parte LLM; el
    esqueleto Yahoo no usa LLM. No hace commit: lo decide quien llama. La sesión
    tiene que llevar el contexto del tenant (``db.info["tenant_id"]``), como
    cualquier escritura de datos por tenant.
    """
    if type(tenant_id) is not int or tenant_id <= 0:
        return CollectResult(status="no_tenant")
    symbol = (ticker or "").strip().upper()
    company = db.scalars(select(Company).where(Company.ticker == symbol)).first()
    if company is None:
        return CollectResult(status="no_company")
    today = today or date.today()
    service = service or AnalystNoteService()
    result = CollectResult(status="nothing")
    inputs: list[AnalystNoteInput] = []

    data = await fetch_yahoo(symbol, yahoo_fetch)
    if data is None:
        result.yahoo_status = "unavailable"
    else:
        from app.services.analyst_targets_service import non_equity_label

        if non_equity_label(data.get("quote_type")) is not None:
            result.yahoo_status = "not_equity"
        else:
            skeletons = yahoo_note_inputs(
                symbol,
                data.get("records") or [],
                data.get("closes") or [],
                today=today,
                currency=data.get("currency"),
            )
            result.yahoo_status = "ok" if skeletons else "empty"
            inputs.extend(skeletons)

    for item in inputs:
        item.company_id = company.id
    _store(db, tenant_id, inputs, service, result)

    if enabled is None:
        from app.core.config import get_settings

        enabled = bool(get_settings().expert_team_enabled)
    if not enabled:
        result.news_status = "disabled"
    else:
        evidence = news_evidence(db, tenant_id, company, today=today)
        if not evidence:
            result.news_status = "no_news"
        else:
            notes = await extract_from_news(
                evidence, symbol, company.name or symbol, reasoner or _default_reasoner(db), result
            )
            notes = align_with_skeletons(db, tenant_id, notes)
            for item in notes:
                item.company_id = company.id
            _store(db, tenant_id, notes, service, result)
    if result.stored or result.unchanged:
        result.status = "stored"
    return result


def _store(
    db: Session,
    tenant_id: int,
    items: Sequence[AnalystNoteInput],
    service: AnalystNoteService,
    result: CollectResult,
) -> None:
    for item in items:
        try:
            _row, changed = service.upsert(db, tenant_id, item)
        except AnalystNoteError as exc:
            result.rejected.append(f"{item.firm} {item.note_date}: {'; '.join(exc.problems)}")
            continue
        if changed:
            result.stored += 1
        else:
            result.unchanged += 1


__all__ = [
    "ANALYST_NOTE_CONTRACT",
    "ANALYST_SIGNAL_WORDS",
    "CollectResult",
    "PROMPT_VERSION",
    "SOCIAL_HOSTS",
    "align_with_skeletons",
    "collect_for_ticker",
    "extract_from_news",
    "fetch_yahoo",
    "is_social_url",
    "news_evidence",
    "numbers_in",
    "parse_extraction",
    "yahoo_note_inputs",
]
