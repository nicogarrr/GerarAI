"""On-demand, non-persistent hypotheses about indirect effects of a news item.

No signal from this service verifies a source claim or changes investment state.
The generative path is operator-gated and limited to the verified free model.
No background job calls it during news ingestion; the tracked-news alert
analysis (portfolio/watchlist companies only) calls it under the same flag
and per-tenant quota.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm import LLMRequest, Message, ResponseFormat, create_llm_provider, parse_json_response
from app.llm.model_aliases import is_owner_approved_model
from app.models import Company, NewsEvent, PeerRelationship
from app.services.async_bridge import run_from_any_context
from app.services.llm_output_guard import complete_guarded
from app.services.prompt_registry import get_prompt
from app.services.second_order_quota import reserve_llm_call

_PROMPT = get_prompt("second_order_news_service", allow_remote=False)


def _prompt():
    """i18n B: resuelve el prompt en el idioma activo de la peticion.

    La constante de modulo queda en espanol (los tests la fijan); cada
    llamada pasa por ``get_prompt`` para heredar el idioma del scope.
    """
    return get_prompt("second_order_news_service", allow_remote=False)



class CausalStep(BaseModel):
    cause: str = Field(max_length=180)
    effect: str = Field(max_length=180)


class Theme(BaseModel):
    exposure: str = Field(max_length=100)
    direction: Literal["beneficiada", "perjudicada", "incierta"]
    chain: list[CausalStep] = Field(max_length=4)


class Extraction(BaseModel):
    themes: list[Theme] = Field(max_length=8)


# A deliberately small, public vocabulary. The fallback does not invent
# exposure or extrapolate sector labels from arbitrary narrative text.
# Keyword matches are NOT evidence that the claim in the article is true.
DETERMINISTIC_THEMES: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
    (("electrification", "electrificación", "electric trucks", "camiones eléctricos"),
     "Electric Utilities", "beneficiada", "Posible aumento de demanda eléctrica"),
    (("electrification", "electrificación", "electric trucks", "camiones eléctricos"),
     "Electrical Equipment", "beneficiada", "Posible inversión en equipamiento de red"),
    (("electrification", "electrificación", "electric trucks", "camiones eléctricos"),
     "Copper", "beneficiada", "Posible demanda de materiales para infraestructura"),
    (("electrification", "electrificación", "electric trucks", "camiones eléctricos"),
     "Oil & Gas", "perjudicada", "Posible sustitución de combustible de transporte"),
)


# Cap on selected candidates. A bare sector coincidence is not a concrete
# reason (measured in prod: 100 sector-level candidates for one ASTS news
# item), so only industry/factor matches count and the list stays short.
CANDIDATE_LIMIT = 10
CANDIDATES_PER_THEME = 2

_REASON_FIELD_LABEL = {"industry": "industria", "factor_tags": "etiqueta de factor"}


def _normalized(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _match_keyword(text: str, term: str) -> bool:
    return f" {_normalized(term)} " in f" {_normalized(text)} "


def _fallback(text: str) -> Extraction:
    themes = []
    for terms, exposure, direction, effect in DETERMINISTIC_THEMES:
        matched = next((term for term in terms if _match_keyword(text, term)), None)
        if matched:
            themes.append(Theme(
                exposure=exposure, direction=direction,
                chain=[CausalStep(cause=f"La fuente menciona {matched}", effect=effect)],
            ))
    return Extraction(themes=themes)


_SCHEMA = Extraction.model_json_schema()


async def _extract_with_llm(text: str, context: str = "", before_retry=None) -> tuple[Extraction, object]:
    provider = create_llm_provider()
    if provider.name == "disabled":
        raise RuntimeError("LLM not configured")
    settings = get_settings()
    model = (
        settings.opencode_go_model
        if is_owner_approved_model(settings.opencode_go_model, settings)
        else "space-bunny-free"
    )
    request = LLMRequest(
        messages=[
            Message("system", _prompt().text),
            Message("user", (context + "\n\nNoticia:\n" if context else "") + text[:3500]),
        ],
        task="news_second_order",
        model=model,
        temperature=0,
        # 900 no dejaba sitio al razonamiento: 3000 con el esfuerzo de la tabla.
        max_tokens=3000,
        reasoning_effort=settings.reasoning_effort_for("segundo_orden"),
        response_format=ResponseFormat.json_schema(_SCHEMA, name="second_order_themes"),
        metadata=_prompt().trace_metadata(),
    )
    # Pin an approved model: task overrides may route to paid models.
    if not is_owner_approved_model(provider.model_router.resolve(request), settings):
        raise RuntimeError("Second-order model is not owner-approved")
    # Salida con CJK, ingles mezclado o tokens corruptos: un reintento y, si falla, el
    # llamador degrada al camino determinista. before_retry reserva cuota para el 2o intento.
    response = (
        await complete_guarded(provider, request, source="second_order", before_retry=before_retry)
    ).response
    return Extraction.model_validate(parse_json_response(response.text)), response


def _company_context(db: Session, company_id: int | None, tenant_id) -> str:
    """Verified DB context about the news subject, prepended to the LLM prompt.

    Only persisted metadata is shown (ticker, name, sector, industry, factor
    tags, selected peer relationships). With no peer rows the prompt says
    "sin relaciones conocidas" so the model never invents relationships.
    """
    if company_id is None or not isinstance(tenant_id, int):
        return ""
    company = db.get(Company, company_id)
    if company is None:
        return ""
    lines = [
        "Contexto verificado de la base de datos sobre la empresa de la noticia:",
        (f"- Ticker: {company.ticker}; Nombre: {company.name}; "
         f"Sector: {company.sector}; Industria: {company.industry}"),
    ]
    specific_tags = [value for value in company.factor_tags or [] if isinstance(value, str) and _specific_exposure(value)]
    if specific_tags:
        lines.append(f"- Etiquetas de exposición concreta: {', '.join(specific_tags)}")
    peers = db.execute(
        select(Company.ticker, Company.name)
        .join(PeerRelationship, PeerRelationship.peer_company_id == Company.id)
        .where(
            PeerRelationship.tenant_id == tenant_id,
            PeerRelationship.company_id == company.id,
            PeerRelationship.selected.is_(True),
        )
        .order_by(Company.ticker)
    ).all()
    if peers:
        lines.append("- Relaciones conocidas: " + ", ".join(f"{ticker} ({name})" for ticker, name in peers))
    else:
        lines.append("- Relaciones conocidas: sin relaciones conocidas")
    return "\n".join(lines)


def _candidate_reason(company: Company, theme: Theme, field: str, value: str) -> str:
    """Concrete match reason; a hypothesis is never presented as a fact."""
    label = _REASON_FIELD_LABEL.get(field, field)
    return (f"La {label} '{value}' de {company.ticker} coincide exactamente con "
            f"la exposición '{theme.exposure}' de la hipótesis; "
            "es una coincidencia de metadatos, no exposición económica verificada.")


# Risk/maturity/style tags describe a stock, not an economic transmission channel.
# Never use them to connect unrelated industries through a speculative narrative.
_GENERIC_EXPOSURES = frozenset({
    "speculative", "speculative growth", "pre fcf", "pre revenue", "pre profit",
    "unprofitable", "growth", "value", "small cap", "mid cap", "large cap",
    "high risk", "high beta", "cyclical", "defensive", "unknown", "other", "unassigned",
})


# An umbrella industry cannot substantiate a product-specific indirect channel.
# In particular "Insurance" does not show that a firm underwrites D&O risk.
_BROAD_INDUSTRIES = frozenset({
    "insurance", "insurers", "aseguradoras", "seguros", "financial services",
    "financials", "technology", "healthcare", "industrials", "legal", "services",
})


def _match_relevance(company: Company, exposure: str) -> tuple[int, str, str] | None:
    """Rank only observed exact metadata evidence, not market size or alphabet."""
    normalized = _normalized(exposure)
    if normalized in _BROAD_INDUSTRIES:
        return None
    fields = [(field, value) for field, value in _company_exposures(company)
              if field != "sector" and _normalized(value) == normalized]
    if not fields:
        return None
    # Concrete factor tagging is closer to the proposed channel than an
    # industry label alone. Independent industry agreement adds support.
    fields.sort(key=lambda item: item[0] != "factor_tags")
    score = sum(2 if field == "factor_tags" else 1 for field, _ in dict(fields).items())
    field, value = fields[0]
    return score, field, value


def _specific_exposure(value: str) -> bool:
    normalized = _normalized(value)
    return bool(normalized) and normalized not in _GENERIC_EXPOSURES and normalized not in _BROAD_INDUSTRIES


def _company_exposures(company: Company) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for field in ("sector", "industry"):
        value = getattr(company, field, None)
        if isinstance(value, str) and _normalized(value) not in {"", "unknown", "other", "unassigned"}:
            values.append((field, value))
    for value in company.factor_tags or []:
        if isinstance(value, str) and _specific_exposure(value):
            values.append(("factor_tags", value))
    return values


def _source_date(event: Any) -> str | None:
    if (event.metadata_ or {}).get("date_source") != "source":
        return None
    date = event.date
    return date.replace(tzinfo=UTC).isoformat() if date.tzinfo is None else date.isoformat()


def _jev_marker(theme: Theme) -> dict:
    """Metadata only. No TypeSafe call until the credit-aware #560 is present."""
    if os.getenv("SECOND_ORDER_JEV_ENABLED") != "1":
        return {"direction": None, "confidence": None, "backend": None}
    # nosemgrep: gerarai-broad-except-pass -- marca opcional de credito Jev (best-effort)
    try:
        from app.services.jev_availability import credit_status
        from app.services.jev_gates import jev_choice_sync

        # The gate itself handles exhausted credit and operational failures.
        # A read-only availability check prevents calling an older ungated Jev.
        state = credit_status()["status"]
        if state != "activo":
            return {"direction": None, "confidence": None, "backend": None}
        decision = jev_choice_sync(
            name="second_order_direction",
            text="; ".join(f"{step.cause} -> {step.effect}" for step in theme.chain),
            instructions="Label the hypothetical direction for the exposed industry; do not verify facts.",
            criteria={"beneficiada": "could benefit", "perjudicada": "could be harmed",
                      "incierta": "direction unclear"},
        )
        if decision and decision.label in {"beneficiada", "perjudicada", "incierta"}:
            return {"direction": decision.label, "confidence": decision.confidence,
                    "backend": getattr(decision, "backend", "jev")}
    except Exception:  # noqa: BLE001 - all marker failures are best effort
        pass
    return {"direction": None, "confidence": None, "backend": None}


