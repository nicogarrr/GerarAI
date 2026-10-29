import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Position
from app.services.llm_router import route_model
from app.services.source_hierarchy_service import SourceTier, classify_source

MATERIAL_KEYWORDS = {
    # "shares" a secas y "atm" como subcadena marcaban dilucion en cualquier
    # titular bursatil ("Shares of AT&T fell", "platform"): solo cuentan frases
    # de emision/venta de acciones y el programa ATM como palabra completa.
    "dilution": [
        "dilution", "dilutive", "atm program", "atm offering", "at-the-market",
        "capital raise", "convertible", "share issuance", "issue new shares",
        "new shares", "share sale", "stock sale", "public offering",
        "equity offering", "stock offering", "share offering", "secondary offering",
        "direct offering", "follow-on offering", "common stock offering",
        "offering of common stock", "offering of shares", "offering of ordinary shares",
        "emision de acciones", "ampliacion de capital",
    ],
    "earnings": ["earnings", "guidance", "revenue", "eps", "fcf", "margin"],
    "regulatory": ["fda", "sec", "fcc", "ema", "regulatory", "investigation", "approval"],
    # "launch", "customer" y "award" como palabra suelta marcaban ruido como
    # evento de contrato (QA: «Reese Witherspoon launches lifestyle brand»):
    # solo cuentan frases con contexto de negocio.
    "contract": [
        "contract", "backlog", "partnership",
        "launches new", "product launch", "launch of", "new customers",
        "customer win", "contract award", "awarded",
    ],
    "capital_allocation": ["buyback", "repurchase", "dividend", "spin-off", "asset sale"],
}

ASSUMPTIONS_BY_EVENT_TYPE = {
    "dilution": ["share_count", "cash_runway", "dilution_risk"],
    "earnings": ["revenue_growth", "fcf_margin", "guidance"],
    "regulatory": ["approval_probability", "regulatory_risk"],
    "contract": ["revenue_timing", "backlog_conversion"],
    "capital_allocation": ["share_count", "capital_allocation"],
}

# Palabra completa inequívoca; lo ambiguo va por frase con contexto abajo.
# Verbos de mercado habituales: sin ellos el 85-100 % de los titulares salía
# «neutral» (medido en prod 28-oct-2026: BABA 60/60 neutral) y «upgrade» no
# era positivo mientras «downgrade» sí era negativo (asimetría). Las formas
# irregulares van explícitas: la flexión automática no cubre «won», «fell»,
# «sank», «slid» ni la doble consonante de «dropped»/«slipped».
POSITIVE_TERMS = [
    "approval", "buyback", "accelerate",
    "upgrade", "upgrading", "outperform", "overweight",
    "surge", "surging", "rally", "rallies", "rallied",
    "jump", "gain", "climb", "soar", "win", "won",
    "secure", "rise", "rose", "rising",
    "sube", "suben", "repunta", "aprueba", "aprueban",
]
NEGATIVE_TERMS = [
    "delay", "offering", "investigation", "default", "halt", "fraud",
    "overvalued", "downgrade", "sell-off", "selloff", "plunge", "plunging",
    "lawsuit",
    "tumble", "tumbling", "slump", "sink", "sank", "slide", "slid", "sliding",
    "slip", "slipped", "slipping", "fell", "falls", "falling",
    "drop", "dropped", "dropping", "warn", "downside", "scrutiny",
    "crackdown", "curb", "setback", "underperform", "underweight",
    "cae", "caen", "desploma", "multa",
]
CRITICAL_TERMS = ["bankruptcy", "fraud", "halt", "default"]

# Sentimiento por patrón verificado: «raise»/«record»/«beat»/«miss»/«cut» a
# palabra suelta invertían el signo con ruido (QA: «preorders fuertes» salía
# negativo; «praise» no debe contar como «raise»). Cada frase fija el objeto.
POSITIVE_PATTERNS = [
    "beats estimates", "beat estimates", "beats expectations",
    "beat expectations", "tops estimates", "tops expectations",
    "record revenue", "record sales", "record earnings", "record quarter",
    "record preorders", "record orders", "record demand", "record profit",
    "record results",
    "raises guidance", "raised guidance", "raises outlook", "raises forecast",
    "raises its dividend", "raises the dividend", "raises price target",
    "price target raised",
    "strong demand", "strong preorders", "preorders strong", "strong orders",
    "strong sales", "demand exceeds",
    "contract award",
]
NEGATIVE_PATTERNS = [
    "under pressure",
    "misses estimates", "missed estimates", "misses expectations",
    "missed expectations", "earnings miss", "revenue miss",
    "cuts guidance", "cut guidance", "guidance cut", "cuts forecast",
    "cuts outlook", "dividend cut", "price target cut",
    "priced for perfection", "valuation concern", "valuation risk",
    "stretched valuation",
    "weak demand", "weak preorders", "slowing demand", "demand slows",
]

