import os
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.llm.chat_provider import create_chat_llm_provider
from app.models import (
    CashBalance,
    Claim,
    Company,
    Document,
    DocumentChunk,
    EvidenceSuggestion,
    FinancialFact,
    MarketPrice,
    NewsEvent,
    Position,
    ResearchSession,
    ThesisSection,
    ThesisVersion,
)
from app.schemas import ChatPageContext, ChatResponse
from app.services.brain_service import SMALL_TALK_RE, resolve_page_context, small_talk_answer
from app.services.chat_synthesis_service import ChatSynthesisService
from app.services.claim_scope import live_claims
from app.services.company_resolver import resolve_company
from app.services.library_context import retrieve_library_context
from app.services.memory_service import MemoryService, remember_note
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.source_hierarchy_service import source_tier_key

# Los nombres son los que persiste la ingesta (financial_ingestion_service):
# el efectivo se guarda como "cash_and_equivalents"; pedir "cash" aqui dejaba
# ese hueco siempre sin cubrir ("Faltan entradas: cash") con el dato ya en DB.
KEY_FACT_METRICS = [
    "revenue",
    "free_cash_flow",
    "operating_cash_flow",
    "net_income",
    "net_debt",
    "cash_and_equivalents",
    "total_debt",
    "shares_diluted",
]

_METRIC_LABELS_ES = {
    "revenue": "ingresos",
    "free_cash_flow": "flujo de caja libre",
    "operating_cash_flow": "flujo de caja operativo",
    "net_income": "beneficio neto",
    "net_debt": "deuda neta",
    "cash_and_equivalents": "efectivo y equivalentes",
    "total_debt": "deuda total",
    "shares_diluted": "acciones diluidas",
}

_MONTHS_ES = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)


def _fmt_number_es(number: float, digits: int = 2) -> str:
    """1.234.567,89 al estilo es-ES (puntos de miles, coma decimal)."""
    text = f"{number:,.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(",", "").replace(".", ",").replace("", ".")


def _fmt_money_es(number: float, digits: int = 2) -> str:
    """Importe con decimales fijos en es-ES: 7.933,60 (no se recortan ceros)."""
    text = f"{number:,.{digits}f}"
    return text.replace(",", " ").replace(".", ",").replace(" ", ".")


def _fmt_value_es(value: float | None, unit: str | None) -> str:
    """Cifra legible: -71,5 millones USD / 1,14 mil millones USD / 300 acciones."""
    if value is None:
        return "sin dato"
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if unit == "shares":
        suffix = " acciones"
    elif unit and unit != "decimal":
        suffix = f" {unit}"
    else:
        suffix = ""
    if magnitude >= 1e9:
        rendered = f"{_fmt_number_es(magnitude / 1e9)} mil millones"
    elif magnitude >= 1e6:
        rendered = f"{_fmt_number_es(magnitude / 1e6)} millones"
    elif magnitude >= 1e3:
        rendered = f"{_fmt_number_es(magnitude / 1e3)} mil"
    else:
        rendered = _fmt_number_es(magnitude)
    return f"{sign}{rendered}{suffix}"


def _fmt_period_es(period: str | None, fiscal_year: int | None = None,
                   fiscal_quarter: str | None = None) -> str:
    """'2025-12-31:FY' -> 'ejercicio 2025'; '2025-09-30:Q3' -> 'Q3 2025'."""
    text = (period or "").strip()
    match = re.match(r"^(\d{4})-\d{2}-\d{2}:(FY|Q[1-4])$", text)
    if match:
        year, quarter = match.groups()
        return f"ejercicio {year}" if quarter == "FY" else f"{quarter} {year}"
    if fiscal_year:
        if fiscal_quarter and fiscal_quarter != "FY":
            return f"{fiscal_quarter} {fiscal_year}"
        return f"ejercicio {fiscal_year}"
    return text or "periodo sin fecha"