def _candidate(company: Company, theme: Theme, field: str, value: str,
               event: Any, marker: dict, reason: str) -> dict:
    source = {"news_event_id": event.id, "url": event.url, "published_at": _source_date(event)}
    return {
        "ticker": company.ticker, "company_name": company.name,
        "reason": reason,
        "direction": theme.direction, "confidence": marker["confidence"],
        "jev_direction": marker["direction"],
        "jev_backend": marker["backend"], "status": "hipótesis_no_verificada",
        "exposure": {"field": field, "value": value},
        "causal_chain": [step.model_dump() for step in theme.chain],
        "sources": [source],
        "limitations": [
            "La noticia y sus cifras son claims de la fuente, no hechos verificados.",
            "La exposición viene de metadatos del universo; no acredita ingresos ni sensibilidad económica.",
        ],
    }


# Accent folding replicated in SQL so the prefilter sees the same alphabet
# as _normalized (NFKD -> ascii-ignore) for the Spanish Latin-1 set, BOTH
# cases (ÁÉÍÓÚÜÑ áéíóúüñ): SQLite lower() is ASCII-only, so uppercase
# accented letters must be replaced BEFORE lower(). JSON-cast columns get two
# SEPARATE folded expressions OR-ed (real characters for Postgres JSONB;
# \uXXXX escapes for SQLite's JSON serializer) because one 28-deep replace
# chain overflows SQLite's parser stack.
# Scope declared: Spanish accented vowels + ñ, upper and lower case. Other
# Unicode simply misses the prefilter; this is NOT a general Unicode superset.
_SQL_FOLD_UPPER = (("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"),
                   ("Ú", "U"), ("Ü", "U"), ("Ñ", "N"))
