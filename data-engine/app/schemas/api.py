from datetime import datetime
from decimal import Decimal
from typing import Literal

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
    official_name: str
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
