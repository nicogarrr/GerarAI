import re
import time
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, ExternalClaim, NewsEvent, ThesisChange, ThesisVersion
from app.schemas import ManualNewsResponse, NewsFeedItem, NewsIngestResponse
from app.services.claim_intelligence_service import ClaimIntelligenceService
from app.services.company_catalog import all_companies
from app.services.company_resolver import resolve_company
from app.services.materiality_service import MaterialityService, apply_recency_policy
from app.services.review_alert_service import ReviewAlertService
from app.services.source_hierarchy_service import classify_source
from app.services.text_clip import clip_words

# Boilerplate de movimiento de posición institucional reescrito por agregadores
# (patrón 13F de MarketBeat: «X Shares Purchased by Y», «Stock: Z Raises
# Stake»...). Cada fila es un hecho distinto pero de muy bajo valor unitario:
# en portada se agrupan por empresa y día (una fila con recuento).
POSITION_CHANGE_HEADLINE_RE = re.compile(
    r"(?:\bshares\s+(?:purchased|sold|bought|acquired)\b"
    r"|\b(?:buys|sells|purchases|acquires|bought|acquired)\b[\w\s,.$()]*\bshares\b"
    r"|\b(?:raises|lowers|boosts|cuts|increases|reduces|trims|grows|lifts)\b[\w\s,.$()]*\b(?:stake|position|holdings)\b"
    r"|\b(?:stake|position|holdings)\s+(?:raised|lowered|boosted|cut|increased|reduced|lifted|trimmed)\b)",
    re.IGNORECASE,
)


_GENERIC_HEADLINE_RE = re.compile(
    r"se\s+abre\s+en\s+una\s+nueva\s+ventana|opens?\s+in\s+(?:a\s+)?new\s+window",
    re.IGNORECASE,
)


def is_generic_headline(headline: str | None) -> bool:
    """Texto de enlace del visor de la fuente que llegó como «titular»
    (SEC: «Comunicado de prensa del Q2 2026, archivo PDF, (se abre en una
    nueva ventana)», visto en prod con ZETA 19-oct-2026). No describe la
    noticia: no se guarda como titular de la fuente ni sustituye al
    recorte del resumen. Solo la frase exacta de enlace de visor: un
    «archivo PDF» suelto puede ser parte de un titular real (objeción del
    auditor, 19-oct-2026)."""
    return bool(headline) and bool(_GENERIC_HEADLINE_RE.search(headline))


def is_viewer_link_only(title: str | None, summary: str | None) -> bool:
    """Fila sin contenido: el titular Y el resumen son solo el texto de enlace
    del visor de la fuente (ZETA 19-oct-2026: «Press Release of Q2 2026, PDF
    file, (opens in new window)» como titular y como resumen). No hay nada
    que mostrar. Si el resumen aporta texto real, la fila se conserva."""
    return is_generic_headline(title) and is_generic_headline(summary)


def is_position_change_headline(headline: str) -> bool:
    """Titular boilerplate de cambio de posición institucional (spam 13F)."""
    return bool(headline) and bool(POSITION_CHANGE_HEADLINE_RE.search(headline))


def position_change_cluster_title(ticker: str | None, source: str, count: int) -> str:
    """Etiqueta generada para la fila agrupada (no verbatim de la fuente:
    la fila se marca headline_from_source=False)."""
    donde = f" en {ticker}" if ticker else ""
    return f"{count} movimientos de inversores institucionales{donde} · {source}"
from app.services.thesis_graph_service import ThesisGraphService
from app.services.ticker_news_lane import (
    STRICT_NAME_PATTERNS as STRICT_TICKERS,
)
from app.services.ticker_news_lane import (
    fails_strict_name,
    is_competitor_only,
    is_law_firm_solicitation,
)

_NAME_NOISE = {"inc", "corp", "corporation", "co", "company", "ltd", "plc", "sa", "nv", "ag", "the", "group", "holdings", "holding", "limited", "sme", "s.a."}

