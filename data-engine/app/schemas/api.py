from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    name: str
    exchange: str
    currency: str
    sector: str
    industry: str
    cik: str | None
    ir_url: str | None
    domicile_country: str | None = None
    company_type: str
    valuation_model: str
    special_sources: list[str]
    special_risks: list[str]
    factor_tags: list[str]


class FinancialFactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    metric: str
    value: Decimal
    unit: str
    period: str
    fiscal_year: int | None
    fiscal_quarter: str | None
    source_id: int | None
    source_type: str
    is_reported: bool
    is_adjusted: bool
    confidence: Decimal
    created_at: datetime
    # Procedencia enlazable (documento de origen del dato). Nulos cuando el
    # hecho no tiene documento asociado: el frontend muestra la fuente como
    # texto plano, nunca un enlace inventado.
    source_url: str | None = None
    source_title: str | None = None
    source_published_at: datetime | None = None


class CompanyKPIOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    metric_key: str
    display_name: str
    aliases: list[str]
    canonical_unit: str
    period_type: str
    driver_type: str
    required: bool
    active: bool
    registry_version: str
    metadata: dict = Field(validation_alias="metadata_")


class KPIExtractionCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    company_kpi_id: int
    document_id: int
    document_chunk_id: int
    metric_key: str
    raw_label: str
    raw_value: str
    raw_unit: str
    normalized_value: Decimal | None
    canonical_unit: str
    period: str
    fiscal_year: int | None
    fiscal_quarter: str | None
    source_locator: dict
    reconciliation_status: str
    status: str
    confidence: Decimal
    extraction_model: str
    prompt_version: str
    approved_by: str | None
    approved_at: datetime | None
    canonical_fact_id: int | None
    trace: dict
    created_at: datetime


class KPIExtractionAction(BaseModel):
    action: Literal["approve", "reject"]
    actor: str = Field(default="user", min_length=1, max_length=160)


class FinancialRefreshResponse(BaseModel):
    status: str
    ticker: str
    provider: str
    source_document_id: int
    facts_imported: int
    # Hechos no escritos por tener ya hecho oficial (complemento Yahoo).
    facts_skipped_official: int = 0
    statements_imported: int
    latest_periods: dict[str, str | None]
    valuation_input_ready: bool


class CalculatedMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    company_id: int | None = None
    metric: str
    value: Decimal | None
    unit: str
    period: str
    fiscal_year: int | None = None
    fiscal_quarter: str | None = None
    status: str
    definition_version: str
    formula: str
    numerator: Decimal | None
    denominator: Decimal | None
    source_fact_ids: list[int]
    calculation_trace: dict
    confidence: Decimal


class CalculatedMetricsResponse(BaseModel):
    ticker: str
    status: str
    metrics: list[CalculatedMetricOut]


class SnapshotThesisSummaryOut(BaseModel):
    id: int
    version: int
    status: str
    executive_summary: str
    rating: str
    current_price: Decimal | None
    bear_value: Decimal | None
    base_value: Decimal | None
    bull_value: Decimal | None
    expected_value: Decimal | None
    margin_of_safety: Decimal | None
    archived_margin_of_safety: Decimal | None = None
    margin_of_safety_convention: str | None = None
    margin_of_safety_status: str = "unknown_convention"
    data_confidence_score: int
    source_coverage_score: int
    hypothesis: str | None = None
    catalysts: list | None = None
    invalidation_criteria: list | None = None
    invalidation_rules: list | None = None
    scenario_probabilities: dict | None = None
    created_at: datetime


class SnapshotValuationSummaryOut(BaseModel):
    model_id: int | None = None
    model_type: str
    version: int | None = None
    status: str
    current_price: Decimal | None = None
    bear_value: Decimal | None = None
    base_value: Decimal | None = None
    bull_value: Decimal | None = None
    expected_value: Decimal | None = None
    margin_of_safety: Decimal | None = None
    archived_margin_of_safety: Decimal | None = None
    margin_of_safety_convention: str | None = None
    margin_of_safety_status: str = "unknown_convention"
    updated_at: datetime | None = None


class SnapshotModelSummaryOut(BaseModel):
    id: int
    version: int
    engine_version: str
    algorithm_version: str
    framework_key: str
    horizon_years: int
    status: str
    publishable: bool
    input_fingerprint: str
    forecast_fingerprint: str
    market_snapshot_fingerprint: str
    valuation_snapshot_fingerprint: str
    code_commit_sha: str
    scenario_probabilities: dict[str, float | None]
    created_at: datetime


class SnapshotCountsOut(BaseModel):
    facts: int = 0
    calculated_metrics: int = 0
    documents: int = 0
    claims: int = 0
    thesis_versions: int = 0
    model_versions: int = 0
    open_reviews: int = 0
    open_alerts: int = 0


class ResearchHealthOut(BaseModel):
    score: int = Field(ge=0, le=100)
    status: Literal["empty", "incomplete", "review_required", "healthy"]
    missing: list[str] = Field(default_factory=list)
    review_required: bool = False


class SnapshotRecentChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int | None
    change_type: str
    impact_direction: str
    materiality_score: int
    summary: str
    affected_metrics: list[str]
    requires_review: bool
    created_at: datetime
    # Procedencia del evento origen (puente ResearchReview -> NewsEvent) y
    # fuentes absorbidas al agrupar la misma noticia en dos idiomas.
    fuente_url: str | None = None
    fuente_nombre: str | None = None
    tambien_en: list[dict] | None = None


class CompanySnapshotOut(BaseModel):
    """Small, read-only bootstrap contract for the Research workspace."""

    company: CompanyOut
    # Tenencia viva del tenant actual (positions con cantidad > 0). NO
    # confundir con companies.company_type: ese campo es una clase fijada
    # en el alta de la ficha y queda desfasada (F143: AAPL en cartera se
    # mostraba como "candidato de analisis" y SPCX, sin posicion del
    # tenant, como "portfolio holding").
    in_portfolio: bool = False
    latest_thesis: SnapshotThesisSummaryOut | None = None
    valuation_summary: SnapshotValuationSummaryOut
    model_summary: SnapshotModelSummaryOut | None = None
    research_health: ResearchHealthOut
    counts: SnapshotCountsOut
    recent_changes: list[SnapshotRecentChangeOut] = Field(default_factory=list)


class ThesisTickersOut(BaseModel):
    """Tickers con al menos una ThesisVersion persistida.

    Semantica identica a la del snapshot (``latest_thesis`` selecciona la
    version mas reciente sin filtro de estado): sirve para ordenar el
    indice de research sin descargar un snapshot por empresa.
    """

    tickers: list[str]


class CompanySnapshotsBatchOut(BaseModel):
    """Respuesta del snapshot por lote del indice de research.

    ``snapshots`` va keyed por ticker de la Company resuelta; ``missing``
    lista los tickers pedidos sin company en el registro (nunca se
    fabrican snapshots vacios para ellos).
    """

    snapshots: dict[str, CompanySnapshotOut]
    missing: list[str] = Field(default_factory=list)


class CompanySearchItemOut(BaseModel):
    """Identidad basica de una empresa del master para listados ligeros."""

    ticker: str
    name: str
    exchange: str
    currency: str


class CompanySearchOut(BaseModel):
    """Resultado de la busqueda local del master (sin proveedor externo)."""

    results: list[CompanySearchItemOut]


class CompanyBasicsBatchOut(BaseModel):
    """Basics por lote keyed por ticker PEDIDO (normalizado).

    ``missing`` lista los tickers pedidos sin company en el registro;
    nunca se fabrican basics vacios para ellos.
    """

    items: dict[str, CompanySearchItemOut]
    missing: list[str] = Field(default_factory=list)


class ThesisGenerateRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    force_new_version: bool = False
    # Id de peticion generado por el cliente en cada click: permite varias
    # generaciones reales para el mismo ticker (sin el, la clave de
    # idempotencia replaya el run exitoso anterior para siempre).
    request_id: str | None = Field(default=None, min_length=8, max_length=64)


VALUATION_WITHHELD_REASON = (
    "Valoración no disponible: faltan ingresos modelados con fuente. El modelo "
    "solo se podía calcular con un supuesto no verificado, así que no se "
    "publica ningún valor por acción."
)


def valuation_uses_inferred_inputs(valuation_basis: object) -> bool:
    if not isinstance(valuation_basis, dict):
        return False
    used = valuation_basis.get("inferred_inputs_used")
    return isinstance(used, list) and len(used) > 0


