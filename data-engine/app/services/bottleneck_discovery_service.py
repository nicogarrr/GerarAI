"""Descubrimiento de candidatos por cuello de botella (3B): INFERENCIA etiquetada.

El modelo solo ve los textos de las evidencias que ya sustentan un tema con
``n_sources >= MIN_SOURCES`` y propone ``{ticker, motivo, evidence_ids}``. Todo
lo que devuelve es hipotesis: se guarda siempre con la etiqueta INFERIDO.

Salida CONTROLADA: el modelo no escribe texto libre. Elige ``exposicion`` y ``canal``
de listas cerradas; el razonamiento en espanol lo compone esta capa con plantillas
fijas. Asi no puede colarse ninguna cantidad, precio, URL o afirmacion inventada
(ni en cifras ni en palabras): lo que no es un valor de la lista se descarta.

Fail-closed y por candidato. Se descarta el candidato cuando:
- trae campos fuera del esquema (p. ej. un ``motivo`` libre);
- el ticker no cumple el formato o no existe en ``companies`` (salvo "N/D");
- ``exposicion`` o ``canal`` no son exactamente un valor permitido;
- cita una evidencia que no recibio, o ninguna.
Las URLs de las fuentes salen de la base, nunca del modelo.
Sin ejecucion ni dinero: solo lee evidencias guardadas y escribe candidatos.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import tenant_filters
from app.llm import LLMRequest, Message, ResponseFormat, create_llm_provider, parse_json_response
from app.llm.model_aliases import is_owner_approved_model
from app.models import (
    BottleneckDiscovery,
    BottleneckSignal,
    Company,
    Document,
    DocumentChunk,
    KnowledgeChunk,
    KnowledgeDocument,
    NewsEvent,
)
from app.services.bottleneck_service import MIN_SOURCES, THEMES, extract_themes, fold
from app.services.budget import BudgetController, BudgetExceededError
from app.services.llm_output_guard import LLMOutputRejected, complete_guarded
from app.services.llm_router import route_model
from app.services.prompt_registry import get_prompt

logger = logging.getLogger(__name__)

TASK = "bottleneck_discovery"
DAILY_QUOTA = 10  # candidatos guardados por tenant y dia UTC
MAX_EVIDENCE = 8
MAX_EVIDENCE_TEXT = 700
MAX_CANDIDATES = 3
MAX_IDS_PER_THEME = 300
CALL_COST_ESTIMATE_EUR = 0.02
NO_DATA = "N/D"

_TICKER = re.compile(r"^(?:[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,3})?)$")
EXPOSURES = {"beneficiaria": "beneficiada", "afectada": "afectada"}
CHANNELS = {
    "proveedor_directo": "suministra de forma directa el recurso o componente escaso",
    "capacidad_productiva": "controla capacidad productiva en el segmento afectado",
    "cliente_dependiente": "depende del recurso escaso para producir o entregar",
    "infraestructura_logistica": "opera infraestructura o logística ligada al cuello de botella",
    "alternativa_sustitutiva": "ofrece una alternativa al recurso escaso",
}
_ALLOWED_KEYS = {"ticker", "exposicion", "canal", "evidence_ids"}

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidatos"],
    "properties": {
        "candidatos": {
            "type": "array",
            "maxItems": MAX_CANDIDATES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ticker", "exposicion", "canal", "evidence_ids"],
                "properties": {
                    "ticker": {"type": "string"},
                    "exposicion": {"type": "string", "enum": list(EXPOSURES)},
                    "canal": {"type": "string", "enum": list(CHANNELS)},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

_PROMPT = get_prompt("bottleneck_discovery_service", allow_remote=False)
SYSTEM = _PROMPT.text


class DiscoveryRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class QuotaExceeded(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"cuota diaria de {limit} candidatos agotada")
        self.limit = limit


@dataclass(frozen=True)
class ResolvedEvidence:
    id: str
    text: str
    title: str | None
    url: str | None
    date: datetime | None


@dataclass(frozen=True)
class ThemeContext:
    theme: str
    n_sources: int
    evidence: tuple[ResolvedEvidence, ...]


@dataclass(frozen=True)
class Candidate:
    ticker: str
    exposure: str
    channel: str
    reasoning: str
    evidence_ids: tuple[str, ...]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _real_url(url: str | None) -> str | None:
    """Solo URLs http(s) guardadas con la fuente; cualquier otra cosa es N/D."""
    clean = (url or "").strip()
    return clean if re.match(r"(?i)^https?://\S+$", clean) else None


def distinct_sources(evidence: Iterable[ResolvedEvidence]) -> list[ResolvedEvidence]:
    """Una entrada por fuente real.

    Varios chunks del mismo documento (p. ej. un 10-K de AAPL troceado) son
    UNA fuente; sin esta agrupacion el contador de evidencias se infla con
    duplicados del mismo filing. Clave: URL guardada o, si no hay, el titulo.
    """
    seen: set[str] = set()
    out: list[ResolvedEvidence] = []
    for item in evidence:
        key = item.url if item.url else f"title:{item.title}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


_CORP_SUFFIXES = {
    "inc", "corp", "corporation", "co", "company", "ltd", "llc", "lp", "llp",
    "sa", "sau", "saa", "plc", "nv", "ag", "se", "asa", "ab", "oyj", "spa",
    "bv", "gmbh", "srl", "pte", "pty", "holdings", "holding", "group",
    "international", "technologies", "technology",
}

_MIN_TICKER_LEN = 3

# Palabras comunes (ES/EN) que ademas son tickers reales. Todo el texto llega
# en minusculas (fold), asi que "now" la palabra y NOW (ServiceNow) son
# indistinguibles: estos tickers solo casan por nombre de empresa, o la
# evidencia tematica generaria falsos cruces. No necesita ser exhaustiva.
_COMMON_WORD_TICKERS = {
    # ingles
    "all", "and", "any", "are", "big", "box", "can", "car", "cat", "day",
    "eat", "eye", "far", "fly", "for", "fox", "fun", "gold", "good", "grow",
    "has", "hope", "hot", "how", "ice", "job", "joy", "key", "king", "life",
    "like", "live", "love", "low", "man", "map", "mark", "meta", "mind",
    "net", "new", "now", "one", "open", "pay", "play", "plug", "race",
    "real", "red", "rio", "run", "see", "shop", "sky", "snow", "spot",
    "sun", "tech", "tell", "ten", "tree", "two", "usa", "via", "way",
    "wish", "work", "you", "zeta",
    # espanol
    "mar", "mas", "mes", "mil", "oro", "sol", "sur",
}


def _name_tokens(name: str | None) -> list[str]:
    """Tokens del nombre ya sin puntuacion pegada ("sciences," -> "sciences")."""
    out: list[str] = []
    for tok in fold(name or "").split():
        tok = tok.strip(".,;:()\"'¡!¿?-/")
        if tok:
            out.append(tok)
    return out


def _mention_pattern(ticker: str, name: str | None) -> re.Pattern[str] | None:
    """Regex para detectar si un texto habla de la empresa (ticker o nombre).

    El nombre se prueba completo y sin sufijos societarios finales
    ("CV Sciences, Inc." -> "cv sciences"); la puntuacion pegada se quita
    ANTES de mirar sufijos, porque si no "sciences," no casa con el sufijo
    real y la coma queda atrapada en el patron ("cv sciences,").

    El ticker solo se prueba si tiene >= 3 caracteres y no es una palabra
    comun (NOW, META, ZETA...): como el texto llega en minusculas, un
    ticker-palabra descartaria evidencia legitima por falso cruce.
    Formas de menos de 4 caracteres del nombre se ignoran igual que antes.
    """
    folded_ticker = fold(ticker)
    parts: set[str] = set()
    if (
        len(folded_ticker) >= _MIN_TICKER_LEN
        and folded_ticker not in _COMMON_WORD_TICKERS
    ):
        parts.add(re.escape(folded_ticker))
    full_tokens = _name_tokens(name)
    tokens = list(full_tokens)
    while tokens and tokens[-1] in _CORP_SUFFIXES:
        tokens.pop()
    for variant in {" ".join(full_tokens), " ".join(tokens)}:
        if len(variant) >= 4 and variant != folded_ticker:
            parts.add(re.escape(variant))
    if not parts:
        return None
    return re.compile("(?<![a-z0-9])(?:" + "|".join(sorted(parts)) + ")(?![a-z0-9])")


def build_mention_patterns(db: Session) -> dict[str, re.Pattern[str]]:
    """Un patron por empresa del universo conocido, para validar candidatos."""
    patterns: dict[str, re.Pattern[str]] = {}
    for ticker, name in db.execute(select(Company.ticker, Company.name)):
        pattern = _mention_pattern(ticker, name)
        if pattern is not None:
            patterns[ticker] = pattern
    return patterns


def _cites_other_company_only(
    texts: list[str], ticker: str, patterns: dict[str, re.Pattern[str]]
) -> bool:
    """True cuando la evidencia citada habla de OTRA empresa conocida y no de esta.

    El modelo propone el par (ticker, evidencia) dentro de un pool tematico
    compartido por muchas empresas; sin esta guarda un candidato podia citar
    la noticia de otra empresa (SIF citando noticias de CVU). La inferencia
    sigue permitida: evidencia tematica que no nombra a ninguna empresa
    conocida no descarta al candidato.
    """
    own = patterns.get(ticker)
    for text in texts:
        folded = fold(text)
        if own and own.search(folded):
            continue
        if any(p.search(folded) for other, p in patterns.items() if other != ticker):
            return True
    return False


def resolve_evidence(db: Session, ids: list[str]) -> dict[str, ResolvedEvidence]:
    """Resuelve ids de ``bottleneck_signal.evidence_ids`` contra el almacen del tenant.

    Ids desconocidos o de otro tenant simplemente no aparecen (la sesion filtra
    por tenant y cada consulta repite el filtro explicito).
    """
    tenant = db.info.get("tenant_id")
    if not isinstance(tenant, int):
        return {}
    by_kind: dict[str, list[int]] = {"document_chunk": [], "knowledge_chunk": [], "news_event": []}
    for raw in ids:
        kind, _, number = str(raw).partition(":")
        if kind in by_kind and number.isdigit():
            by_kind[kind].append(int(number))
    out: dict[str, ResolvedEvidence] = {}
    if by_kind["document_chunk"]:
        for chunk, doc in db.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_(by_kind["document_chunk"]), DocumentChunk.tenant_id == tenant,
                   Document.tenant_id == tenant)
        ):
            key = f"document_chunk:{chunk.id}"
            out[key] = ResolvedEvidence(key, chunk.text, doc.title, _real_url(doc.source_url),
                                        doc.published_at and _utc(doc.published_at))
    if by_kind["knowledge_chunk"]:
        for kchunk, kdoc in db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
            .where(KnowledgeChunk.id.in_(by_kind["knowledge_chunk"]), KnowledgeChunk.tenant_id == tenant,
                   KnowledgeDocument.tenant_id == tenant)
        ):
            key = f"knowledge_chunk:{kchunk.id}"
            published = kdoc.publication_date
            out[key] = ResolvedEvidence(
                key, kchunk.content, kdoc.title, _real_url(kdoc.source_url),
                datetime.combine(published, datetime.min.time(), UTC) if published else None)
    if by_kind["news_event"]:
        for news in db.scalars(select(NewsEvent).where(
            NewsEvent.id.in_(by_kind["news_event"]), NewsEvent.tenant_id == tenant
        )):
            key = f"news_event:{news.id}"
            out[key] = ResolvedEvidence(key, news.title, news.title, _real_url(news.url), _utc(news.date))
    return out


def load_theme_contexts(db: Session, *, min_sources: int = MIN_SOURCES) -> list[ThemeContext]:
    """Temas del tenant con fuentes suficientes y sus evidencias (copiadas a dataclasses)."""
    tenant = db.info.get("tenant_id")
    if not isinstance(tenant, int):
        return []
    rows = db.scalars(select(BottleneckSignal).where(
        BottleneckSignal.tenant_id == tenant, BottleneckSignal.n_sources >= min_sources
    )).all()
    contexts: list[ThemeContext] = []
    for row in sorted(rows, key=lambda r: list(THEMES).index(r.theme) if r.theme in THEMES else 99):
        resolved = resolve_evidence(db, list(row.evidence_ids or [])[-MAX_IDS_PER_THEME:])
        # Solo evidencias que siguen sustentando el tema (el texto pudo cambiar).
        support = [e for e in resolved.values() if row.theme in extract_themes(e.text)]
        support.sort(key=lambda e: (e.date or datetime.min.replace(tzinfo=UTC), e.id), reverse=True)
        # Fuentes realmente distintas: varios chunks del mismo filing cuentan una vez.
        support = distinct_sources(support)
        if support:
            contexts.append(ThemeContext(row.theme, row.n_sources, tuple(support[:MAX_EVIDENCE])))
    return contexts


def build_request(context: ThemeContext, model: str | None = None) -> LLMRequest:
    payload = {
        "tema": context.theme,
        "evidencias": [
            {"id": e.id, "texto": e.text[:MAX_EVIDENCE_TEXT]} for e in context.evidence
        ],
    }
    return LLMRequest(
        messages=[Message("system", SYSTEM), Message("user", json.dumps(payload, ensure_ascii=False))],
        task=TASK,
        model=model,
        temperature=0.2,
        max_tokens=700,
        response_format=ResponseFormat.json_schema(_SCHEMA, name="bottleneck_discovery"),
        metadata=_PROMPT.trace_metadata(),
    )


def compose_reasoning(
    ticker: str,
    exposure: str,
    channel: str,
    *,
    company_name: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
) -> str:
    """Texto en espanol 100% de plantilla: nada del modelo llega al usuario salvo valores de listas cerradas.

    El nombre, sector e industria salen de la tabla ``companies`` (dato curado,
    no del modelo): hacen la hipotesis especifica por empresa sin abrir texto
    libre. Si la ficha no tiene sector/industria curado ("Unknown"), se omite.
    """
    if ticker == NO_DATA:
        who = "Una empresa aún sin identificar (N/D)"
    else:
        who = ticker
        details = []
        if company_name and company_name.strip() and company_name.strip() != ticker:
            details.append(company_name.strip())
        for value in (industry, sector):
            if value and value.strip() and value.strip() != "Unknown":
                details.append(value.strip())
                break
        if details:
            who = f"{ticker} ({' · '.join(details)})"
    return (
        f"Hipótesis del modelo, no un hecho: {who} podría resultar {EXPOSURES[exposure]} por este cuello de "
        f"botella porque {CHANNELS[channel]}. Se infiere de las evidencias citadas."
    )


def build_company_profiles(db: Session) -> dict[str, tuple[str, str, str]]:
    """ticker -> (nombre, sector, industria) de la tabla companies (dato curado)."""
    return {
        ticker: (name, sector, industry)
        for ticker, name, sector, industry in db.execute(
            select(Company.ticker, Company.name, Company.sector, Company.industry)
        )
    }


def _check_candidate(
    item: Any,
    allowed_ids: set[str],
    known_tickers: set[str],
    *,
    evidence_by_id: dict[str, ResolvedEvidence] | None = None,
    mention_patterns: dict[str, re.Pattern[str]] | None = None,
    company_profiles: dict[str, tuple[str, str, str]] | None = None,
) -> Candidate | str:
    if not isinstance(item, dict):
        return "candidato_invalido"
    if set(item) - _ALLOWED_KEYS:
        return "campos_no_permitidos"
    ticker = item.get("ticker")
    if not isinstance(ticker, str):
        return "ticker_invalido"
    ticker = ticker.strip().upper()
    if ticker != NO_DATA:
        if not _TICKER.match(ticker):
            return "ticker_invalido"
        if ticker not in known_tickers:
            return "ticker_inexistente"
    exposure, channel = item.get("exposicion"), item.get("canal")
    if not isinstance(exposure, str) or exposure not in EXPOSURES:
        return "exposicion_invalida"
    if not isinstance(channel, str) or channel not in CHANNELS:
        return "canal_invalido"
    ids = item.get("evidence_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
        return "sin_evidencia"
    if any(i not in allowed_ids for i in ids):
        return "evidencia_no_recibida"
    unique_ids = tuple(dict.fromkeys(ids))
    if ticker != NO_DATA and evidence_by_id and mention_patterns:
        texts = [evidence_by_id[i].text for i in unique_ids if i in evidence_by_id]
        if texts and _cites_other_company_only(texts, ticker, mention_patterns):
            return "evidencia_de_otra_empresa"
    name = sector = industry = None
    if company_profiles and ticker != NO_DATA:
        name, sector, industry = company_profiles.get(ticker, (None, None, None))
    return Candidate(
        ticker, exposure, channel,
        compose_reasoning(ticker, exposure, channel, company_name=name, sector=sector, industry=industry),
        unique_ids)


def validate_output(
    raw: Any,
    *,
    allowed_ids: set[str],
    known_tickers: set[str],
    evidence_by_id: dict[str, ResolvedEvidence] | None = None,
    mention_patterns: dict[str, re.Pattern[str]] | None = None,
    company_profiles: dict[str, tuple[str, str, str]] | None = None,
) -> tuple[list[Candidate], list[str]]:
    """Devuelve (aceptados, motivos de descarte). Salida mal formada = DiscoveryRejected."""
    if not isinstance(raw, dict) or not isinstance(raw.get("candidatos"), list):
        raise DiscoveryRejected("json_invalido")
    accepted: list[Candidate] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw["candidatos"]):
        if index >= MAX_CANDIDATES:
            rejected.append("exceso_de_candidatos")
            continue
        result = _check_candidate(
            item, allowed_ids, known_tickers,
            evidence_by_id=evidence_by_id, mention_patterns=mention_patterns,
            company_profiles=company_profiles,
        )
        if isinstance(result, str):
            rejected.append(result)
        elif result.ticker in seen:
            rejected.append("ticker_duplicado")
        else:
            seen.add(result.ticker)
            accepted.append(result)
    return accepted, rejected


# --- cuota diaria ---------------------------------------------------------

_quota_guard = threading.Lock()
_quota_locks: dict[tuple, threading.Lock] = {}


def _today(now: datetime) -> date:
    return _utc(now).date()


def todays_discoveries(db: Session, now: datetime) -> int:
    return int(db.scalar(select(func.count(BottleneckDiscovery.id)).where(
        BottleneckDiscovery.day == _today(now),
        *tenant_filters(db, BottleneckDiscovery),
    )) or 0)


def save_within_quota(
    db: Session, context: ThemeContext, candidates: list[Candidate], model: str, now: datetime
) -> int:
    """Cuenta y guarda en una transaccion corta serializada por tenant y dia.

    Candado de proceso mas pg_advisory_xact_lock (varios workers); se toma
    DESPUES del LLM, nunca lo cubre. Devuelve cuantos candidatos nuevos guardo.
    """
    db.commit()
    tenant = db.info.get("tenant_id")
    key = (tenant, _today(now))
    with _quota_guard:
        lock = _quota_locks.setdefault(key, threading.Lock())
    with lock:
        if db.get_bind().dialect.name == "postgresql":
            raw = f"bottleneck-discovery-quota:{tenant}:{_today(now)}".encode()
            number = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") >> 1
            db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": number})
        remaining = DAILY_QUOTA - todays_discoveries(db, now)
        if remaining <= 0:
            db.rollback()
            raise QuotaExceeded(DAILY_QUOTA)
        existing = set(db.scalars(select(BottleneckDiscovery.ticker).where(
            BottleneckDiscovery.day == _today(now),
            BottleneckDiscovery.theme == context.theme,
            *tenant_filters(db, BottleneckDiscovery),
        )))
        saved = 0
        try:
            for candidate in candidates:
                if saved >= remaining:
                    break
                if candidate.ticker in existing:
                    continue
                db.add(BottleneckDiscovery(
                    theme=context.theme, ticker=candidate.ticker, reasoning=candidate.reasoning,
                    evidence_ids=list(candidate.evidence_ids), label="INFERIDO", model=model,
                    day=_today(now), created_at=_utc(now), n_sources=context.n_sources))
                saved += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        return saved


def paid_model_risk(provider: Any, model: str, *, settings: Any = None) -> str | None:
    """Motivo de bloqueo si la llamada REAL podria usar un modelo no aprobado.

    Aprobados: free verificados o el modelo Go de la suscripcion del dueno (solo
    con ``chat_go_subscription_enabled``). Resuelve con el mismo router que usara
    el proveedor (incluidos overrides de entorno) sobre una peticion con el modelo
    ya fijado, y mira tambien el modelo de fallback del adaptador. Todo ANTES de
    gastar nada. Fail-closed: si no se puede verificar, se bloquea.
    """
    settings = settings or get_settings()
    router = getattr(provider, "model_router", None)
    if router is None:
        return "modelo_no_verificable"
    probe = LLMRequest(messages=[Message("user", "x")], task=TASK, model=model)
    try:
        resolved = router.resolve(probe)
    except Exception:  # noqa: BLE001 - alias deshabilitado o inconsistente
        return "modelo_no_verificable"
    if not is_owner_approved_model(resolved, settings):
        return "modelo_no_gratuito"
    fallback = getattr(provider, "_fallback_model", None)
    if fallback and not is_owner_approved_model(fallback, settings):
        return "fallback_no_gratuito"
    return None


# --- ejecucion ------------------------------------------------------------

async def discover(
    db: Session,
    *,
    provider: Any = None,
    now: datetime | None = None,
    deadline: Any = None,
    min_sources: int = MIN_SOURCES,
) -> dict[str, Any]:
    """Un barrido por temas. La sesion se libera (commit) antes de cada llamada LLM."""
    now = now or datetime.now(UTC)
    result: dict[str, Any] = {
        "status": "ok", "themes_considered": 0, "themes_processed": 0, "saved": 0,
        "rejected": {}, "errors": 0, "stop_reason": None,
    }

    def stop(reason: str) -> dict[str, Any]:
        result["status"] = "partial"
        result["stop_reason"] = reason
        return result

    settings = get_settings()
    route = route_model(TASK)
    if not is_owner_approved_model(route.model, settings):
        return {**result, "status": "skipped", "stop_reason": "modelo_no_gratuito"}
    provider = provider or create_llm_provider()
    if provider.name == "disabled":
        return {**result, "status": "skipped", "stop_reason": "llm_deshabilitado"}
    blocked = paid_model_risk(provider, route.model, settings=settings)
    if blocked:
        return {**result, "status": "skipped", "stop_reason": blocked}
    if todays_discoveries(db, now) >= DAILY_QUOTA:
        return {**result, "status": "skipped", "stop_reason": "cuota_agotada"}
    contexts = load_theme_contexts(db, min_sources=min_sources)
    company_profiles = build_company_profiles(db)
    known = set(company_profiles)
    mention_patterns = build_mention_patterns(db)
    db.commit()  # sin conexion ni transaccion abiertas durante el LLM
    result["themes_considered"] = len(contexts)
    budget = BudgetController()
    rejected: Counter[str] = Counter()

    def _record(resp) -> None:
        cost = budget.estimate_cost_eur(resp.model, resp.usage.input_tokens, resp.usage.output_tokens)
        budget.record(db, resp.model, TASK, cost, resp.usage.total_tokens)

    def _can_spend() -> bool:
        try:
            return budget.can_spend(db, CALL_COST_ESTIMATE_EUR)
        finally:
            db.commit()

    def _before_retry() -> None:
        if not _can_spend():
            raise BudgetExceededError("LLM budget exhausted")

    def _over() -> bool:
        return deadline is not None and bool(deadline.expired())

    async def _call(context: ThemeContext):
        coroutine = complete_guarded(
            provider, build_request(context, route.model), source=TASK, on_response=_record,
            before_retry=_before_retry,
        )
        remaining = getattr(deadline, "remaining", None)
        if remaining is None:
            return await coroutine
        return await asyncio.wait_for(coroutine, timeout=max(float(remaining()), 0.001))

    for context in contexts:
        if _over():
            result["rejected"] = dict(rejected)
            return stop("deadline")
        if not _can_spend():
            result["rejected"] = dict(rejected)
            return stop("presupuesto_agotado")
        try:
            guarded = await _call(context)
            raw = parse_json_response(guarded.response.text)
            accepted, reasons = validate_output(
                raw,
                allowed_ids={e.id for e in context.evidence},
                known_tickers=known,
                evidence_by_id={e.id: e for e in context.evidence},
                mention_patterns=mention_patterns,
                company_profiles=company_profiles,
            )
        except TimeoutError:
            if deadline is not None:
                deadline.truncated = True
            result["rejected"] = dict(rejected)
            return stop("deadline")
        except BudgetExceededError:
            result["rejected"] = dict(rejected)
            return stop("presupuesto_agotado")
        except LLMOutputRejected:
            rejected["salida_rechazada"] += 1
            result["themes_processed"] += 1
            continue
        except DiscoveryRejected as exc:
            rejected[exc.reason] += 1
            result["themes_processed"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 - JSON roto o fallo del proveedor: el tema se omite
            logger.warning("bottleneck_discovery[%s]: %s", context.theme, type(exc).__name__)
            result["errors"] += 1
            result["status"] = "partial"
            continue
        rejected.update(reasons)
        result["themes_processed"] += 1
        if _over():  # vencio durante la llamada o el guard: no se persiste fuera de plazo
            result["rejected"] = dict(rejected)
            return stop("deadline")
        try:
            result["saved"] += save_within_quota(db, context, accepted, guarded.response.model, now)
        except QuotaExceeded:
            result["rejected"] = dict(rejected)
            return stop("cuota_agotada")
        if _over():  # vencio durante la persistencia: ya guardado, pero el barrido es parcial
            result["rejected"] = dict(rejected)
            return stop("deadline")
    result["rejected"] = dict(rejected)
    return result