# Siglas que son palabras o abreviaturas comunes: solo vinculan con cashtag,
# «(NYSE: X)» o el nombre distintivo de la empresa; el contexto no basta.
_AMBIGUOUS_TICKERS = {
    "A", "ALL", "IT", "ON", "ARE", "FOR", "AI", "EU", "UK", "US", "FED", "GDP", "CEO", "CFO", "NHS",
    "T", "F", "C", "V", "K", "D", "NOW", "ONE", "TWO", "WELL", "REAL", "LOVE", "BIG", "CAT", "HAS",
    "SO", "BE", "BY", "AN", "AS", "AT", "DO", "GO", "IF", "IN", "OR", "TV", "PM", "AM", "MAN", "OUT",
    "NEW", "OLD", "TOP", "LOW", "HIGH", "FAST", "GOOD", "BEST", "CASH", "FUN", "PLAY", "SEE", "CAN",
}

_FINANCE_WORDS = re.compile(
    r"^(stocks?|shares?|equity|earnings|dividends?|guidance|ipo|trading|trades?|traded|halted|"
    r"buybacks?|repurchase|upgrade[sd]?|downgrade[sd]?|analysts?|revenue|quarterly|eps|"
    r"acciones|bolsa|resultados|dividendo)$",
    flags=re.IGNORECASE,
)
_TARGET_ANCHOR = re.compile(r"^(price|precio)$", flags=re.IGNORECASE)
# «target» suelto NO es evidencia: «CB Target J. Cobbins» (cornerback de
# fútbol americano) vinculaba una noticia deportiva a Chubb (CB). Solo vale la
# locución «price target» / «precio objetivo».
_WORD = re.compile(r"[\w$&.\-]+")
_PROXIMITY_WORDS = 3

EVIDENCE_STRONG = 3  # cashtag o «(NYSE: X)»
EVIDENCE_NAME = 2  # ticker + nombre distintivo de la empresa
EVIDENCE_CONTEXT = 1  # ticker + termino financiero a <= 3 palabras



def _change_summary(headline: str, impact: str) -> str:
    """Resumen del cambio sin repetir el titular dentro del cuerpo."""
    head = (headline or "").strip().rstrip(".")
    body = (impact or "").strip()
    if body and head and body.lower().lstrip().startswith(head.lower()[:60]):
        return body
    prefix = "Noticia material que requiere revisión de la tesis"
    return f"{prefix}: {head}. {body}".strip() if body else f"{prefix}: {head}."


def _near_finance_word(ticker: str, text: str) -> bool:
    words = [w.strip(".,;:()[]\"'") for w in _WORD.findall(text)]
    for i, w in enumerate(words):
        if w != ticker:
            continue
        lo, hi = max(0, i - _PROXIMITY_WORDS), min(len(words), i + _PROXIMITY_WORDS + 1)
        for j, x in enumerate(words[lo:hi], start=lo):
            if j == i:
                continue
            if _FINANCE_WORDS.match(x):
                return True
            # «target»/«objetivo» solo cuenta como locución financiera:
            #  - «price target» / «precio objetivo» (ancla delante),
            #  - «target price» («CB target price raised»),
            #  - «target to/at $N» («Jefferies sets CB target at $280»).
            # «target» suelto no: «CB Target J. Cobbins» es un cornerback.
            if x.lower() in ("target", "objetivo"):
                if j > 0 and _TARGET_ANCHOR.match(words[j - 1]):
                    return True
                next_w = words[j + 1].lower() if j + 1 < len(words) else ""
                if next_w == "price":
                    return True
                if next_w in ("to", "at") and j + 2 < len(words) and words[j + 2].startswith("$"):
                    return True
    return False