class NarrativeSectionOut(BaseModel):
    titulo: str
    parrafos: list[str]


class ThesisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    version: int
    status: str
    thesis_markdown: str
    executive_summary: str
    rating: str
    current_price: Decimal | None
    bear_value: Decimal | None
    base_value: Decimal | None
    bull_value: Decimal | None
    expected_value: Decimal | None
    margin_of_safety: Decimal | None
    archived_margin_of_safety: Decimal | None = None
    margin_of_safety_convention: str | None = None
    margin_of_safety_status: str = "unknown_convention"
    data_confidence_score: int
    source_coverage_score: int
    red_team_score: int
    valuation_risk_score: int
    input_fingerprint: str | None = None
    hypothesis: str | None = None
    catalysts: list | None = None
    invalidation_criteria: list | None = None
    invalidation_rules: list | None = None
    scenario_probabilities: dict | None = None
    # Inputs pendientes (human-in-the-loop): lo que falta para completar la
    # tesis. None = sin informacion (empresa sin modelo fundamental
    # persistido); lista vacia = sin pendientes conocidos.
    missing_inputs: list[str] | None = None
    # Procedencia de cada input del modelo: key + label
    # (dato/derivado/estimacion_llm/supuesto) + metodo + cita + confianza.
    inputs_provenance: list[dict] | None = None
    # Null en versiones anteriores a la capa narrativa o sin seleccion valida.
    narrative_sections: list[NarrativeSectionOut] | None = None
    # Base por accion de los escenarios al generar la tesis; None = sin evidencia.
    valuation_basis: dict | None = None
    stale: bool = False
    latest_data_at: datetime | None = None
    created_at: datetime
    # Motivo en español cuando la valoracion se retiene (input inferido).
    valuation_withheld_reason: str | None = None

    @model_validator(mode="after")
    def _separate_archived_margin(self) -> "ThesisOut":
        from app.valuation.margin_convention import margin_convention_known

        if self.valuation_withheld_reason and self.margin_of_safety_status == "withheld":
            return self
        if self.archived_margin_of_safety is None:
            self.archived_margin_of_safety = self.margin_of_safety
        self.margin_of_safety_convention = (self.valuation_basis or {}).get("margin_of_safety_convention")
        if self.archived_margin_of_safety is None:
            self.margin_of_safety_status = "missing"
        elif margin_convention_known(self.valuation_basis):
            self.margin_of_safety_status = "verified"
        else:
            self.margin_of_safety = None
            self.margin_of_safety_status = "unknown_convention"
        return self

    @model_validator(mode="after")
    def _withhold_inferred_valuation(self) -> "ThesisOut":
        """Un margen/ingreso INFERIDO nunca pasa por dato: sin cifras por accion."""
        if not valuation_uses_inferred_inputs(self.valuation_basis):
            return self
        self.bear_value = self.base_value = self.bull_value = None
        self.expected_value = None
        self.margin_of_safety = None
        self.archived_margin_of_safety = None
        self.margin_of_safety_convention = None
        self.margin_of_safety_status = "withheld"
        self.rating = "insufficient_data"
        self.valuation_withheld_reason = VALUATION_WITHHELD_REASON
        self.executive_summary = VALUATION_WITHHELD_REASON
        self.thesis_markdown = f"# Valoración no disponible\n\n{VALUATION_WITHHELD_REASON}\n"
        return self


class ClaimEvidenceCreate(BaseModel):
    document_id: int | None = None
    document_chunk_id: int | None = None
    source_url: str | None = None
    evidence_type: str = Field(
        default="supports",
        pattern="^(supports|contradicts|supersedes|context|uncertain)$",
    )
    summary: str = Field(min_length=3)
    quote: str | None = None
    confidence: Decimal = Decimal("0.70")
    source_tier: str | None = None


class ClaimEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_id: int
    document_id: int | None
    document_chunk_id: int | None
    source_url: str | None
    evidence_type: str
    summary: str
    quote: str | None
    confidence: Decimal
    source_tier: str
    created_at: datetime


class ClaimCreate(BaseModel):
    ticker: str | None = Field(default=None, max_length=20)
    company_id: int | None = None
    thesis_version_id: int | None = None
    statement: str = Field(min_length=5)
    claim_type: str = "thesis"
    status: str = "unverified"
    confidence: Decimal = Decimal("0.50")
    materiality_score: int = Field(default=5, ge=0, le=10)
    source_quality: str = "unknown"
    created_by: str = "user"


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int | None
    thesis_version_id: int | None
    statement: str
    claim_type: str
    status: str
    confidence: Decimal
    materiality_score: int
    source_quality: str
    created_by: str
    last_reviewed_at: datetime | None
    evidence: list[ClaimEvidenceOut] = Field(default_factory=list)
    created_at: datetime


class ThesisSectionCreate(BaseModel):
    section_key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    status: str = "draft"
    order_index: int = 0
    confidence: Decimal = Decimal("0.70")


class ThesisSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    thesis_version_id: int
    company_id: int
    section_key: str
    title: str
    body: str
    status: str
    order_index: int
    confidence: Decimal
    created_at: datetime
    updated_at: datetime


class ThesisChangeCreate(BaseModel):
    ticker: str | None = Field(default=None, max_length=20)
    company_id: int | None = None
    from_version_id: int | None = None
    to_version_id: int | None = None
    change_type: str = "manual"
    impact_direction: str = Field(default="neutral", pattern="^(positive|negative|neutral|mixed)$")
    materiality_score: int = Field(default=5, ge=0, le=10)
    summary: str = Field(min_length=5)
    affected_claim_ids: list[int] = Field(default_factory=list)
    affected_metrics: list[str] = Field(default_factory=list)
    requires_review: bool = False


class ThesisChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int | None
    from_version_id: int | None
    to_version_id: int | None
    change_type: str
    impact_direction: str
    materiality_score: int
    summary: str
    affected_claim_ids: list[int]
    affected_metrics: list[str]
    requires_review: bool
    created_at: datetime
    updated_at: datetime


class ResearchSessionCreate(BaseModel):
    ticker: str | None = Field(default=None, max_length=20)
    company_id: int | None = None
    title: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=3)
    status: str = "open"
    summary: str = ""
    source_ids: list[int] = Field(default_factory=list)
    claim_ids: list[int] = Field(default_factory=list)


class ResearchSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int | None
    title: str
    question: str
    status: str
    summary: str
    source_ids: list[int]
    claim_ids: list[int]
    memory_item_ids: list[int]
    created_at: datetime
    updated_at: datetime


class MemoryItemCreate(BaseModel):
    ticker: str | None = Field(default=None, max_length=20)
    company_id: int | None = None
    research_session_id: int | None = None
    scope: str = "portfolio"
    memory_type: str = "note"
    importance: int = Field(default=5, ge=0, le=10)
    content: str = Field(min_length=3)
    status: str = "active"
    source_type: str = "user"
    source_id: int | None = None


class MemoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int | None
    research_session_id: int | None
    scope: str
    memory_type: str
    importance: int
    content: str
    status: str
    source_type: str
    source_id: int | None
    created_at: datetime
    updated_at: datetime


class ManualNewsRequest(BaseModel):
    text: str = Field(min_length=10)
    url: str | None = None
    source: str = "manual"


class ManualNewsResponse(BaseModel):
    ticker: str | None
    summary: str
    event_type: str
    materiality_score: int
    impact_direction: str
    affected_thesis: bool
    affected_assumptions: list[str]
    requires_update: bool
    action: str
    source_policy: str
    source_tier: str = "tier_unknown"
    source_trust_score: float = 0
    portfolio_weight: float = 0
    materiality_reasons: list[str] = Field(default_factory=list)
    model_route: str = "news_triage"
    affected_claim_ids: list[int] = Field(default_factory=list)
    affected_node_ids: list[int] = Field(default_factory=list)
    semantic_impact: dict = Field(default_factory=dict)


