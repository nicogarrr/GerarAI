"""Marco de foso competitivo: reglas de puntuacion derivadas de evidencia.

Este modulo define COMO se puntua una categoria de foso y, sobre todo, COMO se
declara que no se puede puntuar. Antes emitia unicamente una estructura vacia
con todos los scores a cero: un 0 sin evidencia no es un dato, es la ausencia
de dato vestida de veredicto, y quien leia "0/100" concluiria "no tiene foso".
Aqui cada score sale de evidencia que se puede citar claim por claim, y cuando
no la hay la categoria se declara no evaluable y se queda FUERA del agregado.

Dos capas:

* ``score_category`` es la regla pura de puntuacion: recibe referencias de
  evidencia ya resueltas (con su tier de fuente) y devuelve una puntuacion
  trazable o un estado explicito de no evaluabilidad. No toca la base de datos.
* ``build_result`` es el envoltorio del contrato publico: separa lo evaluado
  de lo no evaluado y decide el estado global y el agregado.

Decisiones de politica encapsuladas aqui para que el servicio y los tests no
puedan divergir:

* Solo los tiers con fuente identificada (``SOURCE_TIER_KEYS``) pueden sostener
  un score. Un rumor de prensa, un dato de proveedor, una semilla de arranque o
  una nota escrita por el usuario documentan el contexto pero no prueban una
  ventaja competitiva: se reportan y no se puntuan.
* La amplitud (cuanta evidencia, no solo cuan fuerte) modula el score. Dos
  notas de la misma fuente con tier 1 no son un foso demostrado.
* La evidencia en contra resta con el mismo peso que la a favor. Un 0 con
  evidencia en contra es un hallazgo ("la evidencia dice que no hay foso") y no
  una ausencia de dato: por eso es puntuable y la categoria no evaluable nunca
  se disfraza de 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MOAT_CATEGORIES = (
    "network_effects",
    "switching_costs",
    "scale_economies",
    "intangible_assets",
    "cost_advantage",
    "regulatory_barriers",
    "data_advantage",
    "distribution",
    "capital_intensity_barrier",
    "ecosystem_lock-in",
)

#: Version del metodo de puntuacion. Va en la traza de cada categoria para que
#: una fila persistida por una politica anterior sea distinguible de una
#: puntuacion vigente (y no semezcle en el mismo agregado).
SCORE_VERSION = "MOAT_EVIDENCE_V2"

#: Relaciones de evidencia que sostienen o refutan una ventaja competitiva.
SUPPORTING_RELATIONS = frozenset({"supports"})
CONTRADICTING_RELATIONS = frozenset({"contradicts", "supersedes"})

#: Tiers con fuente primaria nombrada (regulador, la propia empresa, llamada).
#: Un score de foso exige uno de estos.
SOURCE_TIER_KEYS = frozenset(
    {"tier_1_regulatory", "tier_2_company", "tier_3_transcript"}
)

#: Filtro de confianza del tier, en la misma escala que ``SOURCE_TIERS``.
#: Corta por confianza y no solo por nombre: si la jerarquia anade un tier
#: nuevo, este modulo no lo empieza a puntuar por inercia.
MIN_SOURCING_TRUST = 0.8

#: Estados por categoria. Los dos primeros son puntuaciones; los tres
#: siguientes son declaraciones de que NO hay puntuacion posible.
EVIDENCE_BACKED = "evidence_backed"
LIMITED_EVIDENCE = "limited_evidence"
INSUFFICIENT_EVIDENCE = "insufficient_evidence"
NO_SOURCED_EVIDENCE = "no_sourced_evidence"
ONLY_LOW_TIER_EVIDENCE = "only_low_tier_evidence"

#: Estados cuyo strength es un score trazable a evidencia.
EVALUATED_CATEGORY_STATUSES = frozenset({EVIDENCE_BACKED, LIMITED_EVIDENCE})

#: Estados no puntuables y su explicacion en castellano, reutilizable por la
#: UI y por la nota metodologica.
CATEGORY_STATUS_LABELS = {
    EVIDENCE_BACKED: "evaluada con evidencia de fuente primaria",
    LIMITED_EVIDENCE: "evaluada con evidencia escasa o de peso bajo",
    INSUFFICIENT_EVIDENCE: (
        "hay evidencia de fuente primaria pero su peso no alcanza para puntuar"
    ),
    NO_SOURCED_EVIDENCE: "ninguna afirmación viva con evidencia vinculada",
    ONLY_LOW_TIER_EVIDENCE: (
        "solo hay evidencia de fuentes sin fuente primaria identificada"
    ),
}

#: Estados globales del assessment.
STATUS_EVIDENCE_BACKED = "evidence_backed"
STATUS_PARTIAL = "partial_evidence"
STATUS_NOT_EVALUABLE = "not_evaluable"

#: Un score necesita al menos este numero de referencias y esta confianza
#: media para pasar de "limitada" a "evaluada con evidencia".
MIN_EVIDENCE_REFS = 2
MIN_CONFIDENCE = 0.35

#: Numero de referencias a partir del cual la amplitud deja de penalizar.
BREADTH_TARGET = 5

#: Techo de confianza: por mucha evidencia que haya, la certeza no es total.
MAX_CONFIDENCE = 0.95

#: Persistencia por debajo de la cual no se afirma duracion. El estado
#: "unproven" cubre tambien lo no evaluable: no hay persistencia demostrada,
#: pero tampoco hay una categoria puntuada que la contradiga.
PERSISTENCE_HIGH = ("high", 70, 0.6)
PERSISTENCE_MEDIUM = ("medium", 40, 0.4)

TREND_MARKERS = ("strengthening", "stable", "eroding")


def is_sourced_tier(source_tier: str | None, trust_score: float) -> bool:
    """Un score exige un tier conocido Y con confianza suficiente.

    La politica de la jerarquia vive en ``source_hierarchy_service``; aqui solo
    se decide que tier puede sostener una puntuacion de foso.
    """
    return (
        (source_tier or "") in SOURCE_TIER_KEYS
        and float(trust_score) >= MIN_SOURCING_TRUST
    )


@dataclass(frozen=True)
class EvidenceRef:
    """Una evidencia concreta, con el tier que permite auditarla.

    ``weight`` es la confianza de la evidencia multiplicada por la confianza
    del tier: una afirmacion respaldada por un regulador pesa mas que la misma
    afirmacion en una nota de prensa.
    """

    claim_id: int
    evidence_id: int
    relation: str
    source_tier: str | None
    trust_score: float
    confidence: float
    document_id: int | None = None
    document_chunk_id: int | None = None

    @property
    def weight(self) -> float:
        return round(float(self.trust_score) * float(self.confidence), 4)

    @property
    def is_sourced(self) -> bool:
        """Solo la evidencia de fuente primaria puede sostener un score."""
        return is_sourced_tier(self.source_tier, self.trust_score)

    @property
    def is_scoreable(self) -> bool:
        """Entra en el calculo: fuente primaria y relacion con significado."""
        return self.is_sourced and self.relation in (
            SUPPORTING_RELATIONS | CONTRADICTING_RELATIONS
        )

    def as_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "relation": self.relation,
            "source_tier": self.source_tier,
            "weight": self.weight,
            "document_id": self.document_id,
            "document_chunk_id": self.document_chunk_id,
            "confidence": round(float(self.confidence), 4),
            "counts_for_score": self.is_scoreable,
        }


@dataclass
class CategoryScore:
    """Resultado de una categoria: puntuacion trazable o no evaluable.

    ``strength`` es ``None`` cuando la categoria no es evaluable. No se
    rellena con 0: un 0 presentaria como dato lo que es una falta de evidencia.
    """

    type: str
    status: str
    strength: int | None
    trend: str
    persistence: str
    confidence: float
    supporting_claim_ids: list[int] = field(default_factory=list)
    contradicting_claim_ids: list[int] = field(default_factory=list)
    evidence_for: list[dict] = field(default_factory=list)
    evidence_against: list[dict] = field(default_factory=list)
    evidence_to_review: list[str] = field(default_factory=list)
    trace: dict = field(default_factory=dict)

    @property
    def evaluable(self) -> bool:
        return self.status in EVALUATED_CATEGORY_STATUSES

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "strength": self.strength,
            "trend": self.trend,
            "persistence": self.persistence,
            "confidence": round(float(self.confidence), 4),
            "status": self.status,
            "evaluable": self.evaluable,
            "status_label": CATEGORY_STATUS_LABELS.get(self.status, self.status),
            "supporting_claim_ids": list(self.supporting_claim_ids),
            "contradicting_claim_ids": list(self.contradicting_claim_ids),
            "evidence_for": list(self.evidence_for),
            "evidence_against": list(self.evidence_against),
            "evidence_to_review": list(self.evidence_to_review),
            "trace": dict(self.trace),
        }


def _persistence(strength: int | None, confidence: float) -> str:
    if strength is None:
        return "unproven"
    if strength >= PERSISTENCE_HIGH[1] and confidence >= PERSISTENCE_HIGH[2]:
        return PERSISTENCE_HIGH[0]
    if strength >= PERSISTENCE_MEDIUM[1] and confidence >= PERSISTENCE_MEDIUM[2]:
        return PERSISTENCE_MEDIUM[0]
    return "unproven"


def _trend(claim_trends: tuple[str, ...], status: str) -> str:
    """Tendencia declarada explicitamente por las claims; si no, la del estado."""
    marker = next(
        (item for item in claim_trends if item in TREND_MARKERS),
        None,
    )
    if marker is not None:
        return marker
    return "stable" if status == EVIDENCE_BACKED else "uncertain"


def score_category(
    moat_type: str,
    refs: list[EvidenceRef],
    *,
    claim_trends: tuple[str, ...] = (),
    keywords: tuple[str, ...] = (),
) -> CategoryScore:
    """Puntua una categoria desde su evidencia, o declara que no se puntua.

    Regla (MOAT_EVIDENCE_V2):

    1. Sin ninguna evidencia vinculada -> ``no_sourced_evidence``.
    2. Con evidencia pero ninguna de fuente primaria -> ``only_low_tier_evidence``:
       se reporta que existe y no se convierte en score.
    3. Con evidencia de fuente primaria pero de peso total nulo ->
       ``insufficient_evidence``.
    4. En otro caso se puntua: el saldo a favor menos en contra, escalado por
       la amplitud (referencias de fuente primaria / BREADTH_TARGET). La
       confianza es el peso medio por referencia, tambien escalado por amplitud.
       Dos o mas referencias con confianza >= MIN_CONFIDENCE elevan la categoria
       a ``evidence_backed``; por debajo queda ``limited_evidence``.
    """
    scoreable = [ref for ref in refs if ref.is_scoreable]
    low_tier = [ref for ref in refs if not ref.is_sourced]
    supporting_refs = [ref for ref in scoreable if ref.relation in SUPPORTING_RELATIONS]
    contradicting_refs = [
        ref for ref in scoreable if ref.relation in CONTRADICTING_RELATIONS
    ]
    supporting_claim_ids = sorted({ref.claim_id for ref in supporting_refs})
    contradicting_claim_ids = sorted({ref.claim_id for ref in contradicting_refs})

    support_score = round(sum(ref.weight for ref in supporting_refs), 4)
    against_score = round(sum(ref.weight for ref in contradicting_refs), 4)
    total = round(support_score + against_score, 4)
    breadth = min(1.0, len(scoreable) / BREADTH_TARGET)

    evidence_for = [ref.as_dict() for ref in supporting_refs]
    evidence_against = [ref.as_dict() for ref in contradicting_refs]
    trace: dict = {
        "method": SCORE_VERSION,
        "support_score": support_score,
        "against_score": against_score,
        "keywords": list(keywords),
        "evidence_refs": len(refs),
        "scored_evidence_refs": len(scoreable),
        "low_tier_evidence_refs": len(low_tier),
        "tier_policy": {
            "scoring_tiers": sorted(SOURCE_TIER_KEYS),
            "min_trust_score": MIN_SOURCING_TRUST,
        },
        "breadth_factor": round(breadth, 4),
        "supporting_claim_ids": supporting_claim_ids,
        "contradicting_claim_ids": contradicting_claim_ids,
    }
    # Las referencias que no pueden puntuar se conservan para poder auditar por
    # que la categoria no se evaluo, no solo que no se evaluo.
    trace["uncounted_evidence"] = [ref.as_dict() for ref in refs if not ref.is_scoreable]

    if not refs:
        status = NO_SOURCED_EVIDENCE
        strength: int | None = None
        confidence = 0.0
    elif not scoreable:
        status = ONLY_LOW_TIER_EVIDENCE if low_tier else INSUFFICIENT_EVIDENCE
        strength = None
        confidence = 0.0
    elif total <= 0:
        # Hay fuentes primarias pero su confianza declarada es cero: no hay
        # nada que convertir en puntuacion.
        status = INSUFFICIENT_EVIDENCE
        strength = None
        confidence = 0.0
    else:
        balance = max(0.0, support_score - against_score)
        strength = round(100 * (balance / total) * breadth)
        confidence = min(
            MAX_CONFIDENCE,
            (total / len(scoreable)) * breadth,
        )
        status = (
            EVIDENCE_BACKED
            if len(scoreable) >= MIN_EVIDENCE_REFS
            and confidence >= MIN_CONFIDENCE
            else LIMITED_EVIDENCE
        )

    trend = _trend(tuple(claim_trends), status)
    checklist = REVIEW_CHECKLIST.get(moat_type, {}).get("evidence_to_review", [])
    return CategoryScore(
        type=moat_type,
        status=status,
        strength=strength,
        trend=trend,
        persistence=_persistence(strength, confidence),
        confidence=confidence,
        supporting_claim_ids=supporting_claim_ids,
        contradicting_claim_ids=contradicting_claim_ids,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        # Lo que haria falta adjuntar para poder puntuar esta categoria. No es
        # evidencia encontrada: es la lista de fuentes que faltan.
        evidence_to_review=(
            list(checklist) if status != EVIDENCE_BACKED else []
        ),
        trace=trace,
    )


def overall_status(
    evaluated: list[CategoryScore], unevaluated: list[CategoryScore]
) -> str:
    """Estado global: evaluado, evaluado a medias, o no evaluable.

    ``partial_evidence`` no es un "casi evaluado": significa que hay
    puntuaciones pero ninguna alcanza el umbral de evidencia respaldada. Cuando
    no hay nada evaluable no se devuelve ningun agregado numerico, ni un 0.
    """
    if not evaluated:
        return STATUS_NOT_EVALUABLE
    if any(item.status == EVIDENCE_BACKED for item in evaluated):
        return STATUS_EVIDENCE_BACKED
    return STATUS_PARTIAL


def aggregate_strength(evaluated: list[CategoryScore]) -> int | None:
    """Media ponderada por confianza de las categorias evaluadas.

    Devuelve ``None`` si no hay nada evaluado. Las categorias no evaluables no
    entran: promediar "no lo se" con un dato baja el agregado sin motivo y
    presentaria cobertura como medida de ventaja.
    """
    scores = [item for item in evaluated if item.strength is not None]
    if not scores:
        return None
    weights = [max(float(item.confidence), 0.01) for item in scores]
    total_weight = sum(weights)
    if total_weight <= 0:  # pragma: no cover - los pesos nunca son todos cero
        return round(sum(float(item.strength) for item in scores) / len(scores))
    weighted = sum(
        float(item.strength) * weight for item, weight in zip(scores, weights)
    )
    return round(weighted / total_weight)


NOT_EVALUABLE_NOTE = (
    "Ninguna categoría de foso reúne evidencia con fuente primaria: no hay "
    "puntuación que mostrar. La ausencia de score no significa ausencia de "
    "foso; adjunta evidencia a las afirmaciones vivas para evaluarlas."
)


def build_result(
    *,
    ticker: str | None,
    company_type: str | None,
    evaluated: list[CategoryScore],
    unevaluated: list[CategoryScore],
    categories_total: int,
    methodology: str,
    note: str,
    trace: dict | None = None,
) -> dict:
    """Envoltorio comun de ``assess`` y ``read``.

    Contrato aditivo y explicito:

    * ``moats``: SOLO categorias con puntuacion trazable (strength numerico).
      Es lo que consume la vista de foso y lo que se formatea como ``/100``.
    * ``unevaluated_moats``: categorias consideradas y descartadas, con su
      estado y el motivo. ``strength`` es ``None`` porque no existe score.
    * ``aggregate_strength``: ``None`` si no hay nada evaluable. Nunca un 0.
    """
    status = overall_status(evaluated, unevaluated)
    aggregate = aggregate_strength(evaluated)
    result = {
        "ticker": ticker,
        "company_type": company_type,
        "status": status,
        "methodology": methodology,
        "note": NOT_EVALUABLE_NOTE if status == STATUS_NOT_EVALUABLE else note,
        "score_version": SCORE_VERSION,
        "categories_total": categories_total,
        "categories_evaluated": len(evaluated),
        "moats": [item.as_dict() for item in evaluated],
        "unevaluated_moats": [item.as_dict() for item in unevaluated],
        "aggregate_strength": aggregate,
        "aggregate": {
            "strength": aggregate,
            "comparable": aggregate is not None,
            "method": (
                "Media de las categorías evaluadas ponderada por su confianza; "
                "las categorías no evaluables se excluyen del cálculo."
            ),
            "evaluated_categories": [item.type for item in evaluated],
            "excluded_categories": [
                {"type": item.type, "status": item.status} for item in unevaluated
            ],
        },
        "trace": trace or {},
    }
    return result


@dataclass
class MoatEvidence:
    """Categoria sugerida para investigar, sin puntuacion.

    Antes este registro era un "andamiaje" con ``strength=0``. Ahora la
    ausencia de score es un ``None`` explicito y ``evidence_to_review`` dice
    que fuente buscaria, sin presentarlo como evidencia ya encontrada.
    """

    type: str
    strength: float | None = None
    trend: str = "unknown"
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)
    evidence_to_review: list[str] = field(default_factory=list)
    persistence_years: float | None = None
    confidence: float = 0.0
    status: str = NO_SOURCED_EVIDENCE

    @property
    def evaluable(self) -> bool:
        return self.strength is not None

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "strength": self.strength,
            "trend": self.trend,
            "evidence_for": self.evidence_for,
            "evidence_against": self.evidence_against,
            "evidence_to_review": self.evidence_to_review,
            "persistence_years": self.persistence_years,
            "confidence": self.confidence,
            "status": self.status,
            "evaluable": self.evaluable,
            "status_label": CATEGORY_STATUS_LABELS.get(self.status, self.status),
        }


#: Categorias que un tipo de empresa suele necesitar, con la evidencia que
#: haria falta para evaluarlas. NO son evidencia: son la lista de fuentes que
#: un analista debe adjuntar para que la categoria pueda puntuarse.
REVIEW_CHECKLIST: dict[str, dict[str, list[str]]] = {
    "switching_costs": {
        "evidence_to_review": [
            "Contratos y condiciones de renovación",
            "Churn medido y su desglose por cohort",
            "Migraciones de clientes a la competencia",
        ]
    },
    "data_advantage": {
        "evidence_to_review": [
            "Volumen, origen y exclusividad del dataset propio",
            "Mejora medible atribuible a los datos",
        ]
    },
    "regulatory_barriers": {
        "evidence_to_review": [
            "Licencias, espectro o autorizaciones vigentes",
            "Barreras de entrada verificadas por el regulador",
        ]
    },
    "capital_intensity_barrier": {
        "evidence_to_review": [
            "Plan de capex y quien lo financia",
            "Coste y plazo de replicar la infraestructura",
        ]
    },
    "intangible_assets": {
        "evidence_to_review": [
            "Marcas registradas, patentes y su titularidad",
            "Precios frente a equivalentes sin marca",
        ]
    },
    "cost_advantage": {
        "evidence_to_review": [
            "Coste unitario frente a competidores identificados",
            "Estructura de costes y su duración",
        ]
    },
    "network_effects": {
        "evidence_to_review": [
            "Liquidez por lado del mercado",
            "Métrica de doble efecto con historico",
        ]
    },
    "scale_economies": {
        "evidence_to_review": [
            "Coste unitario por volumen y su evolución",
            "Reparto de costes fijos con el crecimiento",
        ]
    },
    "distribution": {
        "evidence_to_review": [
            "Canales de distribución propios y su cuota",
            "Base instalada y recurrencia de la red comercial",
        ]
    },
    "ecosystem_lock-in": {
        "evidence_to_review": [
            "Integraciones y desarrolladores en la plataforma",
            "Coste de salida del ecosistema",
        ]
    },
}

_TAG_TO_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("software", ("switching_costs", "data_advantage")),
    ("platform", ("switching_costs", "data_advantage")),
    ("space", ("regulatory_barriers", "capital_intensity_barrier")),
    ("telecom", ("regulatory_barriers", "capital_intensity_barrier")),
    ("quality", ("intangible_assets",)),
    ("commodities", ("cost_advantage",)),
)


def suggested_categories(factor_tags: list[str]) -> list[str]:
    """Categorias a investigar segun etiquetas explicitas de la empresa.

    Es una lista de trabajo, no un analisis: no implica que la empresa tenga
    esa ventaja. Sin etiquetas conocidas se cae en las tres primeras del marco.
    """
    tags = {str(tag).strip().lower() for tag in (factor_tags or [])}
    suggested: list[str] = []
    for tag, categories in _TAG_TO_CATEGORIES:
        if tag in tags:
            suggested.extend(categories)
    if not suggested:
        return list(MOAT_CATEGORIES[:3])
    return list(dict.fromkeys(suggested))


def empty_moat_framework(
    company_type: str, factor_tags: list[str], special_risks: list[str]
) -> dict:
    """Marco de foso sin evaluacion, sin inventar categorias ni puntuaciones.

    Se usa cuando un motor de valoracion todavia no ha evaluado el foso. No
    devuelve ninguna puntuacion: devuelve las categorias que conviene
    investigar, su estado ``no_sourced_evidence`` y el contrato completo para
    que el consumidor lo lea igual que un assessment real.
    """
    # Sin evidencia ni claims: score_category resuelve el estado y adjunta la
    # lista de fuentes que cada categoria necesitaria. No hay atajos con 0.
    unevaluated = [
        score_category(category, [], keywords=())
        for category in suggested_categories(factor_tags)
    ]
    result = build_result(
        ticker=None,
        company_type=company_type,
        evaluated=[],
        unevaluated=unevaluated,
        categories_total=len(MOAT_CATEGORIES),
        methodology=(
            "Categorias sugeridas por tipo de empresa, sin evaluación: ninguna "
            "tiene evidencia vinculada con fuente primaria."
        ),
        note=(
            "Marco de foso sin evaluar. Las categorias marcadas son una lista "
            "de trabajo para el analista, no un diagnostico competitivo."
        ),
    )
    result["special_risks"] = list(special_risks or [])
    result["review_checklist"] = {
        item.type: list(item.evidence_to_review) for item in unevaluated
    }
    return result