def _ticker_evidence_level(ticker: str, name: str | None, text: str) -> int:
    """0 = sin evidencia; 1-3 = fuerza creciente de la evidencia de que el texto habla de esa empresa."""
    if not ticker or not text:
        return 0
    tk = re.escape(ticker)
    if re.search(rf"\${tk}\b", text, flags=re.IGNORECASE):
        return EVIDENCE_STRONG
    if re.search(rf"\b(?:NYSE|NASDAQ|AMEX|BME|LSE|EPA|ETR)\s*:\s*{tk}\b", text, flags=re.IGNORECASE):
        return EVIDENCE_STRONG
    # Siglas que chocan con una palabra o sigla corriente (AENA, CB cornerback,
    # CPT visado estudiantil): vale una forma completa verificada o la sigla
    # con contexto del sector; la proximidad financiera suelta no basta.
    if ticker.upper() in STRICT_TICKERS:
        return 0 if fails_strict_name(ticker, text) else EVIDENCE_NAME
    if not re.search(rf"(?<![\w$]){tk}(?![\w])", text):
        return 0
    for token in re.findall(r"[A-Za-z][A-Za-z.&'-]+", name or ""):
        if token.lower().strip(".") in _NAME_NOISE or len(token) < 4:
            continue
        if re.search(rf"\b{re.escape(token)}\b", text, flags=re.IGNORECASE):
            return EVIDENCE_NAME
    if ticker.upper() in _AMBIGUOUS_TICKERS or len(ticker) == 1:
        return 0
    if len(ticker) >= 4:
        return EVIDENCE_CONTEXT
    return EVIDENCE_CONTEXT if _near_finance_word(ticker, text) else 0


def _ticker_evidence(ticker: str, name: str | None, text: str) -> bool:
    return _ticker_evidence_level(ticker, name, text) > 0


class _LLMBudgetSkipped(Exception):
    """Salta el bloque de enriquecimiento Jev/LLM al agotarse el presupuesto."""


def _llm_budget_exceeded(deadline: float | None) -> bool:
    """True si el presupuesto de tiempo para enriquecimiento LLM/Jev se agoto.

    Los gates Jev y las marcas LLM son metadatos best-effort: cuando el actor
    de ingesta agota su presupuesto (prod: refresh_rss_feeds murio a los 601 s
    dentro de un gate Jev con la BD lenta), la ingesta DETERMINISTA continua y
    solo se omite el enriquecimiento - mismo resultado que "sin key/fallo".
    """
    return deadline is not None and time.monotonic() >= deadline