class NewsFeedItem(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    text: str | None = None
    ticker: str | None = Field(default=None, max_length=20)
    url: str | None = None
    source: str = "feed"
    published_at: datetime | None = None
    # False = `title` es texto de display generado por GerarAI, no un titular
    # verbatim de la fuente: no se guarda como source_headline (procedencia).
    headline_from_source: bool = True


class NewsIngestRequest(BaseModel):
    items: list[NewsFeedItem] = Field(min_length=1, max_length=100)
    source: str = "feed"


class NewsIngestResponse(BaseModel):
    status: str
    received: int
    created: int
    skipped_duplicates: int
    requires_update: int
    events: list[ManualNewsResponse]


class ChatPageContext(BaseModel):
    """Contexto de página explícito ("Viendo X") enviado por el cliente.

    El ticker es TEXTO: la Company se resuelve en servidor dentro del tenant
    de la sesión (brain_service.resolve_page_context). El cliente nunca
    manda IDs de base de datos.
    """

    path: str = Field(min_length=1, max_length=240)
    label: str | None = Field(default=None, max_length=120)
    ticker: str | None = Field(default=None, max_length=20)


class ChatTurn(BaseModel):
    """Turno previo de la conversación del cerebro (solo texto, acotado)."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=1500)


class ChatRequest(BaseModel):
    question: str = Field(min_length=3)
    scope: str = "portfolio"
    ticker: str | None = None
    enable_debate: bool | None = None
    page: ChatPageContext | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


class SynthesisSection(BaseModel):
    key: Literal[
        "facts",
        "calculations",
        "user_hypotheses",
        "unverified_claims",
        "inferences",
        "contradictions",
        "insufficient_data",
        "conclusion",
    ]
    body: str
    citations: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    sections: list[SynthesisSection] = Field(default_factory=list)
    sources: list[dict]
    blocked: bool = False
    proposed_actions: list[str] = Field(default_factory=list)
    evidence_suggestions: list[dict] = Field(default_factory=list)
    prompt_version: str | None = None
    model: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    insufficient_data: bool = False
    llm_trace: dict = Field(default_factory=dict)
    # Eco del contexto de página resuelto en servidor (pastilla "Viendo X").
    context: dict | None = None


class ContradictionScanRequest(BaseModel):
    ticker: str
    document_id: int | None = None
    news_event_id: int | None = None
    create_reviews: bool = True


class ResearchReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int | None
    review_type: str
    status: str
    priority: str
    title: str
    summary: str
    thesis_change_id: int | None
    claim_id: int | None
    news_event_id: int | None
    assigned_to: str | None
    due_at: datetime | None
    resolved_at: datetime | None
    resolution_notes: str | None
    created_at: datetime
    updated_at: datetime


class ResearchReviewUpdate(BaseModel):
    status: Literal["open", "in_progress", "approved", "dismissed", "resolved"]
    resolution_notes: str | None = None


class ResearchAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int | None
    review_id: int | None
    ticker: str | None = None
    severity: str
    status: str
    alert_type: str
    title: str
    message: str
    fingerprint: str
    channels: list[str]
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    # F172: enlace al documento original (filing SEC, noticia) cuando la
    # alerta nace de un evento con fuente - antes solo habia /research/<ticker>
    # y el filing citado era inalcanzable desde la alerta.
    source_url: str | None = None
    company_name: str | None = None
    event_date: datetime | None = None
    event_date_source: str | None = None
    event_form: str | None = None
    # Titular de la noticia de origen (news_events.title), solo en alertas de noticias.
    event_headline: str | None = None
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    snoozed_until: datetime | None
    resolved_at: datetime | None
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str
    rule_type: str
    condition: dict
    target: dict
    severity: str
    channels: list[str]
    active: bool
    cooldown_seconds: int
    last_evaluated_at: datetime | None
    last_triggered_at: datetime | None
    trigger_count: int
    last_value: str | None
    last_result: dict
    metadata: dict = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_validator("condition", "target", "last_result", "metadata", mode="before")
    @classmethod
    def _coerce_legacy_dict(cls, value: object) -> dict:
        # Filas legacy pueden tener campos JSON con formas antiguas (string,
        # None) que PostgreSQL json/jsonb admite. Sin esta tolerancia, UNA sola
        # fila malformada hace fallar la validacion del listado entero y el
        # frontend muestra un error persistente para todas las alertas de la
        # cuenta. Coaccion segura: el frontend ya trata estos campos como
        # opcionales en la practica (p. ej. metadata.ticker ?? "").
        return value if isinstance(value, dict) else {}

    @field_validator("channels", mode="before")
    @classmethod
    def _coerce_legacy_channels(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            # Listas legacy pueden mezclar tipos ([1, {}, null]): conservar
            # solo strings; si no queda ninguno, canal por defecto.
            strings = [item for item in value if isinstance(item, str)]
            return strings or ["in_app"]
        return ["in_app"]


class ResearchAlertAction(BaseModel):
    action: Literal["acknowledge", "resolve", "snooze", "reopen"]
    actor: str = "user"
    snoozed_until: datetime | None = None


class ResearchAlertChannels(BaseModel):
    channels: list[Literal["in_app", "email", "push", "telegram"]] = Field(
        min_length=1
    )


class ThesisNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    thesis_version_id: int
    node_key: str
    node_type: str
    label: str
    description: str
    status: str
    confidence: Decimal
    materiality_score: int
    claim_ids: list[int]
    invalidation_conditions: list[str]


class ThesisEdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_node_id: int
    to_node_id: int
    edge_type: str
    strength: Decimal


class ThesisGraphOut(BaseModel):
    ticker: str
    thesis_version_id: int
    nodes: list[ThesisNodeOut]
    edges: list[ThesisEdgeOut]


class EarningsWorkflowRequest(BaseModel):
    fiscal_year: int
    fiscal_quarter: str = Field(default="FY", pattern="^(Q1|Q2|Q3|Q4|FY)$")
    document_ids: list[int] = Field(default_factory=list)
    force_new_thesis: bool = False


class EarningsRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    fiscal_year: int
    fiscal_quarter: str
    status: str
    document_ids: list[int]
    extracted_metrics: list[dict]
    guidance_changes: list[dict]
    comparisons: dict
    management_tone: dict
    promise_tracking: list[dict]
    risk_updates: list[dict]
    catalyst_updates: list[dict]
    claim_changes: list[dict]
    thesis_change_id: int | None
    error: str | None
    trace: dict
    created_at: datetime


class ValuationResponse(BaseModel):
    ticker: str
    model_type: str
    status: str = "ok"
    publishable: bool = True
    current_price: float | None = None
    bear_value: float | None = None
    base_value: float | None = None
    bull_value: float | None = None
    expected_value: float | None = None
    margin_of_safety: float | None = None
    missing_inputs: list[str] = []
    publication_blockers: list[str] = []
    # F394: escenarios por accion ordinaria; listed_share_values ya convertidos a
    # la base del precio cotizado (ADR) cuando hay adr_ratio.
    adr_ratio: float | None = None
    value_per_share_basis: str | None = None
    # Un escenario con valor por acción <= 0 es N/D (None) con su explicación
    # en scenario_notes; nunca una cifra negativa.
    listed_share_values: dict[str, float | None] | None = None
    scenario_notes: dict[str, str] = {}
    reverse_dcf: dict = {}
    sensitivity: dict = {}
    moat: dict = {}
    trace: dict = {}


# --- Ownership (SEC 13F, gestores revisados) ---------------------------------
# Modelan EXACTAMENTE lo que devuelven las ramas de ManagerHoldingIngestionService
# (persistida, snapshot edgartools y unavailable); un Literal de mas romperia la
# respuesta con un 500 de validacion y uno de menos esconderia el caso real.


class ProvenanceOut(BaseModel):
    """Bloque de proveniencia estandar (app/services/provenance.py)."""

    source: str
    source_kind: str
    source_url: str | None = None
    fetched_at: str
    coverage: str
    note: str | None = None


class OwnershipManagerOut(BaseModel):
    cik: str
    name: str


class OwnershipManagersOut(BaseModel):
    managers: list[OwnershipManagerOut]
    limitations: list[str]


class ManagerHoldingRowOut(BaseModel):
    """Una posicion 13F tal como se sirvio. La via snapshot (sin sync en vivo)
    deja en None lo que el snapshot no tiene (accession, filing_url, ...)."""

    accession_number: str | None = None
    is_amendment: bool = False
    name_of_issuer: str | None = None
    name_of_issuer_filed: str | None = None
    title_of_class: str | None = None
    cusip: str | None = None
    value_usd_thousands: float | None = None
    shares: float | None = None
    share_type: str | None = None
    put_call: str | None = None
    investment_discretion: str | None = None
    filing_url: str | None = None


class ManagerHoldingsOut(BaseModel):
    # "ok" solo con totales contrastados contra el propio 13F; "snapshot" =
    # servido del snapshot edgartools sin contrastar (nunca es "ok").
    status: Literal["ok", "mismatch", "unverified", "partial", "unavailable", "snapshot"]
    cik: str
    manager: str | None = None
    verification: str | None = None
    report_date: str | None = None
    coverage: str | None = None
    holdings: list[ManagerHoldingRowOut]
    errors: list | None = None
    limitations: list[str] | None = None
    transport: str | None = None
    snapshot_synced_at: str | None = None
    provenance: ProvenanceOut | None = None


class ManagerChangeRowOut(BaseModel):
    change: Literal["new", "closed", "increased", "decreased", "unchanged"]
    name_of_issuer: str
    title_of_class: str
    cusip: str
    put_call: str | None = None
    shares_latest: float | None = None
    shares_previous: float | None = None
    value_usd_thousands_latest: float | None = None
    value_usd_thousands_previous: float | None = None


class ComparedAccessionsOut(BaseModel):
    latest: str
    previous: str
    rule: str


class ManagerChangesOut(BaseModel):
    status: Literal["ok", "insufficient_history", "unavailable"]
    cik: str
    manager: str | None = None
    detail: str | None = None
    latest_report: str | None = None
    previous_report: str | None = None
    compared_accessions: ComparedAccessionsOut | None = None
    changes: list[ManagerChangeRowOut]
    limitations: list[str] | None = None
    provenance: ProvenanceOut | None = None


class InvestorSummaryOut(BaseModel):
    """Fila del listado de inversores (services/investors.list_investors)."""

    slug: str
    name: str
    firm: str
    kind: Literal["person", "firm", "company"]
    cik: str | None = None
    has_13f: bool
    has_public_profile: bool
    coverage: str | None = None
    verification: str | None = None
    # REVIEWED_MANAGERS.get(inv.cik or "") -> None (sin default) para inversores
    # sin CIK revisado: 8 registros del listado real. Nullable, nunca "".
    official_name: str | None = None
    report_date: str | None = None
    positions: int | None = None
    value_usd_thousands: float | None = None
    note: str | None = None


class InvestorsListOut(BaseModel):
    investors: list[InvestorSummaryOut]
    limitations: list[str]
    provenance: ProvenanceOut


class MostBoughtBuyerOut(BaseModel):
    slug: str
    name: str
    change: Literal["new", "increased"]
    report_date: str


class MostBoughtItemOut(BaseModel):
    name_of_issuer: str
    name_of_issuer_filed: str
    cusip: str
    buyers_count: int
    new_count: int
    sellers_count: int
    value_usd: float | None = None
    buyers: list[MostBoughtBuyerOut]


class MostBoughtOut(BaseModel):
    status: Literal["ok", "sin_datos"]
    managers_compared: int
    managers_without_history: int
    managers_partial: int
    report_dates: list[str]
    items: list[MostBoughtItemOut]
    limitations: list[str]
    provenance: ProvenanceOut


class OverlapHolderOut(BaseModel):
    slug: str
    name: str
    report_date: str
    filing_date: str | None = None
    filing_url: str | None = None
    coverage: str | None = None
    verification: str | None = None


class OverlapPositionOut(BaseModel):
    ticker: str
    name: str
    cusip: str | None = None
    identity_source: str | None = None
    holders: list[OverlapHolderOut]
    status: Literal["sin_identificador", "sin_coincidencias", "coincidencia"]


class PortfolioOverlapOut(BaseModel):
    # El payload "empty" (sin tenant/sin cartera) no trae comparison_complete
    # ni limitations: quedan opcionales para cubrir ambas ramas.
    status: Literal["ok", "sin_datos"]
    kind: Literal["derivado"]
    positions: list[OverlapPositionOut]
    not_owned: list[MostBoughtItemOut]
    unresolved_positions: int
    managers_with_data: int
    managers_without_data: int
    managers_partial: int
    report_dates: list[str]
    message: str | None = None
    comparison_complete: bool | None = None
    limitations: list[str] | None = None


class InvestorDatumOut(BaseModel):
    """Datum etiquetado de investor_portfolio.datum: N/D => todo null."""

    value: float | None = None
    label: Literal["OFICIAL", "INFERIDO", "SIN_DATOS"]
    as_of: str | None = None
    source_url: str | None = None


class PortfolioPositionOut(BaseModel):
    issuer: str
    ticker: str | None = None
    cusip: str | None = None
    title_of_class: str
    shares: InvestorDatumOut
    ownership_pct: InvestorDatumOut
    value_usd: InvestorDatumOut
    weight_pct: InvestorDatumOut
    source_form: str
    note: str | None = None


class PortfolioMovementOut(BaseModel):
    date: str | None = None
    filing_date: str | None = None
    issuer: str
    ticker: str | None = None
    action: str
    transaction_code: str | None = None
    shares: InvestorDatumOut
    price_usd: InvestorDatumOut
    shares_after: InvestorDatumOut
    source_form: str
    note: str | None = None


class InvestorPortfolioOut(BaseModel):
    """Respuesta de investor_portfolio(): ramas 13F y curated/Form4."""

    slug: str
    name: str
    firm: str
    has_13f: bool
    status: Literal["ok", "sin_datos"]
    labels: list[str]
    # LIMITATIONS (lista) en la rama 13F; texto largo en la rama sin 13F.
    limitations: list[str] | str
    positions: list[PortfolioPositionOut]
    movements: list[PortfolioMovementOut]
    as_of: str | None = None
    source_kinds: list[str]
    total_value_usd: InvestorDatumOut
    coverage: str | None = None
    note: str | None = None


class SavingsScenarioOut(BaseModel):
    """Escenario de project_savings: cifras ilustrativas, net_dividend siempre null."""

    years: int
    annual_total_return: float
    contributed: float
    terminal_value: float
    simulated_return: float
    terminal_value_today_money: float
    annual_inflation: float
    terminal_dividend_yield: float
    terminal_annual_gross_dividend: float
    terminal_monthly_gross_dividend_equivalent: float
    net_dividend: None = None


class SavingsProjectionOut(BaseModel):
    """Contrato de savings_contract: dict literal, todas las claves siempre presentes."""

    plan_exists: bool
    plan_id: int | None = None
    preview: bool
    monthly_contribution: float | None = None
    currency: str | None = None
    horizon_years: int | None = None
    initial_capital: int
    portfolio_included: bool
    basis: str
    assumptions: list[str]
    scenarios: list[SavingsScenarioOut]
    status: Literal["ok", "no_plan", "currency_missing"]
    source: str
    projection_url: str


class Schedule13DGDisplayOut(BaseModel):
    holder: str
    aggregate_shares: str
    percent_of_class: str
    snapshot_date: str


class Schedule13DGFilingOut(BaseModel):
    """Fila persistida de SC 13D/13G: lo no parseado queda null (N/D en display)."""

    accession_number: str
    form: str
    is_amendment: bool
    issuer_ticker: str | None = None
    issuer_name: str | None = None
    issuer_cik: str | None = None
    filer_cik: str | None = None
    holder_name: str | None = None
    aggregate_shares: float | None = None
    percent_of_class: float | None = None
    sole_voting_power: float | None = None
    shared_voting_power: float | None = None
    sole_dispositive_power: float | None = None
    shared_dispositive_power: float | None = None
    securities_class_title: str | None = None
    snapshot_date: str | None = None
    filing_date: str | None = None
    report_date: str | None = None
    signature_date: str | None = None
    status: str
    source: str
    source_url: str | None = None
    index_url: str | None = None
    parser_version: str
    display: Schedule13DGDisplayOut


class Schedule13DGResponseOut(BaseModel):
    ticker: str
    source: str
    count: int
    filings: list[Schedule13DGFilingOut]
    limitations: list[str]


class InvestorHoldingOut(BaseModel):
    """Fila de cartera del detalle: ORM con defaults "" (filing_url nunca null)."""

    name_of_issuer: str
    name_of_issuer_filed: str
    title_of_class: str
    cusip: str
    shares: float | None = None
    value_usd_thousands: float | None = None
    weight_pct: float | None = None
    put_call: str | None = None
    filing_url: str


class PublicFactOut(BaseModel):
    label: str
    value: str
    as_of: str
    source_url: str
    kind: Literal["oficial", "inferido", "prensa"]


class PublicProfileVehicleOut(BaseModel):
    name: str
    type: str
    regulator_id: str
    manager_company: str
    start_date: str
    source_url: str


class PublicProfileLetterOut(BaseModel):
    title: str
    date: str
    url: str


class PublicProfileMeetingOut(BaseModel):
    title: str
    year: str
    url: str


class PublicProfileLinkOut(BaseModel):
    label: str
    url: str


class PublicProfileOut(BaseModel):
    """Ficha pública curada (investor_profiles.PUBLIC_PROFILES) + provenance_note."""

    vehicle: PublicProfileVehicleOut
    facts: list[PublicFactOut]
    letters: list[PublicProfileLetterOut]
    meetings: list[PublicProfileMeetingOut]
    holdings: list | None = None
    holdings_note: str
    provenance_note: str
    links: list[PublicProfileLinkOut]


class InvestorVideoOut(BaseModel):
    video_id: str
    title: str
    published_at: str
    channel_name: str
    channel_url: str
    channel_kind: Literal["personal_confirmed", "firm_confirmed", "archive"]


class InvestorDetailOut(InvestorSummaryOut):
    """Ficha de inversor: _entry + holdings + provenance; la ruta anade
    changes solo si hay CIK (clave ausente si no) y videos siempre."""

    public_profile: PublicProfileOut | None = None
    holdings: list[InvestorHoldingOut]
    limitations: list[str]
    provenance: ProvenanceOut
    changes: ManagerChangesOut | None = None
    videos: list[InvestorVideoOut] = []


# --- GET /api/portfolio/intelligence ---------------------------------------
# Formas medidas contra PortfolioIntelligenceService.build (servicio real).
# La ruta usa response_model_exclude_unset=True: la rama sin posiciones de
# _ledger_contribution OMITE base_currency (no la emite null) y hay que
# conservar la omision en el wire.


class PortfolioTwrPeriodOut(BaseModel):
    start: date
    end: date
    sessions: int


class PortfolioReconstructionOut(BaseModel):
    method: str
    scope: str
    status: str
    days_valued: int
    days_excluded: int
    excluded_days: list[dict[str, Any]]
    first_date: date | None
    last_date: date | None
    twr: float | None
    quantity_check: list[dict[str, Any]]
    price_check: dict[str, Any]


class PortfolioPerformanceOut(BaseModel):
    twr: float | None
    xirr: float | None
    annualized_return: float | None
    trace: dict[str, Any]
    twr_method: Literal[
        "daily_portfolio_snapshots",
        "ledger_reconstruction_positions_only",
        "static_current_weight_estimate",
    ]
    twr_is_exact: bool
    twr_period: PortfolioTwrPeriodOut | None
    reconstruction: PortfolioReconstructionOut
    valuation_history: list[dict[str, Any]]


class PortfolioDrawdownPointOut(BaseModel):
    date: date
    drawdown: float


class PortfolioRiskOut(BaseModel):
    max_drawdown: float | None
    drawdown_series: list[PortfolioDrawdownPointOut]
    volatility: float | None
    sharpe: float | None
    sortino: float | None
    var_95: float | None
    cvar_95: float | None
    calmar: float | None
    beta: float | None
    beta_trace: dict[str, Any]
    correlations: dict[str, dict[str, float | None]]
    correlation_observations: dict[str, dict[str, int]]
    correlation_min_observations: int


class PortfolioConcentrationOut(BaseModel):
    top_1: float
    top_5: float
    herfindahl: float
    weights: dict[str, float]


class PortfolioExposuresOut(BaseModel):
    sectors: dict[str, float]
    countries: dict[str, float]
    currencies: dict[str, float]
    factors: dict[str, float]


class PortfolioAttributionPositionOut(BaseModel):
    ticker: str
    weight: float
    total_return: float | None
    period_start: str | None
    period_end: str | None
    period_days: int | None
    fx_known: bool
    dividends_known: bool
    partial_history: bool
    components: dict[str, float | None]


class PortfolioAttributionOut(BaseModel):
    basis: str
    period_start: str | None
    period_end: str | None
    portfolio_components: dict[str, float | None]
    incomplete_components: list[str]
    excluded_partial_histories: list[str]
    positions: list[PortfolioAttributionPositionOut]


class PortfolioLedgerPositionOut(BaseModel):
    ticker: str
    contribution_pnl: float | None
    contribution_share: float | None
    end_value: float | None
    start_value: float | None
    net_invested: float | None
    income: float | None
    reason: str | None


class PortfolioLedgerCoverageOut(BaseModel):
    positions: int
    with_contribution: int
    reasons: dict[str, int]


class PortfolioLedgerContributionOut(BaseModel):
    positions: list[PortfolioLedgerPositionOut]
    total_pnl: float | None
    coverage: PortfolioLedgerCoverageOut
    methodology: str
    # La rama sin posiciones del servicio OMITE la clave (no la emite null):
    # se conserva la omision con response_model_exclude_unset=True.
    base_currency: str | None = None


class PortfolioBenchmarkOut(BaseModel):
    symbol: str
    status: Literal["calculated", "missing_benchmark", "insufficient_overlap"]
    benchmark_twr: float | None
    benchmark_annualized: float | None
    portfolio_annualized: float | None
    alpha_annualized: float | None
    tracking_error: float | None
    information_ratio: float | None
    observations: int


class PortfolioCoverageOut(BaseModel):
    positions: int
    positions_with_price_history: int
    positions_with_full_horizon: int
    price_history_window_percent: float
    price_history_percent: float
    portfolio_snapshots: int
    partial_trading_day: bool
    spot_tail_positions: list[str]
    snapshot_returns: int
    snapshot_pricing_complete: int
    limitations: list[str]


class PortfolioIntelligenceOut(BaseModel):
    as_of: date
    base_currency: str
    missing_fx: list[dict[str, Any]]
    horizon_years: int
    performance: PortfolioPerformanceOut
    risk: PortfolioRiskOut
    concentration: PortfolioConcentrationOut
    exposures: PortfolioExposuresOut
    attribution: PortfolioAttributionOut
    ledger_contribution: PortfolioLedgerContributionOut
    benchmark: PortfolioBenchmarkOut
    coverage: PortfolioCoverageOut


# --- GET /api/portfolio/summary --------------------------------------------
# Formas medidas contra RiskService.dashboard (servicio real): la ruta
# devuelve siempre todas las claves (ramas None/[]; no omite ninguna).


class PortfolioSummaryAlertOut(BaseModel):
    severity: Literal["high", "medium"]
    ticker: str | None
    message: str
    metric_value: float
    threshold: float


class PortfolioValuationHoldOut(BaseModel):
    ticker: str
    reason: str
    effective_date: str | None


class PortfolioFxRateOut(BaseModel):
    scope: Literal["cash", "positions"]
    currency: str
    rate: float
    as_of: str


class PortfolioSummaryOut(BaseModel):
    total_value: float
    equity_value: float
    cash_assets_base: float
    margin_debt_base: float
    cash: dict[str, float]
    top_1_weight: float
    top_5_weight: float
    alerts: list[PortfolioSummaryAlertOut]
    status: Literal["ok", "incomplete_fx", "incomplete_valuation"]
    base_currency: str
    cash_native: dict[str, float]
    missing_fx: list[dict[str, Any]]
    data_as_of: str | None
    cash_as_of: str | None
    fx_rates: list[PortfolioFxRateOut]
    valuation_dates_differ: bool
    valuation_hold: list[PortfolioValuationHoldOut]
    provenance: ProvenanceOut


# --- GET /api/portfolio/positions ------------------------------------------
# Formas medidas contra la ruta (L773+) y sus helpers reales:
# _pnl_effects, _QUOTE_MISSING_PNL_KEYS, mask_cost_under_review,
# reconcile_ibkr_costs, _fiscal_info/_fiscal_info_batch, tracked_statuses.
# El payload de cada posicion emite siempre todas sus claves (ramas None),
# pero los objetos ANIDADOS omiten claves segun la rama: analysis solo
# lleva missing_inputs con thesis_status insufficient_data y
# cost_reconciliation not_comparable no lleva los importes de la rama
# ok/review_required. La ruta usa response_model_exclude_unset=True para
# preservar esas omisiones (los null explicitos se conservan).


class PortfolioAnalysisStateOut(BaseModel):
    """Estado de analisis tracked (tracked_statuses): clave por ticker."""

    status: str
    as_of: str
    thesis_status: str | None = None
    missing_inputs: list[str] | None = None


class PositionValuationHoldOut(BaseModel):
    reason: str
    effective_date: str | None
    since: str | None


class PortfolioCostReconciliationOut(BaseModel):
    """Resultado de reconcile_ibkr_costs para una posicion IBKR."""

    status: Literal["ok", "review_required", "not_comparable"]
    reason: str | None = None
    message: str | None = None
    snapshot_cost_native: float | None = None
    trade_cost_native: float | None = None
    difference_native: float | None = None
    tolerance_native: float | None = None
    currency: str | None = None
    cost_unit_verified: bool | None = None


class PortfolioPositionItemOut(BaseModel):
    ticker: str
    name: str
    sector: str
    analysis: PortfolioAnalysisStateOut | None
    quantity: float
    # mask_cost_under_review anula costes/plusvalias en revision: None.
    average_cost: float | None
    # Valoracion en suspenso: null con motivo, nunca un 0 como cotizacion.
    market_price: float | None
    market_value: float | None
    valuation_hold: PositionValuationHoldOut | None
    unrealized_pnl: float | None
    realized_pnl: float
    cost_basis: float | None
    as_of: str
    currency: str
    native_currency: str
    base_currency: str
    market_value_native: float | None
    market_value_base: float | None
    cost_basis_native: float | None
    cost_basis_base: float | None
    unrealized_pnl_native: float | None
    unrealized_pnl_base: float | None
    realized_pnl_base: float | None
    fx_rate: float | None
    pnl_price_effect_base: float | None
    pnl_fx_effect_base: float | None
    source: str
    first_buy_date: str | None
    holding_days: int | None
    fiscal_bucket: Literal["corto_plazo", "largo_plazo"] | None
    quote_missing: bool
    cost_reconciliation: PortfolioCostReconciliationOut | None


# --- GET /api/portfolio/transactions (+ /page) ------------------------------
# Forma medida contra _transaction_payload (servicio real): emite siempre
# todas las claves (notes/review_flag llegan como null). El listado se
# limita a buy/sell via _trade_filters.


class PortfolioTransactionOut(BaseModel):
    id: int
    ticker: str
    action: Literal["buy", "sell"]
    quantity: float
    price: float
    fees: float
    currency: str
    trade_date: str
    notes: str | None
    # Compra a precio 0 aceptada pero marcada para revision (regalo/spin-off).
    review_flag: str | None
    created_at: str
    updated_at: str


class PortfolioTransactionCreateOut(BaseModel):
    """Respuesta de POST /api/portfolio/transactions (201).

    Igual que PortfolioTransactionOut pero el POST acepta acciones de caja
    (dividend/interest/fee/cash_misc), no solo buy/sell.
    """

    id: int
    ticker: str
    action: Literal["buy", "sell", "dividend", "interest", "fee", "cash_misc"]
    quantity: float
    price: float
    fees: float
    currency: str
    trade_date: str
    notes: str | None
    review_flag: str | None
    created_at: str
    updated_at: str


class PortfolioTransactionBatchOut(BaseModel):
    """Respuesta de POST /api/portfolio/transactions/batch (201, atomico)."""

    created: int
    transaction_ids: list[int]
    transactions: list[PortfolioTransactionCreateOut]


class PortfolioTransactionPageOut(BaseModel):
    """Respuesta de GET /api/portfolio/transactions/page (limit/offset)."""

    items: list[PortfolioTransactionOut]
    total: int


# --- GET /api/portfolio/data-quality ----------------------------------------
# Forma medida contra portfolio_quality (servicio real): la rama sin cartera
# OMITE cost_review_positions y cost_unverified_positions; el resto de
# claves se emite siempre. La ruta usa response_model_exclude_unset=True
# para conservar esa omision.


class PortfolioTwrChainOut(BaseModel):
    status: Literal["no_snapshots", "broken", "linked"]
    unlinked_snapshots: int
    first_unlinked_date: str | None


class PortfolioDataQualityOut(BaseModel):
    status: Literal["ok", "incomplete", "no_portfolio"]
    positions: int
    missing_cost_positions: int
    # Solo presentes con cartera (la rama no_portfolio las omite).
    cost_review_positions: int | None = None
    cost_unverified_positions: int | None = None
    position_dates: list[str]
    cash_dates: list[str]
    cash_native: dict[str, float]
    position_sources: list[str]
    cash_sources: list[str]
    snapshots: int
    complete_snapshots: int
    return_observations: int
    latest_snapshot_date: str | None
    latest_pricing_coverage: float | None
    twr_chain: PortfolioTwrChainOut
    reasons: list[str]
# --- GET/PUT /api/portfolio/configuration ------------------------------------
# Formas medidas contra las rutas (servicio real): GET emite siempre todas
# las claves (id/source/latest_rate_date llegan como null); PUT devuelve un
# payload distinto y mas corto (sin tax_currency ni fx_source).


class PortfolioFxSourceOut(BaseModel):
    source: str | None
    latest_rate_date: str | None
    base_currency: str


class PortfolioConfigurationOut(BaseModel):
    id: int | None
    name: str
    base_currency: str
    is_default: bool
    # IRPF y Modelo 720 se declaran en euros al tipo BCE.
    tax_currency: str
    fx_source: PortfolioFxSourceOut


class PortfolioConfigurationUpdateOut(BaseModel):
    id: int
    name: str
    base_currency: str
    is_default: bool
# --- GET /api/portfolio/fx-rates ---------------------------------------------
# Forma medida contra la ruta (servicio real): emite siempre todas las
# claves. Paginado con PaginatedResponse como /positions.


class FXRateOut(BaseModel):
    id: int
    base_currency: str
    quote_currency: str
    rate: float
    rate_date: str
    source: str


# --- POST /api/portfolio/import/commit ---------------------------------------
# Forma medida contra TransactionImportService.commit_import: exito -> las 5
# claves siempre; los errores salen como 400 (ValueError), no como wire.


class PortfolioImportCommitOut(BaseModel):
    success: bool
    message: str
    imported_count: int
    duplicates_skipped: int
    import_batch: str
# --- POST /api/portfolio/dividends/sync --------------------------------------
# Envelope medido contra DividendIngestionService.sync_portfolio (6 claves
# siempre presentes). Los items de results varian por rama, medido contra
# ProviderIngestionService.sync_company y el override de dividendos:
# - ok: ticker/status/source/inserted/existing/skipped/fetched_at
#   (+ split_readjustments_healed si hubo cura; + currency_unknown_rows y
#   reason, con status currency_unknown, si el proveedor no informo divisa)
# - unknown_company: ticker/status/inserted/existing
# - no_safe_symbol / unavailable: + error
# Por eso todo lo demas es opcional y la ruta usa exclude_unset.


class DividendSyncResultOut(BaseModel):
    ticker: str
    status: Literal["ok", "unavailable", "unknown_company", "no_safe_symbol", "currency_unknown"]
    inserted: int
    existing: int
    error: str | None = None
    source: str | None = None
    skipped: dict[str, int] | None = None
    fetched_at: str | None = None
    split_readjustments_healed: int | None = None
    currency_unknown_rows: int | None = None
    reason: str | None = None


class PortfolioDividendSyncOut(BaseModel):
    companies: int
    synced: int
    unavailable: int
    currency_unknown: int
    results: list[DividendSyncResultOut]
    provenance: ProvenanceOut
# --- POST /api/portfolio/import/ibkr/csv -------------------------------------
# Forma medida contra IBKRImportService.import_ibkr_csv: exito -> las 8
# claves siempre (identity_warning es null si todas las filas traen id;
# CSV sin identificador -> aviso, medido en la rama has_rows_without_id).
# Errores -> IBKRImportError -> 400, no wire.


class PortfolioIbkrCsvImportOut(BaseModel):
    status: Literal["imported"]
    trades_imported: int
    duplicate_trades: int
    legacy_reimport_blocked: int
    identity_warning: str | None
    rows_skipped: int
    row_errors: list[str]
# --- POST /api/portfolio/import/ibkr/xml -------------------------------------
# Forma medida contra IBKRImportService.import_flex_xml (rama confirmada,
# return L1915): las 23 claves siempre. dry_run y reconcile destructivo
# nunca llegan al wire desde la ruta (solo pasa expected_account_id y
# max_statement_age_days). Errores -> IBKRImportError -> 400, no wire.


# --- POST /api/portfolio/import/ibkr -----------------------------------------
# Dos variantes medidas en la ruta: sin credenciales Flex devuelve
# {status: not_configured, message} y con credenciales delega en
# import_flex_xml (misma rama confirmada de 23 claves que /import/ibkr/xml).
# Un solo modelo con todo opcional + exclude_unset (el guard de drift no
# resuelve unions anyOf; precedente refresh-market); los tests fijan el
# conjunto exacto de claves de cada variante. Errores -> 400/403/409/503.


class PortfolioIbkrImportOut(BaseModel):
    status: Literal["imported", "not_configured"]
    message: str | None = None
    price_backfills_enqueued: int | None = None
    positions_imported: int | None = None
    valuation_hold_kept: list[str] | None = None
    cost_review_required: list[str] | None = None
    cash_imported: int | None = None
    trades_imported: int | None = None
    raw_rows_stored: int | None = None
    raw_rows_already_present: int | None = None
    raw_rows_pruned: int | None = None
    fx_conversions_imported: int | None = None
    fx_conversions_skipped: int | None = None
    trades_cancelled: int | None = None
    dividends_imported: int | None = None
    fees_imported: int | None = None
    cash_transactions_imported: int | None = None
    rows_skipped: int | None = None
    unattributed_cash_rows: int | None = None
    row_errors: list[str] | None = None
    positions_closed: list[str] | None = None
    cash_removed: list[str] | None = None
    reconcile_blocked: list[str] | None = None
    portfolio_snapshot_id: int | None = None


class PortfolioIbkrXmlImportOut(BaseModel):
    # Re-medido tras #3664: la rama "imported" emite 23 claves (status fijo
    # "imported"; dry_run no es alcanzable desde la ruta: default False y la
    # ruta no lo pasa). Sin estas 4, response_model las borraba del wire.
    status: Literal["imported"]
    trades_imported: int
    rows_skipped: int
    row_errors: list[str]
    price_backfills_enqueued: int
    positions_imported: int
    valuation_hold_kept: list[str]
    cost_review_required: list[str]
    cash_imported: int
    raw_rows_stored: int
    raw_rows_already_present: int
    raw_rows_pruned: int
    fx_conversions_imported: int
    fx_conversions_skipped: int
    trades_cancelled: int
    dividends_imported: int
    fees_imported: int
    cash_transactions_imported: int
    unattributed_cash_rows: int
    positions_closed: list[str]
    cash_removed: list[str]
    reconcile_blocked: list[str]
    portfolio_snapshot_id: int


# --- GET /api/watchlist/attention-thesis -------------------------------------
# Forma medida contra la ruta + home_attention_service.pending_thesis_changes:
# envelope fijo {items, truncated}; item de 5 claves siempre presentes.
# direction es String(40) en el modelo con escritores que usan
# neutral/negative/mixed (medido); no es un conjunto cerrado: str honesto.


class WatchlistAttentionThesisItemOut(BaseModel):
    id: int
    symbol: str
    summary: str
    direction: str
    createdAt: str


class WatchlistAttentionThesisOut(BaseModel):
    items: list[WatchlistAttentionThesisItemOut]
    truncated: bool


# --- GET /api/alerts/telegram-status -----------------------------------------
# Forma medida contra la ruta: cuatro booleanos siempre (solo presencia de
# config; ningun secreto sale por la API, ver docstring de la ruta).


class AlertsTelegramStatusOut(BaseModel):
    enabled: bool
    has_bot_token: bool
    has_chat_id: bool
    configured: bool


# --- GET /api/alerts/{alert_id}/analysis --------------------------------------
# Forma medida contra alert_analysis_service.read_analysis: envelope fijo
# {alert_id, versions}. Cada version tiene 7 claves siempre; la rama valida
# (cita verificada) anade second_order (null si no se ejecuto el paso LLM) y
# la rama invalida lo OMITE: response_model_exclude_unset + test de ausencia.
# second_order es un bloque de hipotesis (temas/candidatos LLM) sin contrato
# cerrado: se declara free-form dict, nunca se inventa su interior.


class AlertAnalysisSectionOut(BaseModel):
    key: str
    body: str
    citation_ids: list[str]


class AlertAnalysisCitationOut(BaseModel):
    id: str
    kind: str
    source: str
    url: str
    as_of: str
    excerpt: str


class AlertAnalysisVersionOut(BaseModel):
    id: int
    version: str
    status: str
    sections: list[AlertAnalysisSectionOut]
    citations: list[AlertAnalysisCitationOut]
    second_order: dict[str, Any] | None = None
    missing_data: list[str]
    writeback: bool


class AlertAnalysisReadOut(BaseModel):
    alert_id: int
    versions: list[AlertAnalysisVersionOut]


# --- GET /api/screeners/custom-metrics y /screens -------------------------------
# Formas medidas contra _metric_payload y _screen_payload (serializan la fila
# ORM tal cual). metadata es un dict libre del tenant y criteria la lista de
# criterios tal como se guardaron: free-form declarado, nunca inventado.


class ScreenerCustomMetricOut(BaseModel):
    id: int
    metric_key: str
    name: str
    formula: str
    unit: str
    description: str
    version: int
    active: bool
    metadata: dict[str, Any]
    created_at: datetime


class ScreenerCriterionOut(BaseModel):
    left: str
    operator: Literal[">", ">=", "<", "<=", "==", "!="]
    right: str


class ScreenerSavedScreenOut(BaseModel):
    id: int
    name: str
    description: str
    criteria: list[ScreenerCriterionOut]
    ranking_formula: str | None
    ranking_direction: str
    alerts_enabled: bool
    active: bool
    last_run_at: datetime | None
    created_at: datetime


# --- GET /api/portfolio/snapshots --------------------------------------------
# Forma medida contra _snapshot_payload (servicio real): emite siempre todas
# las claves; daily_return/cumulative_twr llegan como null (la primera foto
# es base sin retorno). Paginado PaginatedResponse como /positions.


class PortfolioSnapshotOut(BaseModel):
    id: int
    portfolio_id: int
    snapshot_date: date
    base_currency: str
    positions_value_base: float
    cash_value_base: float
    total_value_base: float
    net_external_flow_base: float
    daily_return: float | None
    cumulative_twr: float | None
    pricing_coverage: float
    source: str
    metadata: dict[str, Any]


# --- POST /api/portfolio/snapshots/capture -----------------------------------
# Forma medida contra la ruta (dict literal de 7 claves, todas siempre
# presentes): subconjunto del payload del historial, sin portfolio_id,
# base_currency, desglose de valor, net_external_flow_base ni source.
# daily_return/cumulative_twr son null en la primera foto de la serie
# (sin foto previa no hay retorno que enlazar).


class PortfolioSnapshotCaptureOut(BaseModel):
    id: int
    snapshot_date: date
    total_value_base: float
    pricing_coverage: float
    daily_return: float | None
    cumulative_twr: float | None
    metadata: dict[str, Any]
# --- GET /api/portfolio/dividends --------------------------------------------
# Formas medidas contra DividendIngestionService.portfolio_yields (servicio
# real): emite siempre todas las claves (los huecos llegan como null, nunca
# como 0 fabricado).


class DividendUncertainEventOut(BaseModel):
    ex_date: str
    amounts: list[str]


class DividendYieldPositionOut(BaseModel):
    ticker: str
    ttm_dividend_per_share: float | None
    uncertain_dividend_events: list[DividendUncertainEventOut]
    currency: str
    price: float | None
    dividend_yield: float | None
    records_12m: int
    matching_currency_records_12m: int
    skipped_currency_mismatch: int
    last_fetched_at: str | None


class DividendYieldCoverageOut(BaseModel):
    positions: int
    positions_with_dividend_data: int
    percent: float
    positions_missing_base_value: list[str]
    covered_value_fraction: float | None


class PortfolioDividendYieldsOut(BaseModel):
    as_of: str
    positions: list[DividendYieldPositionOut]
    portfolio_yield: float | None
    coverage: DividendYieldCoverageOut
    provenance: ProvenanceOut


# --- GET /api/portfolio/dividends/projection ---------------------------------
# Formas medidas contra DividendProjectionService.project (servicio real).
# fiscal_by_year: las ramas sin escenario completo (todo excluido o base no
# EUR) OMITEN effective_avg_rate y per_position; la ruta usa
# response_model_exclude_unset=True para conservar la omision.


class DividendProjectionMonthOut(BaseModel):
    month: str
    gross_base: float
    source_withheld_base: float
    gross_unverified_base: float
    gross_total_base: float
    covered_tickers: list[str]
    excluded_tickers: list[str]
    note: str | None


class DividendProjectionPositionFiscalOut(BaseModel):
    gross_base: float
    source_withheld_foreign_base: float
    retencion_a_cuenta_base: float
    double_tax_deduction_base: float


class DividendProjectionFiscalYearOut(BaseModel):
    gross_base: float | None
    irpf_scenario: float | None
    source_withheld_foreign: float | None
    retencion_a_cuenta_es: float | None
    double_tax_deduction: float | None
    cuota_pendiente_estimada: float | None
    net_scenario: float | None
    # Solo presentes en la rama con escenario completo (base EUR y datos).
    effective_avg_rate: float | None = None
    per_position: dict[str, DividendProjectionPositionFiscalOut] | None = None
    covered_tickers: list[str]
    excluded_tickers: list[str]
    note: str


class DividendProjectionPositionOut(BaseModel):
    ticker: str
    currency: str
    quantity: float
    frequency_last_year: int
    gross_native: float
    gross_base: float | None
    domicile_country: str | None
    withholding_basis: Literal["emisor_verificado", "domicilio_bd"] | None
    withholding_kind: (
        Literal["techo_convenio", "escenario_convenio", "sin_impuesto_origen_escenario"] | None
    )
    unverified_reason: str | None
    scenario_conditions: str | None
    source_withholding_rate: float | None
    source_withheld_base: float | None
    months: dict[str, float]


class DividendProjectionGrossSummaryOut(BaseModel):
    label: str
    gross_total_base: float
    gross_unverified_base: float
    net_irpf: str
    excluded_no_fx: list[str]
    excluded_no_dividends: list[str]
    excluded_uncertain_dividends: list[str]
    complete: bool


class DividendProjectionDeclaredFutureOut(BaseModel):
    ticker: str
    ex_date: str
    pay_date: str | None
    amount_per_share: float
    currency: str
    label: str
    source: str
    projection_as_of: str
    note: str


class DividendProjectionCoverageOut(BaseModel):
    with_data: int
    sin_datos: list[str]
    uncertain_dividends: list[str]
    fx_missing: list[str]
    unknown_source_withholding: list[str]
    unverified_reasons: dict[str, str]


class PortfolioDividendProjectionOut(BaseModel):
    as_of: str
    base_currency: str
    horizon_months: int
    label: str
    method: str
    fiscal_conditions: list[str]
    sources: dict[str, str]
    months: list[DividendProjectionMonthOut]
    fiscal_by_year: dict[str, DividendProjectionFiscalYearOut]
    positions: list[DividendProjectionPositionOut]
    gross_summary: DividendProjectionGrossSummaryOut
    declared_future: list[DividendProjectionDeclaredFutureOut]
    coverage: DividendProjectionCoverageOut


# --- GET /api/portfolio/tearsheet --------------------------------------------
# Formas medidas contra TearsheetService.build (servicio real). La rama
# no_portfolio publica metrics/qualification/exposure como null y trace SOLO
# con method: n_snapshots/n_returns se omiten -> response_model_exclude_unset
# en la ruta conserva la omision.


class TearsheetMetricsOut(BaseModel):
    status: Literal["ok", "insufficient_data"]
    n_observations: int
    cumulative_return: float | None
    sharpe: float | None
    sortino: float | None
    max_drawdown: float | None
    win_rate: float | None
    best_day: float | None
    worst_day: float | None
    periods_per_year: int


class TearsheetQualificationOut(BaseModel):
    continuous: bool
    series_breaks: int
    excluded_returns: int
    start_date: str | None
    end_date: str | None


class TearsheetExposureOut(BaseModel):
    snapshot_date: str
    base_currency: str
    total_value_base: float | None
    equity_weight: float | None
    cash_weight: float | None
    n_positions: int
    top_1_weight: float | None
    top_5_weight: float | None
    positions_value_base: float | None
    cash_value_base: float | None
    net_leverage: float | None
    gross_leverage: float | None
    weight_bases: dict[str, str]
    gross_positions_value_base: float | None
    top_1_gross_positions_weight: float | None
    top_5_gross_positions_weight: float | None


class TearsheetTraceOut(BaseModel):
    method: str
    # Solo presentes con portfolio (la rama no_portfolio los omite).
    n_snapshots: int | None = None
    n_returns: int | None = None


class PortfolioTearsheetOut(BaseModel):
    status: Literal["ok", "insufficient_data", "no_portfolio"]
    metrics: TearsheetMetricsOut | None
    qualification: TearsheetQualificationOut | None
    exposure: TearsheetExposureOut | None
    trace: TearsheetTraceOut
# --- GET /api/portfolio/cash -------------------------------------------------
# Forma medida contra la propia ruta (SELECT CashBalance directo): emite
# siempre las mismas cinco claves por divisa.


class CashBalanceOut(BaseModel):
    currency: str
    balance: float
    settled_cash: float
    interest_rate: float
    source: str


# --- GET /api/portfolio/forecast ---------------------------------------------
# Formas medidas contra la ruta (agregacion inline, servicio real): todas las
# ramas (vacia, monedas mezcladas, sin valor base) emiten las mismas seis
# claves de nivel superior; los huecos llegan como null, nunca omitidos.
# El tipo manuscrito del front no contemplaba reason_code "valuation_hold".


class ForecastScenarioOut(BaseModel):
    contribution_cagr: float
    contribution_total_return: float
    coverage: float
    horizon_scope: Literal["uniform", "mixed"]


class ForecastCoveredScenarioOut(BaseModel):
    cagr: float
    total_return: float
    coverage: float
    horizon_scope: Literal["uniform", "mixed"]


class ForecastCoveredOnlyOut(BaseModel):
    scenarios: dict[str, ForecastCoveredScenarioOut]
    expected_cagr: float | None


class ForecastPortfolioOut(BaseModel):
    total_value_base: float
    position_count: int
    covered_count: int
    excluded_count: int
    covered_weight: float | None
    scenarios: dict[str, ForecastScenarioOut] | None
    expected_cagr: float | None
    expected_coverage: float | None
    covered_only: ForecastCoveredOnlyOut


class ForecastPositionOut(BaseModel):
    ticker: str
    name: str
    weight: float
    currency: str
    weight_scope: Literal["total_portfolio", "valued_subset"]
    price: float
    price_as_of: str
    price_source: str
    price_veracity: Literal["OFICIAL", "MANUAL/NO OFICIAL", "NO VERIFICADA"]
    # El dict trae las tres claves de escenario y un valor None cuando ese
    # escenario no es computable (tesis sin bear/base/bull value).
    intrinsic: dict[str, float | None]
    comparison_basis: str
    probabilities: dict[str, float] | None
    probability_mass: float | None
    horizon_years: int
    thesis_version: int
    thesis_status: str
    model_version: int | None
    cagr: dict[str, float]
    total_return: dict[str, float]
    expected_cagr: float | None
    partial_expected_cagr: float | None
    contribution_expected: float | None


class ForecastExcludedOut(BaseModel):
    ticker: str
    name: str
    weight: float | None
    currency: str
    reason_code: Literal[
        "valuation_hold",
        "no_base_value",
        "no_published_thesis",
        "valuation_basis_unverified",
        "no_computable_intrinsic",
    ]
    reason: str


class PortfolioForecastOut(BaseModel):
    as_of: str | None
    base_currency: str | None
    portfolio: ForecastPortfolioOut | None
    positions: list[ForecastPositionOut]
    excluded: list[ForecastExcludedOut]
    assumptions: list[str]
# --- PATCH /api/portfolio/prices ---------------------------------------------
# Forma medida contra la ruta (precio manual): siempre las mismas dos claves.


class PortfolioPriceUpdateOut(BaseModel):
    ticker: str
    market_price: float


# --- POST /api/portfolio/refresh-market --------------------------------------
# Forma medida contra MarketRefreshService.refresh (servicio real): sobre un
# envelope fijo, los stages varian sus claves por paso (solo step/name/status
# son comunes) -> todo lo demas opcional y response_model_exclude_unset en la
# ruta. Los tres bloques operativos internos (risk, alert_results,
# screen_results) quedan free-form a proposito: son salidas de otros
# servicios con sus propias ramas, y tiparlos parcialmente borraria claves
# del wire (response_model filtra lo no declarado).


class RefreshMarketStageOut(BaseModel):
    step: int
    name: str
    status: str
    updated: int | None = None
    errors: list[dict[str, Any]] | None = None
    stale_prices: list[dict[str, Any]] | None = None
    portfolio_snapshot_id: int | None = None
    snapshot_pricing_coverage: float | None = None
    market_data_status: str | None = None
    alert_rules: int | None = None
    saved_screens: int | None = None


class PortfolioRefreshMarketOut(BaseModel):
    status: Literal["ok", "partial"]
    as_of: date
    started_at: datetime
    completed_at: datetime
    order: list[str]
    stages: list[RefreshMarketStageOut]
    risk: dict[str, Any]
    alert_results: list[dict[str, Any]]
    screen_results: list[dict[str, Any]]