def _fold(text: str) -> str:
    """Minusculas y sin tildes: "emisión" casa con "emision"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# Flexiones habituales (plural y verbo regular). Las siglas cortas (<= 3
# letras: sec, fda, atm, eps) no las admiten.
_INFLECTION = r"(?:s|es|ed|d|ing)?"


def _has_term(lower_text: str, term: str) -> bool:
    """Palabra completa con plural/flexion: "contracts" casa "contract",
    "repurchases" casa "repurchase", pero "sec" no casa dentro de "second"."""
    text, word = _fold(lower_text), _fold(term)
    suffix = "" if len(word) <= 3 else _INFLECTION
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}{suffix}(?![a-z0-9])", text) is not None


def _has_phrase(lower_text: str, phrase: str) -> bool:
    """Frase con contexto, borde de palabra en ambos extremos y sin flexion:
    "raises guidance" no casa "praises guidance" ni "raised his guidance"."""
    text, words = _fold(lower_text), _fold(phrase)
    return re.search(rf"(?<![a-z0-9]){re.escape(words)}(?![a-z0-9])", text) is not None



def _contested_selloff(text: str) -> bool:
    """Opinión explícita sobre una venta excesiva, no un hecho de la tesis."""
    folded = _fold(text)
    return re.search(
        r"\bsell[ -]?off\b[^.!?]{0,140}(?:"
        r"(?:may|might|could) have punished[^.!?]{0,100}beyond[^.!?]{0,50}fundamentals"
        r"|(?:is|was|seems|looks|may be|might be|could be) (?:the )?overdone)",
        folded,
    ) is not None


def _has_resumption(lower_text: str) -> bool:
    """El texto anuncia la reanudación de la cotización tras un halt."""
    return (
        _has_term(lower_text, "resumption")
        or _has_phrase(lower_text, "resumes trading")
        or _has_phrase(lower_text, "trading resumes")
        or _has_phrase(lower_text, "resume trading")
    )


_NAME_NOISE = {
    "inc", "corp", "corporation", "ltd", "limited", "plc", "holdings", "holding", "group",
    "company", "co", "the", "sa", "nv", "ag", "se", "class", "common", "stock", "adr", "ordinary",
}
# Fuentes que publican de todo (medios y agregadores): solo ahí la mención de la
# empresa decide si la noticia es sobre ella. Filings, IR, transcripciones y
# notas del usuario nunca se degradan.
_GENERIC_SOURCE_TIERS = {"tier_4_reputable_media", "tier_5_data_provider", "tier_unknown"}
UNRELATED_NEWS_MAX_MATERIALITY = 6
SOCIAL_NEWS_MAX_MATERIALITY = 2


def mentions_company(text: str, company: Company | None) -> bool:
    """El texto cita el ticker o una palabra distintiva del nombre de la empresa."""
    if company is None:
        return True
    folded = _fold(text or "")
    ticker = (company.ticker or "").strip().lower()
    if ticker and re.search(rf"(?<![a-z0-9]){re.escape(ticker)}(?![a-z0-9])", folded):
        return True
    for token in re.findall(r"[a-z0-9]+", _fold(company.name or "")):
        if len(token) >= 3 and token not in _NAME_NOISE:
            if re.search(rf"(?<![a-z0-9]){re.escape(token)}", folded):
                return True
    return not (ticker or (company.name or "").strip())


def is_unrelated_generic_news(text: str, company: Company | None, source: str, url: str | None) -> bool:
    """Titular de una fuente genérica que no menciona ni el ticker ni el nombre."""
    if company is None:
        return False
    if classify_source(source, url).key not in _GENERIC_SOURCE_TIERS:
        return False
    return not mentions_company(text, company)

# Un evento mas viejo que esta ventana nunca es "urgente" por recencia: un
# filing de 2025 ingerido hoy no puede abrir una cola de revision urgente.
RECENT_URGENCY_WINDOW = timedelta(days=7)


def apply_recency_policy(
    requires_update: bool, published_at: datetime | None, reasons: list[str]
) -> bool:
    """La urgencia solo aplica a eventos recientes (o sin fecha conocida).

    El score de materialidad se conserva intacto; lo que se suprime es la
    cola de revision urgente sobre historia antigua.
    """
    if not requires_update or published_at is None:
        return requires_update
    moment = published_at if published_at.tzinfo is not None else published_at.replace(tzinfo=UTC)
    age = datetime.now(UTC) - moment
    if age > RECENT_URGENCY_WINDOW:
        if not any(r.startswith("historical_event") for r in reasons):
            reasons.append(f"historical_event age={age.days}d => urgencia por recencia suprimida")
        return False
    return requires_update


@dataclass(frozen=True)
class MaterialityAssessment:
    event_type: str
    matched_event_types: list[str]
    materiality_score: int
    impact_direction: str
    affected_assumptions: list[str]
    requires_update: bool
    portfolio_weight: float
    source_tier: str
    source_trust_score: float
    reasons: list[str]
    model_route: str
    source_policy: str


class MaterialityService:
    def assess_news(
        self,
        db: Session,
        company: Company | None,
        text: str,
        source: str,
        url: str | None,
        *,
        use_jev: bool = True,
        published_at: datetime | None = None,
    ) -> MaterialityAssessment:
        lower_text = text.lower()
        matched_types = [
            event_type
            for event_type, keywords in MATERIAL_KEYWORDS.items()
            if any(_has_term(lower_text, keyword) for keyword in keywords)
        ]
        event_type = matched_types[0] if matched_types else "general_news"
        source_tier = classify_source(source, url)
        portfolio_weight = self.portfolio_weight(db, company) if company else 0.0

        materiality = 3
        reasons = ["base_score=3"]

        if matched_types:
            keyword_points = 2 * len(matched_types)
            materiality += keyword_points
            reasons.append(f"matched_event_types={','.join(matched_types)} +{keyword_points}")
        if "dilution" in matched_types:
            materiality += 2
            reasons.append("dilution +2")
        critical_hits = [word for word in CRITICAL_TERMS if _has_term(lower_text, word)]
        # Un aviso de reanudación («Trade Resumption», «trading resumes»)
        # siempre convive con la palabra «halt»: el crítico es el halt, no la
        # reanudación. Sin esta excepción la reanudación heredaba el 10/10
        # negativo del halt (QA prod 28-oct-2026: CIRO «Trade Resumption -
        # BN.PF.N» a 10/10 negativo con aviso de tesis).
        if _has_resumption(lower_text) and "halt" in critical_hits:
            critical_hits.remove("halt")
            reasons.append("trade_resumption: halt no critico")
        if critical_hits:
            materiality = max(materiality, 10)
            reasons.append("critical_term => 10")
        if company and ("pre_fcf" in company.factor_tags or "speculative" in company.factor_tags):
            materiality += 1
            reasons.append("speculative/pre_fcf company +1")
        source_adjustment = self._source_adjustment(source_tier)
        if source_adjustment:
            materiality += source_adjustment
            reasons.append(f"{source_tier.key} {source_adjustment:+d}")
        portfolio_adjustment = self._portfolio_adjustment(portfolio_weight)
        if portfolio_adjustment:
            materiality += portfolio_adjustment
            reasons.append(f"portfolio_weight={portfolio_weight:.4f} {portfolio_adjustment:+d}")

        impact_direction = self._impact_direction(lower_text)
        if impact_direction == "negative" and portfolio_weight >= 0.05:
            materiality += 1
            reasons.append("negative event on meaningful position +1")

        if use_jev:
            # nosemgrep: gerarai-broad-except-pass -- triage opcional de Jev; nunca rompe la ingesta
            try:
                from app.services.jev_triage_service import (
                    apply_to_materiality,
                    classify_urgency_sync,
                )

                triage = classify_urgency_sync(text)
                if triage is not None and not triage.error:
                    materiality = apply_to_materiality(materiality, reasons, triage)
            except Exception:  # noqa: BLE001 — Jev es best-effort, nunca rompe ingesta
                pass

        # Redes sociales (tier_8_social, p. ej. StockTwits): conversación sin
        # verificar. Nunca material: techo duro por debajo del umbral de
        # revisión, fuera de cualquier conteo de fuentes verificadas.
        if source_tier.key == "tier_8_social" and materiality > SOCIAL_NEWS_MAX_MATERIALITY:
            materiality = SOCIAL_NEWS_MAX_MATERIALITY
            reasons.append(f"fuente social sin verificar => max {SOCIAL_NEWS_MAX_MATERIALITY}")
        # Relevancia conservadora: nunca se descarta, solo se baja por debajo del
        # umbral de revisión (7) si la fuente es genérica y el texto no cita a la
        # empresa (QA: titulares de CoreWeave/HOOD con materialidad 10 en AAPL).
        if is_unrelated_generic_news(text, company, source, url) and materiality > UNRELATED_NEWS_MAX_MATERIALITY:
            materiality = UNRELATED_NEWS_MAX_MATERIALITY
            reasons.append(f"sin mención de la empresa en fuente genérica => max {UNRELATED_NEWS_MAX_MATERIALITY}")
        materiality = max(1, min(materiality, 10))
        requires_update = materiality >= 7 or (portfolio_weight >= 0.10 and materiality >= 6)
        requires_update = apply_recency_policy(requires_update, published_at, reasons)
        model_route = route_model(
            "deep_thesis" if requires_update else "news_triage",
            materiality_score=materiality,
            portfolio_weight=portfolio_weight,
        ).task

        return MaterialityAssessment(
            event_type=event_type,
            matched_event_types=matched_types,
            materiality_score=materiality,
            impact_direction=impact_direction,
            affected_assumptions=self._affected_assumptions(matched_types),
            requires_update=requires_update,
            portfolio_weight=portfolio_weight,
            source_tier=source_tier.key,
            source_trust_score=source_tier.trust_score,
            reasons=reasons,
            model_route=model_route,
            source_policy=source_tier.policy,
        )

    def portfolio_weight(self, db: Session, company: Company | None) -> float:
        if company is None:
            return 0.0
        positions = list(db.scalars(select(Position)).all())
        # El peso es un cociente de importes: solo vale si todos están en la
        # misma divisa. Con una cartera en una sola divisa sirve el importe
        # nativo; si se mezclan (USD, EUR, JPY…) se usa el valor en divisa base
        # de cada posición. Antes se sumaban 2.000.000 JPY con 100.000 EUR como
        # si fueran la misma unidad y el peso de la acción japonesa salía 95 %.
        single_currency = len({position.currency for position in positions}) <= 1
        values: list[tuple[Position, Decimal]] = []
        for position in positions:
            if single_currency:
                values.append((position, Decimal(position.market_value)))
            elif position.market_value_base is not None:
                values.append((position, Decimal(position.market_value_base)))
            elif position.currency == position.base_currency:
                values.append((position, Decimal(position.market_value)))
            # Sin valor en base no hay forma honesta de sumarla: queda fuera.
        total_equity = sum((value for _, value in values), Decimal("0"))
        if total_equity <= 0:
            return 0.0
        company_value = sum(
            (value for position, value in values if position.company_id == company.id),
            Decimal("0"),
        )
        return float(company_value / total_equity)

    def _affected_assumptions(self, matched_types: list[str]) -> list[str]:
        assumptions: list[str] = []
        for event_type in matched_types:
            assumptions.extend(ASSUMPTIONS_BY_EVENT_TYPE.get(event_type, []))
        return sorted(set(assumptions))

    def _impact_direction(self, lower_text: str) -> str:
        # Palabra completa para lo inequívoco y frase con contexto para lo
        # ambiguo: "cut" no casa en "execute", "raise" no casa en "praise" y
        # "preorders fuertes" es positivo aunque el titular traiga ruido.
        positive = any(_has_term(lower_text, word) for word in POSITIVE_TERMS) or any(
            _has_phrase(lower_text, phrase) for phrase in POSITIVE_PATTERNS
        )
        negative_terms = [
            word
            for word in NEGATIVE_TERMS
            # La reanudación de cotización no es el halt: «Trade Resumption»
            # vuelve a neutral en vez de heredar el negativo de «halt».
            if not (word == "halt" and _has_resumption(lower_text))
            # Una caída que el autor considera excesiva no afirma deterioro.
            # Solo se suprime la señal de precio selloff, nunca fraude, recorte
            # de guidance ni otros hechos negativos del mismo texto.
            and not (word in {"selloff", "sell-off"} and _contested_selloff(lower_text))
        ]
        negative = any(_has_term(lower_text, word) for word in negative_terms) or any(
            _has_phrase(lower_text, phrase) for phrase in NEGATIVE_PATTERNS
        )
        if positive and negative:
            return "mixed"
        if positive:
            return "positive"
        if negative:
            return "negative"
        return "neutral"

    def _source_adjustment(self, source_tier: SourceTier) -> int:
        if source_tier.key in {"tier_1_regulatory", "tier_2_company"}:
            return 1
        if source_tier.key in {"tier_6_bootstrap", "tier_unknown"}:
            return -1
        return 0

    def _portfolio_adjustment(self, portfolio_weight: float) -> int:
        if portfolio_weight >= 0.15:
            return 2
        if portfolio_weight >= 0.05:
            return 1
        return 0