class NewsService:
    def __init__(self) -> None:
        self.materiality = MaterialityService()
        self.claim_intelligence = ClaimIntelligenceService()
        self.thesis_graph = ThesisGraphService()
        self.reviews = ReviewAlertService()

    def detect_ticker(self, db: Session, text: str) -> Company | None:
        """Vincula un texto a una empresa solo con evidencia suficiente.

        Se evaluan todas las empresas y gana la de evidencia mas fuerte
        (cashtag/bolsa > nombre > contexto financiero cercano); si hay empate
        en el nivel mas alto no se vincula nada. Las siglas ambiguas (A, ALL,
        IT, ON...) solo valen con cashtag, bolsa o nombre.
        """
        best_level = 0
        best: list[Company] = []
        for company in all_companies(db):
            level = _ticker_evidence_level(company.ticker, company.name, text)
            if level > best_level:
                best_level, best = level, [company]
            elif level == best_level and level > 0:
                best.append(company)
        return best[0] if len(best) == 1 else None

    def _company_for_item(self, db: Session, text: str, ticker: str | None = None) -> Company | None:
        if ticker:
            company = resolve_company(db, ticker)
            if company:
                return company
        return self.detect_ticker(db, text)

    def _is_duplicate(
        self,
        db: Session,
        company: Company | None,
        text: str,
        url: str | None,
        *,
        title_is_identity: bool = True,
        headline: str | None = None,
    ) -> bool:
        if url:
            duplicate_url = db.scalar(
                select(NewsEvent.id)
                .where(NewsEvent.url == url, *tenant_filters(db, NewsEvent))
                .limit(1)
            )
            if duplicate_url:
                return True
        if not title_is_identity:
            # Título de display generado por GerarAI (p.ej. «8-K presentado
            # ante la SEC»): no identifica el evento — dos filings distintos
            # del mismo form comparten título canónico. La identidad es la
            # URL (o no hay dedup posible); casar por título aquí descartaría
            # filings reales como falsos duplicados.
            return False
        from app.services.news_identity import equivalent_news_event

        # Misma URL con otra query/fragmento, o mismo titular con otra puntuación: es la misma noticia.
        if equivalent_news_event(
            db, company_id=company.id if company else None, url=url, title=text
        ) is not None:
            return True
        # El título guardado puede ser el compuesto recortado (histórico) o el
        # titular íntegro del medio (nuevo): se casa contra ambos para que una
        # re-ingesta sin URL siga detectando el duplicado.
        candidates = {" ".join(text.strip().split())[:180]}
        if headline:
            candidates.add(" ".join(headline.strip().split())[:500])
        duplicate_title = db.scalar(
            select(NewsEvent.id)
            .where(
                NewsEvent.company_id == (company.id if company else None),
                NewsEvent.title.in_(candidates),
                *tenant_filters(db, NewsEvent),
            )
            .limit(1)
        )
        return duplicate_title is not None

    def _analyze_news(
        self,
        db: Session,
        text: str,
        source: str,
        url: str | None,
        ticker: str | None = None,
        published_at: datetime | None = None,
        connector: str | None = None,
        date_source_label: str | None = None,
        source_headline: str | None = None,
        headline_from_source: bool = True,
        news_lane: str | None = None,
        macro_theme: str | None = None,
        detect_company: bool = True,
        llm_deadline: float | None = None,
    ) -> ManualNewsResponse:
        # detect_company=False: carriles sin ticker (p.ej. macro) nunca
        # vinculan empresa por coincidencia de texto.
        company = self._company_for_item(db, text, ticker) if detect_company else None
        # Gate Jev (3): duplicate/noise con confianza >= 0.85 -> via ligera:
        # se registra el evento en el tracker pero se omite el analisis
        # semantico, el ThesisChange/review y el claim scan. Best-effort:
        # sin key o ante fallo, via completa como siempre.
        jev_light = False
        jev_light_marker = ""
        # Presupuesto agotado: se omite el gate (metadata best-effort) y la
        # ingesta determinista sigue - como cuando Jev no esta configurado.
        if _llm_budget_exceeded(llm_deadline):
            pass
        else:
            try:
                from app.services.jev_gates import NEWS_ACTION_THRESHOLD, jev_news_action_sync

                decision = jev_news_action_sync(text)
                if (
                    decision is not None
                    and decision.label in {"duplicate", "noise"}
                    and decision.confidence >= NEWS_ACTION_THRESHOLD
                ):
                    jev_light = True
                    jev_light_marker = (
                        f"jev_news_action({decision.label}, "
                        f"conf={decision.confidence:.2f}) -> analisis ligero "
                        "(sin ThesisChange ni claim scan)"
                    )
            except Exception:  # noqa: BLE001 — Jev nunca rompe ingesta
                jev_light = False
        assessment = self.materiality.assess_news(db, company, text, source, url, published_at=published_at)
        materiality_reasons = list(assessment.reasons)
        if jev_light_marker:
            materiality_reasons.append(jev_light_marker)
        if jev_light:
            semantic_impact = None
            materiality_score = assessment.materiality_score
            requires_update = False
        else:
            semantic_impact = (
                self.thesis_graph.assess_impact(
                    db,
                    company,
                    text,
                    base_materiality=assessment.materiality_score,
                    impact_direction=assessment.impact_direction,
                )
                if company
                else None
            )
            materiality_score = (
                semantic_impact.impact_score if semantic_impact else assessment.materiality_score
            )
            requires_update = assessment.requires_update or bool(
                semantic_impact and semantic_impact.affected_claim_ids and materiality_score >= 7
            )
        # El impacto semantico puede subir la nota por encima del tope de
        # relevancia: la misma regla conservadora se reaplica (solo baja, no descarta).
        from app.services.materiality_service import (
            UNRELATED_NEWS_MAX_MATERIALITY,
            is_unrelated_generic_news,
        )

        if (
            is_unrelated_generic_news(text, company, source, url)
            and materiality_score > UNRELATED_NEWS_MAX_MATERIALITY
        ):
            materiality_score = UNRELATED_NEWS_MAX_MATERIALITY
            requires_update = False
            materiality_reasons.append(
                f"sin mención de la empresa en fuente genérica => max {UNRELATED_NEWS_MAX_MATERIALITY}"
            )
        # La politica de recencia tambien cubre la urgencia derivada del
        # impacto semantico: un filing antiguo nunca es urgente por recencia.
        requires_update = apply_recency_policy(requires_update, published_at, materiality_reasons)
        # Relevancia: una noticia que solo menciona de pasada a la empresa (titular sin ella y < 3
        # menciones) se guarda, pero no abre revision de tesis ni alerta "material". Filings
        # (sec/ir) quedan fuera: su titular es generico y la fuente es primaria.
        if requires_update and company and connector not in ("sec", "ir"):
            from app.services.news_relevance import company_is_central

            if not company_is_central(
                company.ticker, company.name, headline=source_headline, text=text,
            ):
                requires_update = False
                materiality_reasons.append("relevancia: la empresa solo se menciona de pasada")

        summary = clip_words(" ".join(text.strip().split()), 320)
        # Tipo de noticia con Jev (earnings/filing/macro/opinion): 1 llamada
        # best-effort (~$0.042/MTok in) guardada en metadata. Sin
        # TYPESAFE_API_KEY o ante error, la noticia se ingiere sin `jev_doc_type`.
        # El conector puede declarar la semántica real de su published_at
        # (p.ej. GDELT seendate = primera detección, no publicación). Sin
        # published_at la fecha es la de ingesta y NUNCA se promociona a una
        # fecha de fuente o de primera detección.
        date_source = "ingested_at_fallback"
        if published_at:
            date_source = date_source_label or "source"
        news_metadata: dict = {"date_source": date_source}
        # Un texto de enlace del visor («archivo PDF, (se abre en una nueva
        # ventana)») no es un titular: se descarta aquí para que ni el title
        # ni metadata.source_headline (alertas, feed, traducción) lo usen.
        if is_generic_headline(source_headline):
            source_headline = None
        # Titular original de la fuente (antes del prefijo de ticker F175),
        # guardado en la creación para que las alertas muestren el titular real.
        if source_headline:
            news_metadata["source_headline"] = source_headline
        # Procedencia del display: False = el título es texto generado por
        # GerarAI (p.ej. «8-K presentado ante la SEC»), no verbatim de la
        # fuente. La UI lo usa para no repetir el ticker (ya en su columna)
        # al pintar el título.
        if not headline_from_source:
            news_metadata["headline_from_source"] = False
        # Procedencia del conector en la MISMA transacción de creación: si se
        # etiqueta después (segundo commit), una caída entre ambos deja
        # noticias nuevas sin connector y la reingesta las trata como previas.
        if connector:
            news_metadata["connector"] = connector
        # Carril editorial (p.ej. macro) y tema en la MISMA transacción de
        # creación, igual que la procedencia del conector.
        if news_lane:
            news_metadata["news_lane"] = news_lane
        if macro_theme:
            news_metadata["macro_theme"] = macro_theme
        # nosemgrep: gerarai-broad-except-pass -- paso opcional (Jev / relevancia); nunca bloquea la ingesta
        try:
            if _llm_budget_exceeded(llm_deadline):
                raise _LLMBudgetSkipped
            from app.services.jev_triage_service import (
                classify_doc_type_sync,
                jev_metadata,
            )

            doc_type = jev_metadata(classify_doc_type_sync(text))
            if doc_type is not None:
                news_metadata["jev_doc_type"] = doc_type
        except Exception:  # noqa: BLE001 — Jev nunca rompe la ingesta
            pass
        # Clasificación para priorizar la vista, no modifica el análisis ni
        # descarta noticias: el universo completo sigue disponible.
        # nosemgrep: gerarai-broad-except-pass -- paso opcional (Jev / relevancia); nunca bloquea la ingesta
        try:
            from app.models import Position, WatchItem
            from app.services.jev_gates import (
                THESIS_CRITERIA,
                UNIVERSE_RELEVANCE_CRITERIA,
                mark_only,
            )

            tracked = bool(
                company
                and (
                    db.scalar(
                        select(Position.id)
                        .where(
                            Position.company_id == company.id,
                            *tenant_filters(db, Position),
                        )
                        .limit(1)
                    )
                    or db.scalar(
                        select(WatchItem.id)
                        .where(
                            WatchItem.symbol == company.ticker,
                            *tenant_filters(db, WatchItem),
                        )
                        .limit(1)
                    )
                )
            )
            if source.lower() == "gdelt" and company:
                mark = mark_only(
                    "universe_relevance",
                    f"TRACKED_BY_ACCOUNT: {tracked}\nTICKER: {company.ticker}\nREPORT: {text}",
                    "Classify the relevance of this report for the provided tracking context; do not verify facts.",
                    UNIVERSE_RELEVANCE_CRITERIA,
                )
                news_metadata["tracked_by_account"] = tracked
                if mark:
                    # La pertenencia a cartera/lista es determinista: Jev
                    # nunca puede convertir un emisor no seguido en posición.
                    if not tracked and mark["label"] == "tracked":
                        mark["label"] = "universe"
                    news_metadata["jev_universe_relevance"] = mark
            if requires_update and company:
                mark = mark_only(
                    "thesis_change",
                    text,
                    "Mark whether the change looks substantive; never decide whether to regenerate a thesis.",
                    THESIS_CRITERIA,
                )
                if mark:
                    news_metadata["jev_thesis_priority"] = mark
        except Exception:  # noqa: BLE001 — jamás bloquear una ingesta
            pass
        # Evaluacion completa persistida en la MISMA transaccion (F314):
        # GET /api/news sirve solo lo persistido en ingesta; recomputar por
        # peticion costaba una evaluacion por noticia y podia divergir de lo
        # persistido (mezcla de campos persistidos y recalculados).
        news_metadata["assessment"] = {
            "source_tier": assessment.source_tier,
            "source_trust_score": assessment.source_trust_score,
            "portfolio_weight": assessment.portfolio_weight,
            "materiality_reasons": materiality_reasons,
            "source_policy": assessment.source_policy,
            "model_route": assessment.model_route,
        }
        news = NewsEvent(
            company_id=company.id if company else None,
            # La fecha del evento es la de publicacion de la fuente (filing,
            # noticia), no la de ingesta: con la de ingesta, una tanda de
            # filings de 2025 aparecia como "100 eventos de hoy" y las
            # urgencias por recencia se disparaban sobre historia antigua.
            date=published_at or datetime.now(UTC),
            # Titular: el del medio cuando la fuente lo trae (RSS con
            # headline_from_source). Antes se guardaba siempre el prefijo del
            # resumen cortado a 180 (clip de palabra pero a media frase:
            # «…rivals scrambling, and one»); el titular íntegro ya estaba en
            # metadata.source_headline y solo el feed lo usaba. Sin titular de
            # fuente, se mantiene el prefijo cortado en límite de palabra (un
            # corte a media palabra dejaba fragmentos «…del Ber»).
            title=(source_headline or "").strip() or clip_words(summary, 180, ellipsis=""),
            source=source,
            url=url,
            summary=summary,
            event_type=assessment.event_type,
            materiality_score=materiality_score,
            impact_direction=assessment.impact_direction,
            affected_thesis=requires_update,
            affected_assumptions=assessment.affected_assumptions,
            requires_update=requires_update,
            processed_at=datetime.now(UTC),
            metadata_=news_metadata,
        )
        db.add(news)
        db.flush()
        latest_thesis = None
        if company:
            latest_thesis = db.scalar(
                select(ThesisVersion)
                .where(ThesisVersion.company_id == company.id)
                .order_by(desc(ThesisVersion.version))
            )
        if requires_update and company:
            change_type = "news_material_update"
            if materiality_score >= 9 and assessment.impact_direction == "negative":
                change_type = "news_potential_invalidation"
            elif materiality_score >= 9 and assessment.impact_direction == "positive":
                change_type = "news_material_positive"
            change = ThesisChange(
                company_id=company.id,
                from_version_id=latest_thesis.id if latest_thesis else None,
                to_version_id=latest_thesis.id if latest_thesis else None,
                change_type=change_type,
                impact_direction=assessment.impact_direction,
                materiality_score=materiality_score,
                # La traza de "sin relacion" del motor semantico no es
                # contenido del cambio: si se persiste en el summary, el feed
                # «Qué ha cambiado» descarta la tarjeta aunque sea una
                # invalidacion material (filtro de memory.py).
                summary=_change_summary(
                    summary,
                    semantic_impact.summary
                    if semantic_impact
                    and (
                        semantic_impact.affected_claim_ids
                        or getattr(semantic_impact, "affected_node_ids", [])
                    )
                    else "",
                ),
                affected_claim_ids=(semantic_impact.affected_claim_ids if semantic_impact else []),
                affected_metrics=assessment.affected_assumptions,
                requires_review=True,
            )
            db.add(change)
            db.flush()
            self.reviews.create_from_news(db, news, change)
        db.add(
            ExternalClaim(
                company_id=company.id if company else None,
                source_id=None,
                claim=summary,
                claim_type="manual_news_claim",
                confidence=classify_source(source, url).trust_score,
                used_in_model=False,
            )
        )
        if company and not jev_light:
            self.claim_intelligence.scan_text(
                db,
                company=company,
                text=text,
                source_type=source,
                source_url=url,
                source_reference={"type": "news_event", "id": news.id},
                auto_apply=True,
            )
        else:
            # Sin empresa (carriles macro/gobierno) o via ligera Jev
            # (duplicado/ruido: sin ThesisChange ni claim scan): el commit de
            # scan_text no corre en ninguna de las dos ramas. Sin este commit
            # el evento quedaba flush pero NUNCA persistido cuando el llamador
            # no commiteaba (los workers de ingesta cierran la sesion sin
            # commit): la noticia se perdia en silencio y, al no existir en el
            # tracker, cada barrido siguiente volvia a ingerirla y a pagar su
            # gate Jev/LLM otra vez en vez de detectarla como duplicada.
            db.commit()

        action = (
            "Actualizar tesis con aprobacion humana y filing/call si confirma el cambio."
            if requires_update
            else "Guardar en tracker; no tocar DCF hasta evidencia primaria."
        )
        return ManualNewsResponse(
            ticker=company.ticker if company else None,
            summary=summary,
            event_type=assessment.event_type,
            materiality_score=materiality_score,
            impact_direction=assessment.impact_direction,
            affected_thesis=requires_update,
            affected_assumptions=assessment.affected_assumptions,
            requires_update=requires_update,
            action=action,
            source_policy=assessment.source_policy,
            source_tier=assessment.source_tier,
            source_trust_score=assessment.source_trust_score,
            portfolio_weight=assessment.portfolio_weight,
            materiality_reasons=materiality_reasons,
            model_route=assessment.model_route,
            affected_claim_ids=(semantic_impact.affected_claim_ids if semantic_impact else []),
            affected_node_ids=(semantic_impact.affected_node_ids if semantic_impact else []),
            semantic_impact=(semantic_impact.trace if semantic_impact else {}),
        )

    def analyze_manual_news(self, db: Session, text: str, source: str, url: str | None) -> ManualNewsResponse:
        return self._analyze_news(db, text, source, url)

    def ingest_news_items(
        self,
        db: Session,
        items: list[NewsFeedItem],
        default_source: str = "feed",
        connector: str | None = None,
        date_source_label: str | None = None,
        news_lane: str | None = None,
        macro_theme: str | None = None,
        detect_company: bool = True,
        llm_deadline: float | None = None,
    ) -> NewsIngestResponse:
        created_events: list[ManualNewsResponse] = []
        skipped_duplicates = 0

        for item in items:
            # Captacion de demandantes de despachos: no es un hecho de la empresa.
            if is_law_firm_solicitation(item.title, item.text):
                continue
            # Fila sin contenido: titular y cuerpo son solo el enlace del visor.
            if is_viewer_link_only(item.title, item.text):
                continue
            # F175: el ticker solo prefija el texto si el título no lo trae ya;
            # si no, el titular guardado salía «COST COST 8-K».
            # Cuerpo sin el titular repetido ni la firma de la fuente: feeds
            # (Simply Wall Street, MarketBeat) repiten el titular al inicio de
            # la descripción y la cierran con el nombre del medio; sin limpiar,
            # el titular guardado salía duplicado («Meta (META) ... Glasses
            # Meta (META) ... Glasses Simply Wall Street»).
            body = (item.text or "").strip()
            headline_txt = (item.title or "").strip()
            if headline_txt and body.casefold().startswith(headline_txt.casefold()):
                body = body[len(headline_txt):].lstrip(" \t\r\n:–—-|·")
            source_name = (item.source or "").strip()
            if source_name and body.casefold().endswith(source_name.casefold()):
                body = body[: -len(source_name)].rstrip(" \t\r\n:–—-|·")
            parts = [item.title, body]
            # Límite de palabra: «COSTCO Wholesale...» no empieza por el
            # ticker «COST» a efectos de prefijo.
            if item.ticker and not re.match(
                rf"^\s*{re.escape(item.ticker)}\b", item.title or "", flags=re.IGNORECASE
            ):
                parts.insert(0, item.ticker)
            text = " ".join(part for part in parts if part)
            company = self._company_for_item(db, text, item.ticker) if detect_company else None
            # Noticia de un competidor etiquetada con el ticker del feed (RKLB
            # bajo ASTS): sin cita de la empresa no se vincula a ella.
            if (
                company is not None
                and item.ticker
                and is_competitor_only(
                    company, f"{item.title or ''} {item.text or ''}", _ticker_evidence_level
                )
            ):
                continue
            if self._is_duplicate(
                db, company, text, item.url,
                title_is_identity=item.headline_from_source or not item.url,
                headline=item.title if item.headline_from_source else None,
            ):
                skipped_duplicates += 1
                continue
            created_events.append(
                self._analyze_news(
                    db=db,
                    text=text,
                    source=item.source or default_source,
                    url=item.url,
                    ticker=item.ticker,
                    published_at=item.published_at,
                    connector=connector,
                    date_source_label=date_source_label,
                    source_headline=(
                        item.title[:500] if item.title and item.headline_from_source else None
                    ),
                    headline_from_source=item.headline_from_source,
                    news_lane=news_lane,
                    llm_deadline=llm_deadline,
                    macro_theme=macro_theme,
                    detect_company=detect_company,
                )
            )

        return NewsIngestResponse(
            status="ingested",
            received=len(items),
            created=len(created_events),
            skipped_duplicates=skipped_duplicates,
            requires_update=sum(1 for event in created_events if event.requires_update),
            events=created_events,
        )