_SQL_FOLD_LOWER = (("á", "a"), ("é", "e"), ("í", "i"),
                   ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n"))
_SQL_FOLD_ESCAPES_UPPER = (("\\u00c1", "A"), ("\\u00c9", "E"), ("\\u00cd", "I"),
                           ("\\u00d3", "O"), ("\\u00da", "U"), ("\\u00dc", "U"),
                           ("\\u00d1", "N"))
_SQL_FOLD_ESCAPES_LOWER = (("\\u00e1", "a"), ("\\u00e9", "e"), ("\\u00ed", "i"),
                           ("\\u00f3", "o"), ("\\u00fa", "u"), ("\\u00fc", "u"),
                           ("\\u00f1", "n"))


def _fold_pairs(expr, upper, lower):
    for ch, base in upper:
        expr = func.replace(expr, ch, base)
    expr = func.lower(expr)
    for ch, base in lower:
        expr = func.replace(expr, ch, base)
    return expr


def _sql_fold(column):
    """Fold real characters: Postgres JSONB and plain text columns."""
    return _fold_pairs(column, _SQL_FOLD_UPPER, _SQL_FOLD_LOWER)


def _sql_fold_json_escapes(column):
    """Fold escaped sequences: SQLite JSON serializer output."""
    return _fold_pairs(column, _SQL_FOLD_ESCAPES_UPPER, _SQL_FOLD_ESCAPES_LOWER)


def _matching_companies(db: Session, exposure: str) -> list[Company]:
    """Prefilter in SQL, then confirm normalized metadata matches in Python.

    The prefilter is a proven superset of the Python check: Python accepts a
    company only when _normalized(field) == _normalized(exposure), and every
    [a-z0-9]+ token of the normalized exposure then appears verbatim as an
    alnum run inside the accent-folded lowercase field (normalization only
    turns punctuation into spaces; it never removes or merges alnum chars).
    Matching ANY token in ANY folded field therefore keeps every exact match.

    No LIMIT before Python validation: an early cap could drop a real match
    behind loose token hits. The result is still selective in practice (the
    alternative was loading the whole universe); the candidate cap applies
    after validation.
    """
    exposure_norm = _normalized(exposure)
    if not exposure_norm:
        return []
    token_predicates = [
        or_(
            _sql_fold(Company.sector).like(f"%{token}%"),
            _sql_fold(Company.industry).like(f"%{token}%"),
            _sql_fold(cast(Company.factor_tags, String)).like(f"%{token}%"),
            _sql_fold_json_escapes(cast(Company.factor_tags, String)).like(f"%{token}%"),
        )
        for token in exposure_norm.split()
    ]
    return list(db.scalars(
        select(Company).where(or_(*token_predicates)).order_by(Company.id)
    ).all())


def analyze_second_order(db: Session, event: NewsEvent, *, use_llm: bool = False) -> dict:
    """No thesis/score/alert changes or ingestion filtering; reserves LLM quota."""
    # Copia escalares y suelta la transaccion antes de cualquier LLM: sin conexion
    # retenida durante la espera ni en el reintento (pool 5+10).
    tenant_id = db.info.get("tenant_id")
    meta = dict(event.metadata_ or {})
    title = event.title
    # Un titular generado por la app (headline_from_source=False) no es un
    # claim de la fuente: el claim analizable es el titular original.
    if meta.get("headline_from_source") is False:
        source_headline = meta.get("source_headline")
        if isinstance(source_headline, str) and source_headline.strip():
            title = source_headline.strip()
    snap: Any = SimpleNamespace(
        id=event.id, url=event.url, source=event.source, date=event.date,
        metadata_=meta, title=title, summary=event.summary, company_id=event.company_id,
    )
    context = _company_context(db, snap.company_id, tenant_id)
    if use_llm:
        db.commit()
    text = " ".join(part for part in (snap.title, snap.summary) if part)[:3500]
    mode = "determinista"
    llm_note = None
    llm_quota = None
    llm_model = None
    extraction = _fallback(text)
    if use_llm:
        if os.getenv("SECOND_ORDER_LLM_ENABLED") != "1":
            llm_note = "Análisis LLM desactivado por configuración."
        else:
            try:
                llm_quota = reserve_llm_call(tenant_id, get_settings())
                if not llm_quota["allowed"]:
                    llm_note = "Análisis LLM no disponible: tope alcanzado."
                else:
                    def _reserve_retry() -> None:
                        nonlocal llm_quota
                        retry = reserve_llm_call(tenant_id, get_settings())
                        llm_quota = retry
                        if not retry["allowed"]:
                            raise RuntimeError("second-order LLM quota exhausted before retry")

                    extraction, response = run_from_any_context(
                        _extract_with_llm(text, context=context, before_retry=_reserve_retry)
                    )
                    llm_model = getattr(response, "model", None) or None
                    mode = "llm"
            except Exception:  # noqa: BLE001 - never claim a failed call worked
                llm_note = "Análisis LLM no disponible; se usa el camino determinista."
    # The LLM does not select companies. Only exact, normalized matches in
    # existing industry/factor metadata can create a candidate; a bare sector
    # coincidence has no concrete reason and is discarded.
    candidates = []
    subject = db.get(Company, snap.company_id) if snap.company_id is not None else None
    subject_ticker = subject.ticker.strip().upper() if subject else None
    seen_tickers: set[str] = set()
    theme_pools = []
    seen_themes: set[str] = set()
    for theme in extraction.themes:
        theme_key = _normalized(theme.exposure)
        if not theme.chain or not _specific_exposure(theme.exposure) or theme_key in seen_themes:
            continue
        seen_themes.add(theme_key)
        matches = []
        for company in _matching_companies(db, theme.exposure):
            ticker = company.ticker.strip().upper()
            if not ticker or company.id == snap.company_id or ticker == subject_ticker:
                continue
            relevance = _match_relevance(company, theme.exposure)
            if relevance:
                score, field, value = relevance
                matches.append((company, field, value, score))
        # Score is grounded exact metadata support. ID only stabilizes equal
        # evidence ties; it is not a relevance claim or an alphabetical ranking.
        matches.sort(key=lambda row: (-row[3], row[0].id))
        theme_pools.append((theme, matches))
    # All themes get a first opportunity before any theme gets a second.
    # Repeated/aliased tickers never consume either the per-theme or total cap.
    markers: dict[str, dict] = {}
    for _round in range(CANDIDATES_PER_THEME):
        for theme, matches in theme_pools:
            while matches:
                company, field, value, score = matches.pop(0)
                ticker = company.ticker.strip().upper()
                if ticker in seen_tickers:
                    continue
                theme_key = _normalized(theme.exposure)
                if theme_key not in markers:
                    markers[theme_key] = _jev_marker(theme)
                marker = markers[theme_key]
                candidate = _candidate(company, theme, field, value, snap, marker,
                                       _candidate_reason(company, theme, field, value))
                candidate["selection_basis"] = {
                    "kind": "exact_metadata_support", "score": score,
                    "limitation": "Prioridad por metadatos exactos, no por impacto económico verificado. Empates sin preferencia económica.",
                }
                candidates.append(candidate)
                seen_tickers.add(ticker)
                break
            if len(candidates) >= CANDIDATE_LIMIT:
                break
        if len(candidates) >= CANDIDATE_LIMIT:
            break
    return {
        "news_event_id": snap.id, "status": "hipótesis_no_verificadas" if candidates else "sin_datos",
        "generated_at": datetime.now(UTC).isoformat(), "mode": mode,
        "source": {"url": snap.url, "published_at": _source_date(snap), "name": snap.source},
        "source_claim": text, "source_verified": False,
        "themes": [theme.model_dump() for theme in extraction.themes],
        "candidates": candidates, "limited_to": CANDIDATE_LIMIT,
        "per_theme_limit": CANDIDATES_PER_THEME, "note": llm_note,
        "llm_model": llm_model, "llm_quota": llm_quota,
        "warning": "Solo hipótesis. Verificar fuente, cadena causal y exposición antes de usar como conclusión.",
    }