def _fmt_date_es(iso_date: str | None) -> str:
    """'2026-10-16' -> '16 oct 2026'."""
    text = (iso_date or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if not match:
        return text or "sin fecha"
    year, month, day = match.groups()
    month_index = int(month) - 1
    if not 0 <= month_index < 12:
        return text
    return f"{int(day)} {_MONTHS_ES[month_index]} {year}"


def _natural_company_answer(
    *,
    company: Company,
    facts: list[FinancialFact],
    thesis: ThesisVersion | None,
    news: list[NewsEvent],
    missing_metrics: list[str],
    claims: list[Claim],
    contradiction_claims: list[Claim],
    price_line: str | None,
    memory_notes: list[str] | None = None,
) -> str:
    """Respuesta visible: prosa natural en castellano.

    La estructura HECHO/CALCULO/... sigue en `sections` (panel plegado con
    sus citas); lo que lee el usuario de un vistazo es esto. Nada de IDs de
    fuente, siglas de seccion ni titulares en ingles en el cuerpo: el detalle
    queda plegado.
    """
    parts: list[str] = []
    if price_line:
        parts.append(price_line)
    if facts:
        rendered = "; ".join(
            f"{_METRIC_LABELS_ES.get(fact.metric, fact.metric)} "
            f"{_fmt_value_es(_decimal_to_float(fact.value), fact.unit)} "
            f"({_fmt_period_es(fact.period, fact.fiscal_year, fact.fiscal_quarter)}, "
            f"{fact.source_type or 'fuente almacenada'})"
            for fact in facts[:5]
        )
        parts.append(f"Datos almacenados: {rendered}.")
    else:
        parts.append(
            f"Todavia no tengo hechos financieros fiables almacenados para "
            f"{company.ticker}; ingiere sus fuentes primarias (SEC/FMP) y te "
            f"respondo con cifras."
        )
    if thesis:
        rating = f", rating {thesis.rating}" if thesis.rating else ""
        parts.append(
            f"Tengo guardada la tesis v{thesis.version} "
            f"(estado {thesis.status}{rating})."
        )
    seen_notes: set[str] = set()
    for content in (memory_notes or [])[:3]:
        note = _short(content, 180)
        key = " ".join(note.lower().split())
        if key in seen_notes:
            continue
        seen_notes.add(key)
        parts.append(f"De tus notas guardadas: '{note}'.")
    if news:
        dated = sorted(
            (event for event in news if event.date),
            key=lambda event: event.date, reverse=True,
        )
        headlines = [
            f"'{_short(event.title, 110)}' ({_fmt_date_es(event.date.isoformat())})"
            for event in (dated or news)[:2]
        ]
        parts.append("Ultimas noticias guardadas: " + "; ".join(headlines) + ".")
    if contradiction_claims:
        parts.append(
            f"Hay {len(contradiction_claims)} afirmaciones contradichas o "
            f"desactualizadas que conviene revisar."
        )
    elif any(claim.status == "unverified" for claim in claims):
        parts.append("Hay afirmaciones pendientes de verificar.")
    if missing_metrics:
        labels = ", ".join(_METRIC_LABELS_ES.get(m, m) for m in missing_metrics)
        parts.append(f"Aun faltan datos almacenados de: {labels}.")
    return "\n\n".join(parts)

def _decimal_to_float(value: Decimal | int | float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _short(text: str, limit: int = 420) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."



# Saludos y marca viven en el cerebro común (brain_service). Alias
# compatibles para los tests que los importaban de aquí.
_SMALL_TALK_RE = SMALL_TALK_RE
_small_talk_answer = small_talk_answer


_COMMON_WORD_TICKERS = frozenset(
    {"META", "NOW", "IT", "ON", "CAT", "ALL", "ARE", "KEY", "LOW", "FAST", "WELL", "A", "BIG", "GOOD"}
)
# Palabra previa que convierte la palabra comun en un sustantivo ("mi meta").
_DETERMINERS = frozenset(
    {"mi", "mis", "tu", "tus", "su", "sus", "la", "las", "el", "un", "una", "esta", "esa", "otra",
     "nuestra", "my", "your", "our", "the", "a", "this", "that", "his", "her", "their"}
)
_COMPANY_CUE_RE = re.compile(
    r"(?i)\b(tesis|thesis|an[aá]lisis|analiza\w*|ficha|empresa|compa[nñ][ií]a|"
    r"acci[oó]n(?:es)?|cotiza\w*|precio|valoraci[oó]n|resultados|balance|"
    r"riesgos?|catalizadores?|noticias?|dividendos?|fundamentales|stock)\b"
)
_PORTFOLIO_SELF_RE = re.compile(
    r"(?i)\b(?:mi|mis)\s+(?:cartera|posici[oó]n(?:es)?|inversi[oó]n(?:es)?|acciones|holdings)\b"
    r"|\bmy\s+(?:portfolio|positions|holdings)\b"
)
_ORDER_VERB_RE = re.compile(r"(?i)\b(compra|compro|comprar|vende|vendo|vender|ejecuta|buy|sell)\b")
# Preguntas de cartera sin la formula "mi cartera": recuento, peso, valor o
# patrimonio. Se responden con los datos guardados del tenant, nunca con una
# orden ni con una recomendacion.
_PORTFOLIO_QUERY_RE = re.compile(
    r"(?i)\b(?:cu[aá]ntas\s+posiciones|posiciones\s+(?:abiertas\s+)?tengo|"
    r"qu[eé]\s+posici[oó]n\s+pesa|patrimonio(?:\s+neto)?|"
    r"valor\s+(?:total\s+)?de\s+(?:la|mi)\s+cartera|"
    r"c[oó]mo\s+va\s+(?:la|mi)\s+cartera)\b"
)
# Pregunta por la posicion de un ticker concreto ("peso de ASTS",
# "cuanto tengo en ASTS", "acciones de ASTS que tengo").
_POSITION_QUERY_RE = re.compile(
    r"(?i)\b(?:peso|posici[oó]n|acciones)\b[^.!?\n]{0,40}\b(?:cartera|tengo|mis)\b"
    r"|\b(?:peso|posici[oó]n)\s+(?:de|en|que)\b"
    r"|\bcu[aá]nt[oa]s?\s+(?:acciones\s+)?(?:tengo|vale|valen|tienen)\b"
)
# Cuando la misma frase pide ademas caja o patrimonio se adjunta ese bloque.
_NET_WORTH_CUE_RE = re.compile(r"(?i)\b(?:patrimonio|caja|margen|neto)\b")


class ChatService:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.memory = MemoryService()
        self.provider = provider or create_chat_llm_provider()

    def _resolve_company(self, db: Session, question: str, scope: str, ticker: str | None) -> Company | None:
        if ticker:
            return resolve_company(db, ticker)
        if scope == "portfolio":
            # El asistente global manda scope="portfolio" sin ticker. Antes eso
            # cortaba aqui y "meta tesis?" se quedaba sin empresa. Ahora solo
            # se resuelve una mencion EXPLICITA (ver _explicit_mention); sin
            # ella la pregunta sigue siendo de cartera.
            return self._explicit_mention(db, question)
        # Índice por ticker + regex de palabra completa: evita falsos
        # positivos por substring ("A" dentro de "APPLE", "IT" en "WITH")
        # y no hace un scan substring por fila.
        companies = list(db.scalars(select(Company)).all())
        by_ticker = {company.ticker.upper(): company for company in companies}
        tokens = re.findall(r"[A-Z0-9][A-Z0-9.\-]*", question.upper())
        for token in tokens:
            if token in by_ticker:
                return by_ticker[token]
        for candidate in companies:
            if re.search(rf"\b{re.escape(candidate.ticker)}\b", question, re.IGNORECASE):
                return candidate
        return None

    def _explicit_mention(self, db: Session, question: str) -> Company | None:
        """Empresa nombrada por su ticker en el texto, para el scope global.

        - Ticker escrito en mayusculas (>= 2 letras): vale siempre.
        - Ticker en minusculas ("meta tesis?"): vale si tiene >= 3 letras y no
          es una palabra corriente; si lo es ("meta", "now") exige ademas una
          pista de consulta sobre empresas, para que "mi meta de ahorro" no se
          convierta en una pregunta sobre Meta Platforms.
        - Con varias empresas distintas nombradas no se elige ninguna: la
          ambiguedad se deja al flujo general en vez de adivinar.
        """
        companies = list(db.scalars(select(Company)).all())
        by_ticker = {company.ticker.upper(): company for company in companies}
        found: dict[str, Company] = {}
        has_cue = bool(_COMPANY_CUE_RE.search(question))
        all_caps = not any(ch.islower() for ch in question)
        recent: list[str] = []  # las dos palabras anteriores (ventana de 2)
        for match in re.finditer(r"[A-Za-z][A-Za-z.\-]*", question):
            raw = match.group(0).strip(".-")
            after_determiner = any(word in _DETERMINERS for word in recent)
            recent = [*recent, raw.lower()][-2:]
            if not raw:
                continue
            token = raw.upper()
            company = by_ticker.get(token)
            if company is None:
                continue
            if token in _COMMON_WORD_TICKERS:
                # Palabra corriente: siempre exige pista de empresa y que no
                # vaya tras un determinante/posesivo ("mi meta de ahorro").
                # Un ticker escrito en MAYUSCULAS (>= 3 letras) en una frase en
                # minusculas es deliberado; en minusculas pide pista de empresa.
                deliberate = raw.isupper() and not all_caps and len(token) >= 3
                ok = (deliberate or (len(token) >= 3 and has_cue)) and not after_determiner
                if len(token) < 3:
                    ok = has_cue and raw.isupper() and not all_caps and not after_determiner
            elif raw.isupper() and not all_caps:
                ok = len(token) >= 2
            else:
                ok = len(token) >= 3
            if ok:
                found[token] = company
        return next(iter(found.values())) if len(found) == 1 else None

    def _latest_thesis(self, db: Session, company: Company) -> ThesisVersion | None:
        return db.scalar(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .limit(1)
        )

    def _key_facts(self, db: Session, company: Company, limit: int = 8) -> list[FinancialFact]:
        # One query instead of one per metric: pick the latest fact per
        # metric in Python, preserving the per-metric ordering contract.
        rows = db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric.in_(KEY_FACT_METRICS),
            )
            .order_by(
                FinancialFact.metric,
                FinancialFact.fiscal_year.desc().nullslast(),
                desc(FinancialFact.created_at),
                desc(FinancialFact.id),
            )
        ).all()
        latest: dict[str, FinancialFact] = {}
        for row in rows:
            latest.setdefault(row.metric, row)
        facts = [latest[m] for m in KEY_FACT_METRICS if m in latest]
        return facts[:limit]

    def _sections(self, db: Session, thesis: ThesisVersion | None, limit: int = 6) -> list[ThesisSection]:
        if not thesis:
            return []
        return list(
            db.scalars(
                select(ThesisSection)
                .where(ThesisSection.thesis_version_id == thesis.id)
                .order_by(ThesisSection.order_index, ThesisSection.section_key)
                .limit(limit)
            ).all()
        )

    def _claims(self, db: Session, company: Company, limit: int = 8) -> list[Claim]:
        # The live claims only: the chat answers about the current thesis, so
        # citing a claim from a superseded version answers a different question.
        return live_claims(db, company, limit=limit)

    def _recent_news(self, db: Session, company: Company, limit: int = 4) -> list[NewsEvent]:
        return list(
            db.scalars(
                select(NewsEvent)
                .where(NewsEvent.company_id == company.id)
                .order_by(desc(NewsEvent.date))
                .limit(limit)
            ).all()
        )

    def _recent_sessions(self, db: Session, company: Company | None, limit: int = 4) -> list[ResearchSession]:
        statement = select(ResearchSession).order_by(desc(ResearchSession.updated_at)).limit(limit)
        if company:
            statement = statement.where(ResearchSession.company_id == company.id)
        return list(db.scalars(statement).all())

    def _document_chunks(self, db: Session, company: Company, question: str, limit: int = 4) -> list[tuple[DocumentChunk, Document]]:
        query_terms = [term.lower() for term in question.split() if len(term) >= 4]
        rows = db.execute(
            select(DocumentChunk, Document)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.company_id == company.id)
            .order_by(desc(Document.published_at), DocumentChunk.chunk_index)
            .limit(80)
        ).all()
        scored: list[tuple[int, DocumentChunk, Document]] = []
        for chunk, document in rows:
            lowered = chunk.text.lower()
            overlap = sum(1 for term in query_terms if term in lowered)
            scored.append((overlap, chunk, document))
        scored.sort(key=lambda item: (item[0], item[2].published_at is not None), reverse=True)
        return [(chunk, document) for _, chunk, document in scored[:limit]]

    def _rag_chunks(
        self,
        db: Session,
        question: str,
        company: Company | None,
        limit: int = 4,
    ) -> list[dict]:
        if os.getenv("CAVAAI_ENABLE_VECTOR_CHAT") != "1":
            return []
        try:
            from app.services.rag import RAGIndex

            hits = RAGIndex().search(
                question,
                ticker=company.ticker if company else None,
                limit=limit,
                tenant_id=db.info.get("tenant_id"),
            )
            tenant_id = db.info.get("tenant_id")
            if type(tenant_id) is not int or tenant_id <= 0:
                return []
            rows = []
            seen = set()
            for hit in hits:
                chunk_id = hit.get("entity_id")
                if hit.get("entity_type") != "document_chunk" or type(chunk_id) is not int or chunk_id in seen:
                    continue
                statement = (
                    select(DocumentChunk, Document)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(DocumentChunk.id == chunk_id, DocumentChunk.tenant_id == tenant_id,
                           Document.tenant_id == tenant_id)
                )
                if company:
                    statement = statement.where(Document.company_id == company.id)
                row = db.execute(statement).first()
                if not row:
                    continue
                chunk, document = row
                if not chunk.text.strip() or not chunk.qdrant_point_id or str(hit.get("point_id")) != chunk.qdrant_point_id:
                    continue
                seen.add(chunk_id)
                rows.append({
                    "point_id": chunk.qdrant_point_id, "entity_id": chunk.id,
                    "document_id": document.id, "title": document.title,
                    "source_type": document.source_type, "text": chunk.text,
                    "url": document.source_url, "chunk_index": chunk.chunk_index,
                })
            return rows
        except Exception:
            return []

    def _source_entry(self, kind: str, source_id: int | str | None, title: str, **extra) -> dict:
        payload = {
            "type": kind,
            "id": source_id,
            "title": title,
        }
        payload.update({key: value for key, value in extra.items() if value is not None})
        return payload

    async def answer(
        self,
        db: Session,
        question: str,
        scope: str,
        ticker: str | None,
        *,
        enable_debate: bool | None = None,
        use_jev: bool = True,
        page: ChatPageContext | None = None,
    ) -> ChatResponse:
        # Contexto de página explícito ("Viendo X"): el ticker de la página se
        # resuelve en servidor en el catálogo global; el contenido privado
        # posterior sigue aislado por tenant. El eco vuelve al cliente
        # para la pastilla. Prioridad: ticker explícito > mención en el texto
        # > ticker de la página.
        page_context = resolve_page_context(db, page)
        context_echo = page_context.echo() if page_context else None
        if _SMALL_TALK_RE.match(question or ""):
            return ChatResponse(
                answer=_small_talk_answer(question),
                sources=[],
                model="small-talk",
                prompt_version="small-talk-v1",
                confidence=0.9,
                llm_trace={"path": "small_talk"},
                context=context_echo,
            )
        # Routing por compania RESUELTA del texto, no solo por el parametro
        # ticker: "precio de ASTS" sin campo ticker va igualmente por la
        # ruta estructurada con validacion financiera.
        company = self._resolve_company(db, question, scope, ticker)
        if company is None and page_context is not None:
            company = page_context.company
        # Memoria SOLO ante "recuerda ..." explicito; respuesta visible, sin LLM.
        note = remember_note(question)
        if note is not None:
            item = self.memory.write_explicit_note(db, note, company, scope)
            return ChatResponse(
                answer=f"Apuntado: {note}",
                sources=[self._source_entry("memory_item", item.id, "Nota guardada por tu orden")],
                model="memory-note",
                prompt_version="memory-note-v1",
                confidence=1.0,
                llm_trace={"path": "memory_note"},
                context=context_echo,
            )
        if (
            company is not None
            and _POSITION_QUERY_RE.search(question or "")
            and not _ORDER_VERB_RE.search(question or "")
        ):
            position_answer = self._position_answer(db, company, question or "")
            if position_answer is not None:
                position_answer.context = context_echo
                return position_answer
        if (
            company is None
            and not ticker
            and (
                _PORTFOLIO_SELF_RE.search(question or "")
                or _PORTFOLIO_QUERY_RE.search(question or "")
            )
            and not _ORDER_VERB_RE.search(question or "")
        ):
            portfolio_answer = self._portfolio_overview(db)
            if portfolio_answer is not None:
                portfolio_answer.context = context_echo
                return portfolio_answer
        if company is not None and not ticker:
            ticker = company.ticker
        # La abstencion financiera vive en el clasificador unificado de
        # synthesize_general (ronda 8 auditor): los conceptos financieros
        # genericos llegan al LLM y solo lo especifico/ambiguo se abstiene.
        baseline = self._deterministic_answer(db, question, scope, ticker)
        # Fast-path Jev (4): si la pregunta es una consulta factual simple
        # (baseline_ok, conf >= 0.8), el contexto determinista ya responde y
        # se ahorra la llamada LLM de sintesis. Sin key o ante fallo,
        # sintesis como siempre.
        if use_jev and ticker:
            try:
                from app.services.jev_gates import (
                    CHAT_BASELINE_OK_THRESHOLD,
                    CHAT_NEEDS_LLM_CRITERIA,
                    CHAT_NEEDS_LLM_INSTRUCTIONS,
                    jev_choice_or_none,
                )

                gate = await jev_choice_or_none(
                    name="chat_needs_llm",
                    text=question,
                    instructions=CHAT_NEEDS_LLM_INSTRUCTIONS,
                    criteria=CHAT_NEEDS_LLM_CRITERIA,
                )
                if (
                    gate is not None
                    and gate.label == "baseline_ok"
                    and gate.confidence >= CHAT_BASELINE_OK_THRESHOLD
                ):
                    baseline.model = "deterministic"
                    baseline.llm_trace = {
                        "fast_path": True,
                        "reason": "jev_baseline_ok",
                        "jev_gate": {
                            "label": gate.label,
                            "confidence": gate.confidence,
                        },
                    }
                    baseline.context = context_echo
                    return baseline
            except Exception:  # noqa: BLE001 — Jev nunca rompe el chat
                pass
        synthesis = ChatSynthesisService(self.provider)
        if ticker:
            response = await synthesis.synthesize(
                question=question,
                ticker=ticker,
                baseline=baseline,
                db=db,
                enable_debate=enable_debate,
            )
        else:
            response = await synthesis.synthesize_general(
                question=question,
                baseline=baseline,
                db=db,
            )
        response.context = context_echo
        return response

    def _portfolio_overview(self, db: Session, limit: int = 15) -> ChatResponse | None:
        """Resumen de la cartera del usuario leido de la BD, sin LLM ni recomendaciones.

        Solo lo guardado (cantidad, coste medio, valor y fecha). Sin posiciones
        devuelve None y la pregunta sigue por la ruta de siempre.
        """
        # TenantOwnedMixin no filtra solo: sin tenant valido no se lee ninguna cartera.
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Company.id == Position.company_id)
                .where(Position.quantity > 0, Position.tenant_id == tenant_id)
            ).all()
        )
        if not rows:
            return None

        def _value(pos: Position) -> float:
            raw = pos.market_value_base if pos.market_value_base is not None else pos.market_value
            return float(raw or 0)

        rows.sort(key=lambda row: _value(row[0]), reverse=True)
        total = sum(_value(pos) for pos, _ in rows)
        as_of = max(pos.as_of for pos, _ in rows)
        bases = {pos.base_currency or "EUR" for pos, _ in rows}
        mixed = len(bases) > 1
        base = rows[0][0].base_currency or "EUR"
        lines = []
        sources = []
        for pos, comp in rows[:limit]:
            weight = (
                f" ({_fmt_number_es(_value(pos) / total * 100, 1)} %)" if total > 0 and not mixed else ""
            )
            lines.append(
                f"- {comp.ticker}: {_fmt_number_es(float(pos.quantity), 4)} acciones, "
                f"coste medio {_fmt_number_es(float(pos.average_cost), 2)} {pos.currency}, "
                f"valor {_fmt_number_es(_value(pos), 2)} {pos.base_currency or 'EUR'}{weight}"
            )
            sources.append(self._source_entry("position", pos.id, f"Posición {comp.ticker}", as_of=str(pos.as_of)))
        extra = f"\n(Se muestran las {limit} mayores de {len(rows)}.)" if len(rows) > limit else ""
        total_text = (
            "monedas base distintas, sin total"
            if mixed
            else f"valor total {_fmt_money_es(total)} {base}"
        )
        answer = (
            f"Tu cartera guardada tiene {len(rows)} posiciones abiertas, {total_text}, "
            f"con datos a {_fmt_date_es(as_of.isoformat())}:\n"
            + "\n".join(lines)
            + extra
            + "\n\nSon los datos guardados en la app, no una recomendación. "
            "Pregunta por un ticker para ver su ficha y fuentes."
        )
        cash_line = self._cash_line(
            db, tenant_id, base if not mixed else None,
            positions_total=None if mixed else total,
        )
        if cash_line:
            answer += "\n\n" + cash_line
        return ChatResponse(
            answer=answer,
            sources=sources,
            model="deterministic",
            prompt_version="portfolio-overview-v1",
            confidence=0.9,
            llm_trace={"path": "portfolio_overview", "generated": False, "provider_calls": 0},
        )

    def _cash_line(
        self,
        db: Session,
        tenant_id: int,
        base: str | None,
        *,
        positions_total: float | None = None,
    ) -> str | None:
        """Bloque de caja/margen/neto leido de cash_balances del tenant.

        Con ``base`` (monedas base homogeneas) convierte cada saldo con la
        tabla FX point-in-time y da caja, deuda de margen y neto; sin tipo de
        cambio para una divisa lo declara y no la suma. Con monedas base
        distintas (``base=None``) solo lista los saldos por divisa, sin
        inventar un total.
        """
        cash_rows = list(
            db.scalars(
                select(CashBalance).where(CashBalance.tenant_id == tenant_id)
            ).all()
        )
        if not cash_rows:
            return None
        native: dict[str, float] = {}
        for row in cash_rows:
            native[row.currency] = native.get(row.currency, 0.0) + float(row.balance)
        if base is None:
            parts = [
                f"{_fmt_money_es(amount)} {currency}"
                for currency, amount in sorted(native.items())
            ]
            return (
                "Caja guardada por divisa (sin sumar, monedas base distintas): "
                + ", ".join(parts) + "."
            )
        table = PortfolioFXService().fx_table(
            db,
            currencies=set(native),
            base_currency=base,
            as_of_max=max((row.as_of for row in cash_rows), default=date.today()),
        )
        assets = 0.0
        debt = 0.0
        missing: list[str] = []
        for currency, amount in sorted(native.items()):
            as_of = max(
                (row.as_of for row in cash_rows if row.currency == currency),
                default=date.today(),
            )
            rate = PortfolioFXService.rate_from_table(
                table, quote_currency=currency, base_currency=base, as_of=as_of,
            )
            if rate is None:
                missing.append(currency)
                continue
            converted = amount * float(rate)
            if converted >= 0:
                assets += converted
            else:
                debt += -converted
        line = ""
        pieces: list[str] = []
        if assets:
            pieces.append(f"caja {_fmt_money_es(assets)} {base}")
        if debt:
            pieces.append(f"deuda de margen {_fmt_money_es(debt)} {base}")
        if pieces:
            line = "Además: " + " y ".join(pieces)
            if positions_total is not None:
                net = positions_total + assets - debt
                line += f"; patrimonio neto {_fmt_money_es(net)} {base}"
            line += "."
        if missing:
            detalle = ", ".join(f"{_fmt_money_es(native[c])} {c}" for c in missing)
            line += (
                f" Sin tipo de cambio guardado para {', '.join(missing)}"
                f" ({detalle}): esa caja no entra en la suma."
            )
        return line.strip() or None

    def _position_answer(self, db: Session, company: Company, question: str) -> ChatResponse | None:
        """Posicion guardada de un ticker: cantidad, coste, valor y peso.

        Determinista y sin recomendacion; sin posiciones del tenant devuelve
        None y la pregunta sigue por la ruta de empresa.
        """
        tenant_id = db.info.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            return None
        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Company.id == Position.company_id)
                .where(Position.quantity > 0, Position.tenant_id == tenant_id)
            ).all()
        )
        if not rows:
            return None

        def _value(pos: Position) -> float:
            raw = pos.market_value_base if pos.market_value_base is not None else pos.market_value
            return float(raw or 0)

        found = [(pos, comp) for pos, comp in rows if comp.id == company.id]
        if not found:
            answer = (
                f"No tienes ninguna posición guardada en {company.ticker}; "
                f"tu cartera guardada tiene {len(rows)} posiciones abiertas en otros tickers. "
                "Son los datos guardados en la app, no una recomendación."
            )
            return ChatResponse(
                answer=answer,
                sources=[],
                model="deterministic",
                prompt_version="portfolio-position-v1",
                confidence=0.9,
                llm_trace={"path": "portfolio_position", "generated": False, "provider_calls": 0},
            )
        pos, comp = found[0]
        total = sum(_value(p) for p, _ in rows)
        bases = {p.base_currency or "EUR" for p, _ in rows}
        mixed = len(bases) > 1
        if total > 0 and not mixed:
            weight_text = f", un {_fmt_number_es(_value(pos) / total * 100, 1)} % del valor de tus posiciones"
        else:
            weight_text = " (sin peso: monedas base distintas)"
        answer = (
            f"Tu posición guardada en {comp.ticker}: {_fmt_number_es(float(pos.quantity), 4)} acciones, "
            f"coste medio {_fmt_money_es(float(pos.average_cost))} {pos.currency}, "
            f"valor {_fmt_money_es(_value(pos))} {pos.base_currency or 'EUR'}{weight_text}, "
            f"con datos a {_fmt_date_es(pos.as_of.isoformat())}."
        )
        if _NET_WORTH_CUE_RE.search(question):
            cash_line = self._cash_line(
                db, tenant_id, None if mixed else (pos.base_currency or "EUR"),
                positions_total=None if mixed else total,
            )
            if cash_line:
                answer += "\n\n" + cash_line
        answer += "\n\nSon los datos guardados en la app, no una recomendación."
        return ChatResponse(
            answer=answer,
            sources=[self._source_entry("position", pos.id, f"Posición {comp.ticker}", as_of=str(pos.as_of))],
            model="deterministic",
            prompt_version="portfolio-position-v1",
            confidence=0.9,
            llm_trace={"path": "portfolio_position", "generated": False, "provider_calls": 0},
        )

    def _deterministic_answer(
        self, db: Session, question: str, scope: str, ticker: str | None
    ) -> ChatResponse:
        company = self._resolve_company(db, question, scope, ticker)
        # El cerebro es SOLO LECTURA: la memoria se recupera, nunca se escribe
        # desde el chat (maybe_write_from_chat quedó retirado).
        retrieved_memory = self.memory.retrieve(db, question, company, scope=scope, limit=6)
        recent_sessions = self._recent_sessions(db, company)

        library_context = (
            retrieve_library_context(db, question)
            if os.getenv("CAVAAI_ENABLE_VECTOR_CHAT") == "1" else []
        )
        library_lines = [
            f"- Investment doctrine, not a company fact: {item['text']} "
            f"[knowledge_chunk:{item['id']}]" for item in library_context
        ]
        sources: list[dict] = list(library_context)
        proposed_actions: list[str] = []

        if company:
            thesis = self._latest_thesis(db, company)
            sections = self._sections(db, thesis)
            facts = self._key_facts(db, company)
            claims = self._claims(db, company)
            news = self._recent_news(db, company)
            db_chunks = self._document_chunks(db, company, question)
            rag_chunks = self._rag_chunks(db, question, company)
            evidence_suggestions = list(
                db.scalars(
                    select(EvidenceSuggestion)
                    .where(
                        EvidenceSuggestion.company_id == company.id,
                        EvidenceSuggestion.status == "pending",
                    )
                    .order_by(
                        desc(EvidenceSuggestion.confidence),
                        desc(EvidenceSuggestion.created_at),
                    )
                    .limit(6)
                ).all()
            )

            if thesis:
                sources.append(
                    self._source_entry(
                        "thesis_version",
                        thesis.id,
                        f"{company.ticker} thesis v{thesis.version}",
                        status=thesis.status,
                    )
                )
            for section in sections:
                sources.append(
                    self._source_entry(
                        "thesis_section",
                        section.id,
                        section.title,
                        section_key=section.section_key,
                        confidence=_decimal_to_float(section.confidence),
                    )
                )
            for fact in facts:
                sources.append(
                    self._source_entry(
                        "financial_fact",
                        fact.id,
                        f"{fact.metric} {fact.period}",
                        metric=fact.metric,
                        value=_decimal_to_float(fact.value),
                        unit=fact.unit,
                        source_type=fact.source_type,
                        source_tier=source_tier_key(fact.source_type),
                        confidence=_decimal_to_float(fact.confidence),
                    )
                )
            for claim in claims:
                sources.append(
                    self._source_entry(
                        "claim",
                        claim.id,
                        _short(claim.statement, 120),
                        status=claim.status,
                        materiality_score=claim.materiality_score,
                        confidence=_decimal_to_float(claim.confidence),
                    )
                )
                for evidence in claim.evidence[:2]:
                    sources.append(
                        self._source_entry(
                            "claim_evidence",
                            evidence.id,
                            _short(evidence.summary, 140),
                            claim_id=claim.id,
                            evidence_type=evidence.evidence_type,
                            document_id=evidence.document_id,
                            document_chunk_id=evidence.document_chunk_id,
                            source_tier=evidence.source_tier,
                            confidence=_decimal_to_float(evidence.confidence),
                        )
                    )
            for chunk, document in db_chunks:
                sources.append(
                    self._source_entry(
                        "document_chunk",
                        chunk.id,
                        document.title,
                        document_id=document.id,
                        source_type=document.source_type,
                        source_tier=source_tier_key(document.source_type),
                        url=document.source_url,
                        text=_short(chunk.text, 240),
                    )
                )
            for chunk in rag_chunks:
                sources.append(
                    self._source_entry(
                        "rag_chunk",
                        chunk.get("point_id"),
                        chunk.get("title") or "Fragmento de documento indexado",
                        document_id=chunk.get("document_id"),
                        knowledge_document_id=chunk.get("knowledge_document_id"),
                        collection_id=chunk.get("collection_id"),
                        page_number=chunk.get("page_number"),
                        chunk_index=chunk.get("chunk_index"),
                        entity_id=chunk.get("entity_id"),
                        source_type=chunk.get("source_type"),
                        source_tier=source_tier_key(chunk.get("source_type")),
                        score=chunk.get("score"),
                        url=chunk.get("url"),
                        text=_short(chunk.get("text", ""), 240),
                    )
                )
            latest_price = db.scalars(
                select(MarketPrice)
                .where(MarketPrice.company_id == company.id)
                .where(MarketPrice.date <= date.today())
                .order_by(desc(MarketPrice.date))
                .limit(1)
            ).first()
            price_line: str | None = None
            if latest_price is not None:
                # adj_close NULL = spot sin ajustar por splits/dividendos
                # (p. ej. intraday): se distingue de cierre diario y se
                # declara el proveedor. Fechas futuras excluidas: una barra
                # de manana no es cotizacion actual.
                adjusted = latest_price.adj_close is not None
                value = latest_price.adj_close if adjusted else latest_price.close
                kind = "cierre" if adjusted else "spot"
                price_line = (
                    f"{company.ticker} cotiza a "
                    f"{_fmt_number_es(float(value))} {company.currency} "
                    f"({kind} del {_fmt_date_es(latest_price.date.isoformat())}, "
                    f"fuente {latest_price.source})."
                )
                sources.append(
                    self._source_entry(
                        "market_price",
                        latest_price.id,
                        f"{company.ticker} {value} {company.currency} ({kind} {latest_price.date.isoformat()}, {latest_price.source})",
                        date=latest_price.date.isoformat(),
                        price=str(value),
                        currency=company.currency,
                        adjusted=adjusted,
                    )
                )
            for event in news:
                sources.append(
                    self._source_entry(
                        "news_event",
                        event.id,
                        event.title,
                        event_type=event.event_type,
                        materiality_score=event.materiality_score,
                        impact_direction=event.impact_direction,
                        requires_update=event.requires_update,
                    )
                )

            for retrieved in retrieved_memory:
                sources.append(
                    self._source_entry(
                        "memory_item",
                        retrieved.item.id,
                        _short(retrieved.item.content, 140),
                        memory_type=retrieved.item.memory_type,
                        importance=retrieved.item.importance,
                        score=retrieved.score,
                        reason=retrieved.reason,
                    )
                )
            if not thesis:
                proposed_actions.append(f"Crear la primera tesis para {company.ticker}")
            if any(claim.status in {"unverified", "contradicted"} for claim in claims):
                proposed_actions.append("Revisar afirmaciones no verificadas o contradichas")
            if any(event.requires_update for event in news):
                proposed_actions.append("Revisar cambios de tesis por noticias materiales")
            if not facts:
                proposed_actions.append("Ingerir hechos financieros SEC/FMP antes de sacar conclusiones cuantitativas")

            facts_text = (
                "\n".join(
                    f"- {fact.metric}: {_decimal_to_float(fact.value)} {fact.unit} "
                    f"({fact.period}, {source_tier_key(fact.source_type)}) "
                    f"[financial_fact:{fact.id}]"
                    for fact in facts[:5]
                )
                or "- No hay hechos financieros fiables almacenados para esta empresa."
            )
            calculations_text = (
                "- No se ha hecho un calculo nuevo en esta respuesta; los hechos almacenados se citan como entradas."
                if facts
                else "- Calculo bloqueado: faltan hechos financieros almacenados."
            )
            assumptions_text = (
                "\n".join(
                    f"- {_short(item.item.content, 180)} "
                    f"[memory_item:{item.item.id}]"
                    for item in retrieved_memory[:3]
                )
                or "- No se recupero memoria relevante del usuario."
            )
            claim_lines = [
                f"- [{claim.status}] {_short(claim.statement, 180)} "
                f"[claim:{claim.id}]"
                for claim in claims[:5]
                if claim.status != "supported"
            ]
            unverified_text = "\n".join(claim_lines) or "- No hay afirmaciones sin resolver en el contexto recuperado."
            thesis_text = (
                f"Tesis {company.ticker} v{thesis.version}: `{thesis.status}` con rating `{thesis.rating}`. "
                f"Valor esperado={_decimal_to_float(thesis.expected_value)} frente a precio actual={_decimal_to_float(thesis.current_price)}. "
                f"[thesis_version:{thesis.id}]"
                if thesis
                else f"Aun no hay tesis almacenada para {company.ticker}."
            )
            rag_evidence_lines = [
                f"- {_short(chunk.get('text', ''), 180)} "
                f"({chunk.get('source_type') or 'indexed'}) "
                f"[rag_chunk:{chunk.get('point_id')}]"
                for chunk in rag_chunks[:3]
                if chunk.get("point_id") and chunk.get("text")
            ] + library_lines
            db_evidence_lines = [
                f"- {_short(chunk.text, 180)} ({document.source_type}) "
                f"[document_chunk:{chunk.id}]"
                for chunk, document in db_chunks[:3]
            ]
            news_lines = [
                f"- {event.title} [{event.impact_direction}, materiality {event.materiality_score}] "
                f"[news_event:{event.id}]"
                for event in news[:3]
            ]
            contradiction_claims = [
                claim
                for claim in claims
                if claim.status in {"contradicted", "superseded", "stale"}
            ]
            contradictions_text = (
                "\n".join(
                    f"- [{claim.status}] {_short(claim.statement, 180)} "
                    f"[claim:{claim.id}]"
                    for claim in contradiction_claims
                )
                or "- No se encontraron contradicciones en las afirmaciones recuperadas."
            )
            found_metrics = {fact.metric for fact in facts}
            missing_metrics = [
                metric for metric in KEY_FACT_METRICS if metric not in found_metrics
            ]
            insufficient_text = (
                f"- Faltan entradas almacenadas: {', '.join(missing_metrics)}."
                if missing_metrics
                else "- No falta ninguna entrada financiera clave en esta recuperacion."
            )
            conclusion_text = (
                "- Hay que revisar la tesis antes de cambiar supuestos."
                if contradiction_claims
                or any(event.requires_update for event in news)
                else "- La evidencia recuperada no exige un cambio automatico de tesis; seguir monitorizando."
            )

            # La respuesta VISIBLE es prosa natural en castellano (pedido de
            # Nico 2026-10-17: "que sea lectura natural y en castellano"). El
            # volcado estructurado con citas no desaparece: sigue en
            # `sections`, que el frontend muestra plegado, y es el contexto
            # que verifica la sintesis LLM.
            answer = _natural_company_answer(
                company=company,
                facts=facts,
                thesis=thesis,
                news=news,
                missing_metrics=missing_metrics,
                claims=claims,
                contradiction_claims=contradiction_claims,
                price_line=price_line,
                memory_notes=[item.item.content for item in retrieved_memory[:3]],
            )

            sections = [
                {
                    "key": "facts",
                    "body": "\n".join([facts_text, *news_lines]),
                    "citations": [
                        f"financial_fact:{fact.id}" for fact in facts[:5]
                    ],
                },
                {
                    "key": "calculations",
                    "body": calculations_text,
                    "citations": [
                        f"financial_fact:{fact.id}" for fact in facts[:5]
                    ],
                },
                {
                    "key": "user_hypotheses",
                    "body": assumptions_text,
                    "citations": [
                        f"memory_item:{item.item.id}"
                        for item in retrieved_memory[:3]
                    ],
                },
                {
                    "key": "unverified_claims",
                    "body": unverified_text,
                    "citations": [
                        f"claim:{claim.id}"
                        for claim in claims[:5]
                        if claim.status != "supported"
                    ],
                },
                {
                    "key": "inferences",
                    "body": "\n".join(
                        [thesis_text, *db_evidence_lines, *rag_evidence_lines]
                    )
                    if (rag_evidence_lines or db_evidence_lines)
                    else thesis_text,
                    "citations": [
                        *([f"thesis_version:{thesis.id}"] if thesis else []),
                        *[f"knowledge_chunk:{item['id']}" for item in library_context],
                        *[
                            f"rag_chunk:{chunk.get('point_id')}"
                            for chunk in rag_chunks[:3]
                            if chunk.get("point_id") and chunk.get("text")
                        ],
                    ],
                },
                {
                    "key": "contradictions",
                    "body": contradictions_text,
                    "citations": [
                        f"claim:{claim.id}" for claim in contradiction_claims
                    ],
                },
                {
                    "key": "insufficient_data",
                    "body": insufficient_text,
                    "citations": [],
                },
                {
                    "key": "conclusion",
                    "body": conclusion_text,
                    "citations": [
                        *[
                            f"claim:{claim.id}"
                            for claim in contradiction_claims
                        ],
                        *[
                            f"news_event:{event.id}"
                            for event in news
                            if event.requires_update
                        ],
                    ],
                },
            ]

            return ChatResponse(
                answer=answer,
                sections=sections,
                sources=sources,
                blocked=not thesis or not sources,
                proposed_actions=list(dict.fromkeys(proposed_actions)),
                evidence_suggestions=[
                    {
                        "id": suggestion.id,
                        "statement": suggestion.statement,
                        "relation": suggestion.relation,
                        "suggestion_type": suggestion.suggestion_type,
                        "confidence": float(suggestion.confidence),
                        "suggested_claim_id": suggestion.suggested_claim_id,
                        "document_chunk_id": suggestion.document_chunk_id,
                    }
                    for suggestion in evidence_suggestions
                ],
                prompt_version="source-aware-synthesis-v1",
                model="deterministic",
            )

        portfolio_memories = [retrieved.item for retrieved in retrieved_memory]
        for item in portfolio_memories:
            sources.append(
                self._source_entry(
                    "memory_item",
                    item.id,
                    _short(item.content, 140),
                    memory_type=item.memory_type,
                    importance=item.importance,
                )
            )
        for session in recent_sessions:
            sources.append(
                self._source_entry(
                    "research_session",
                    session.id,
                    session.title,
                    status=session.status,
                    summary=_short(session.summary, 180),
                )
            )

        answer = (
            "CONTEXTO\n- Pregunta general sin ticker: el asistente dispone de memorias de cartera, sesiones de research y contexto documental.\n\n"
            "SIN CALCULOS\n- Sin ticker no hay calculos de cartera en esta respuesta.\n\n"
            "MEMORIAS\n"
            f"{chr(10).join(f'- {_short(item.content, 180)}' for item in portfolio_memories[:5]) or '- No se recuperó memoria de cartera relevante.'}\n\n"
            "SIN AFIRMACIONES DE EMPRESA\n- Pregunta por un ticker concreto para revisar afirmaciones y evidencia.\n\n"
            "CONTEXTO DOCUMENTAL\n"
            + ("\n".join(library_lines) or "- Para respuestas con fuentes de empresa, indica un ticker o ingiere evidencia primero.")
        )
        return ChatResponse(
            answer=answer,
            sections=[
                {
                    "key": "facts",
                    "body": "Solo contexto de memorias de cartera y sesiones de research.",
                    "citations": [
                        f"memory_item:{item.id}"
                        for item in portfolio_memories[:5]
                    ],
                },
                {
                    "key": "calculations",
                    "body": "No se hizo ningún cálculo de cartera.",
                    "citations": [],
                },
                {
                    "key": "user_hypotheses",
                    "body": "Memorias de cartera recuperadas.",
                    "citations": [
                        f"memory_item:{item.id}"
                        for item in portfolio_memories[:5]
                    ],
                },
                {
                    "key": "unverified_claims",
                    "body": "Pregunta por un ticker concreto para revisar afirmaciones y evidencia.",
                    "citations": [],
                },
                {
                    "key": "inferences",
                    "body": "\n".join(library_lines) or "Hace falta un ticker para inferencias de empresa.",
                    "citations": [f"knowledge_chunk:{item['id']}" for item in library_context],
                },
                {
                    "key": "contradictions",
                    "body": "No se seleccionaron afirmaciones de empresa.",
                    "citations": [],
                },
                {
                    "key": "insufficient_data",
                    "body": "Indica un ticker o ingiere evidencia de cartera.",
                    "citations": [],
                },
                {
                    "key": "conclusion",
                    "body": "No hay conclusión de empresa disponible.",
                    "citations": [],
                },
            ],
            sources=sources,
            blocked=False,
            proposed_actions=["Pregunta por un ticker", "Ingiere documentos de cartera"],
            prompt_version="source-aware-synthesis-v1",
            model="deterministic",
        )
