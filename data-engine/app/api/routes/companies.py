import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.errors import safe_detail
from app.core.tenancy import tenant_filters
from app.models import (
    CalculatedMetric,
    Company,
    CompanyKPI,
    DecisionLesson,
    FinancialFact,
    FundamentalDriver,
    InferredInput,
    ManagementPromise,
    ThesisVersion,
)
from app.schemas import (
    CalculatedMetricOut,
    CalculatedMetricsResponse,
    CompanyKPIOut,
    CompanyOut,
    CompanySnapshotOut,
    CompanySnapshotsBatchOut,
    FinancialFactOut,
    FinancialRefreshResponse,
    ThesisTickersOut,
)
from app.schemas.ttm import CompanyTtmOut
from app.services import market_change
from app.services.analyst_targets_service import AnalystTargets, analyst_targets_service
from app.services.async_bridge import run_from_any_context
from app.services.company_changes_service import changes_since
from app.services.company_enrichment_service import CompanyEnrichmentService
from app.services.company_resolver import resolve_companies, resolve_company
from app.services.company_snapshot_service import CompanySnapshotService
from app.services.connectors.fmp import FMPClient
from app.services.decision_learning_service import (
    DECISION_ERROR_TAXONOMY,
    DecisionLearningService,
)
from app.services.driver_assumption_service import (
    DriverAssumptionService,
    driver_assumption_payload,
)
from app.services.extended_quote_service import ExtendedQuote, extended_quote_service
from app.services.fact_source_links import attach_assumption_sources
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.financial_terminal_service import FinancialTerminalService
from app.services.fundamental_model_repository import FundamentalModelRepository
from app.services.fundamental_review_service import (
    DecisionJournalService,
    ExpectationRealityService,
)
from app.services.inferred_input_llm_service import (
    InferenceRejected,
    infer_input,
)
from app.services.inferred_input_llm_service import (
    QuotaExceeded as InferenceQuotaExceeded,
)
from app.services.inferred_input_service import (
    InferredInputError,
    InferredInputService,
)
from app.services.inferred_input_service import payload as inferred_input_payload
from app.services.kpi_extraction_service import CompanyKPIRegistryService
from app.services.long_term_model_service import LongTermModelService
from app.services.management_credibility_service import ManagementCredibilityService
from app.services.metric_calculation_service import MetricCalculationService
from app.services.moat_service import MoatService
from app.services.peer_analysis_service import PeerAnalysisService
from app.services.peer_comparison_service import DEFAULT_PEER_METRICS, PeerComparisonService
from app.services.red_team_service import RedTeamService
from app.services.ttm_service import build_company_ttm
from app.services.wacc_input_service import WaccInputService

logger = logging.getLogger(__name__)

router = APIRouter()


MAX_SNAPSHOT_BATCH_TICKERS = 50


@router.get("/{ticker}/analyst-targets", response_model=AnalystTargets)
async def company_analyst_targets(ticker: str) -> AnalystTargets:
    """Per-firm analyst price targets (Yahoo Finance via yfinance, free and
    unofficial). Every row carries its source and date; a failed or empty
    source is reported as such, never filled in. Tickers without coverage on
    their bare line fall back to their reviewed listing (KRKNF -> PNG.V),
    declaring symbol and currency; a currency mismatch is never adopted."""
    result = await analyst_targets_service.get(ticker)
    if result.status != "empty":
        return result
    # Listado revisado (mapa de fundamentales no oficiales): si Yahoo no
    # cubre el ticker OTC pero si el listado oficial, se usa ESE, con la
    # divisa declarada verificada contra el mapa — nunca se adopta un
    # consenso en otra divisa.
    from app.services.yahoo_fundamentals_service import REVIEWED_MAP

    entry = REVIEWED_MAP.get(ticker.strip().upper())
    if not entry:
        return result
    alt = await analyst_targets_service.get(entry["symbol"])
    if alt.status != "available" or (alt.currency or "").upper() != entry["currency"]:
        return result
    return alt.model_copy(
        update={
            "symbol": ticker.strip().upper(),
            "source": (
                f"Yahoo Finance (no oficial) - listado {entry['symbol']} "
                f"en {entry['currency']}, agregado de analistas"
            ),
        }
    )


@router.get("/{ticker}/extended-quote", response_model=ExtendedQuote)
async def company_extended_quote(ticker: str, db: Session = Depends(get_db)) -> ExtendedQuote:
    """Yahoo intraday/extended hours. With the market closed, `change` and
    `change_percent` stay null (no live reference) and the day variation comes
    from official closes in our DB as `close_change*` (last close vs previous
    session). Any DB failure leaves those fields null; the quote still works."""
    quote = await extended_quote_service.get(ticker)
    if quote.status == "unavailable":
        # Emisor sin cotizacion en su listado OTC pero con listado revisado
        # (KRKNF -> PNG.V, TSXV, CAD): se usa ESE listado, declarando simbolo y
        # divisa; nunca se mezcla con cierres USD de la BD (sin close_change).
        from app.services.yahoo_fundamentals_service import REVIEWED_MAP

        entry = REVIEWED_MAP.get(ticker.strip().upper())
        if entry:
            alt = await extended_quote_service.get(entry["symbol"])
            if alt.status != "unavailable" and alt.price is not None and (alt.currency or "").upper() == entry["currency"]:
                return alt.model_copy(
                    update={
                        "ticker": ticker.strip().upper(),
                        "source": f"Yahoo Finance (no oficial) - listado {entry['symbol']} en {entry['currency']}, retraso posible",
                    }
                )
    if quote.session == "cerrado" and quote.price is not None:
        try:
            def _close_change() -> dict | None:
                company = resolve_company(db, ticker)
                return market_change.ticker_close_change(db, company.id) if company else None

            info = await run_in_threadpool(_close_change)
        except Exception:  # noqa: BLE001 - the quote must not depend on the DB
            logger.warning("extended-quote close change unavailable for %s", ticker, exc_info=True)
            info = None
        if info:
            from app.valuation.currency import normalize_currency

            source_currency, source_divisor = normalize_currency(info.get("currency"))
            quote_currency, quote_divisor = normalize_currency(quote.currency)
            if not source_currency or (quote_currency and source_currency != quote_currency):
                return quote
            quote.close_change = info["change"] * quote_divisor / source_divisor if quote_currency else None
            quote.close_change_percent = info["change_percent"]
            quote.close_change_date = info["date"]
            quote.close_change_previous_date = info["previous_date"]
    return quote



@router.get("/snapshots", response_model=CompanySnapshotsBatchOut)
def company_snapshots_batch(
    tickers: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> CompanySnapshotsBatchOut:
    """Snapshots de varias empresas en UNA llamada (indice de research).

    Sustituye el fan-out de ~40 GET /{ticker}/snapshot por visita del
    indice: la resolucion de tickers va en 1-2 queries IN (politica de
    alias de sufijos de resolve_company) y las del snapshot agregadas por
    IN(company_ids) (~13 para todo el lote, no 5 por empresa). Limites
    honestos: maximo MAX_SNAPSHOT_BATCH_TICKERS tickers por llamada (400
    por encima); los tickers sin company en el registro vuelven en
    ``missing`` y NUNCA se fabrican snapshots vacios para ellos.
    """
    requested: list[str] = []
    seen: set[str] = set()
    for raw in tickers.split(","):
        normalized = raw.strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            requested.append(normalized)
    if len(requested) > MAX_SNAPSHOT_BATCH_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximo {MAX_SNAPSHOT_BATCH_TICKERS} tickers por llamada",
        )
    companies, missing = resolve_companies(db, requested)
    snapshots = CompanySnapshotService().build_many(db, companies)
    return CompanySnapshotsBatchOut(
        snapshots={company.ticker: snapshots[company.id] for company in companies},
        missing=missing,
    )


@router.get("/thesis-tickers", response_model=ThesisTickersOut)
def thesis_tickers(db: Session = Depends(get_db)) -> ThesisTickersOut:
    """Tickers con tesis en UNA query DISTINCT (orden del indice de research).

    El indice ordena tesis > cartera > watchlist > resto; pedir un snapshot
    por empresa solo para saber si tiene tesis eran ~13 queries agregadas
    por lote de 50 en fan-out paralelo. La semantica replica la seleccion
    del snapshot (cualquier ThesisVersion de la company, sin filtro de
    estado), asi el bucket y la tarjeta nunca discrepan.
    """
    rows = db.scalars(
        select(Company.ticker)
        .where(
            Company.id.in_(
                select(ThesisVersion.company_id)
                .where(*tenant_filters(db, ThesisVersion))
                .distinct()
            )
        )
        .order_by(Company.ticker)
    ).all()
    return ThesisTickersOut(tickers=list(rows))


@router.get("/{ticker}/kpi-registry", response_model=list[CompanyKPIOut])
def company_kpi_registry(
    ticker: str, db: Session = Depends(get_db)
) -> list[CompanyKPI]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return list(
        db.scalars(
            select(CompanyKPI)
            .where(CompanyKPI.company_id == company.id, CompanyKPI.active.is_(True))
            .order_by(CompanyKPI.required.desc(), CompanyKPI.metric_key)
        ).all()
    )


@router.post("/{ticker}/kpi-registry/sync", response_model=list[CompanyKPIOut])
def sync_company_kpi_registry(
    ticker: str, db: Session = Depends(get_db)
) -> list[CompanyKPI]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return CompanyKPIRegistryService().sync(db, company)


class CompanyEnsureRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")
    name: str | None = Field(default=None, max_length=255)
    exchange: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, min_length=3, max_length=10)
    sector: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=160)
    domicile_country: str | None = Field(default=None, max_length=120)


class DecisionJournalCreate(BaseModel):
    decision: Literal["buy", "hold", "trim", "sell", "watch", "avoid"]
    rationale: str = Field(min_length=5, max_length=5000)
    what_must_be_true: list[str] = Field(default_factory=list, max_length=30)
    # Operacion real (compra/venta de IBKR o manual) que ejecuto la decision.
    transaction_id: int | None = Field(default=None, ge=1)


class DecisionJournalTradeLink(BaseModel):
    """Enlaza una entrada del diario a una operacion; null la desenlaza."""

    transaction_id: int | None = Field(default=None, ge=1)


class DriverAssumptionCreate(BaseModel):
    driver_key: str = Field(min_length=1, max_length=160)
    fiscal_year: int = Field(ge=1900, le=2200)
    scenario: Literal["bear", "base", "bull"] = "base"
    value: Decimal
    source: str = Field(min_length=1, max_length=240)
    user_override: bool = True
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=5000)


class InferredInputCreate(BaseModel):
    """Input INFERIDO: base explicita ("dado X, inferimos Y") + URLs https."""

    input_key: Literal["fcf_margin", "wacc", "terminal_growth"]
    value: Decimal
    base: str = Field(min_length=20, max_length=5000)
    source_urls: list[str] = Field(min_length=1, max_length=10)
    origin: Literal["llm", "user"] = "llm"


class DecisionLessonUpdate(BaseModel):
    taxonomy: Literal[
        "overestimating_TAM",
        "underestimating_dilution",
        "extrapolating_peak_margin",
        "ignoring_balance_sheet",
        "management_trust_error",
        "valuation_anchoring",
        "position_sizing_error",
        "selling_too_early",
        "ignoring_cyclicality",
        "thesis_drift",
    ]
    cause: str = Field(min_length=3, max_length=5000)
    error: str = Field(min_length=3, max_length=5000)
    lesson: str = Field(min_length=3, max_length=5000)
    future_application: str = Field(min_length=3, max_length=5000)


class DecisionLessonAction(BaseModel):
    action: Literal["approve", "reject"]


class ManagementPromiseCreate(BaseModel):
    promise: str = Field(min_length=3, max_length=5000)
    promise_date: date
    expected_period: str = Field(min_length=1, max_length=80)
    metric: str | None = Field(default=None, max_length=160)
    operator: Literal[">", ">=", "<", "<=", "=="] | None = None
    target_value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=40)
    source_document_id: int | None = None


class ManagementExplanationUpdate(BaseModel):
    explanation: str = Field(min_length=3, max_length=5000)


@router.post("/ensure", response_model=CompanyOut)
def ensure_company(payload: CompanyEnsureRequest, db: Session = Depends(get_db)) -> Company:
    ticker = payload.ticker.strip().upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        company = Company(
            ticker=ticker,
            name=(payload.name or ticker).strip(),
            exchange=(payload.exchange or "UNKNOWN").strip().upper(),
            currency=(payload.currency or "USD").strip().upper(),
            sector=(payload.sector or "Unknown").strip(),
            industry=(payload.industry or "Unknown").strip(),
            domicile_country=(
                payload.domicile_country.strip() if payload.domicile_country else None
            ),
            company_type="research_candidate",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        # Los callers (crear alerta, Propicks) suelen mandar solo el ticker;
        # sin esto la ficha queda con nombre/sector "Unknown" para siempre.
        # Enriquecemos desde Finnhub (best-effort: si falla, queda el stub).
        try:
            CompanyEnrichmentService().enrich(db, company)
        except Exception:  # noqa: BLE001 - el ensure nunca debe fallar por esto
            logger.warning("enrich fallo para %s", ticker, exc_info=True)
    else:
        if payload.name and company.name == company.ticker:
            company.name = payload.name.strip()
        if payload.exchange and company.exchange == "UNKNOWN":
            company.exchange = payload.exchange.strip().upper()
        if payload.sector and company.sector == "Unknown":
            company.sector = payload.sector.strip()
        if payload.industry and company.industry == "Unknown":
            company.industry = payload.industry.strip()
        if payload.domicile_country and not company.domicile_country:
            company.domicile_country = payload.domicile_country.strip()
        # La ficha ya existia con identidad en placeholder (p.ej. sector
        # "Unknown"): un ensure posterior es tambien oportunidad de
        # clasificarla, no solo el barrido manual. Best-effort (1 llamada
        # Finnhub por ensure afectado; si falla, queda como estaba).
        if CompanyEnrichmentService.needs_enrichment(company):
            try:
                # Enfriamiento: una ficha inenriquecible (industria no
                # mapeada) no llama a Finnhub en cada ensure, para siempre.
                CompanyEnrichmentService().enrich(db, company, respect_cooldown=True)
            except Exception:  # noqa: BLE001 - el ensure nunca debe fallar por esto
                logger.warning("enrich fallo para %s", ticker, exc_info=True)
    db.commit()
    db.refresh(company)
    return company


class IdentityVerificationRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")


class IdentityVerificationResponse(BaseModel):
    ticker: str
    verified: bool
    already_in_master: bool = False
    reasons: list[str] = []
    sec: dict | None = None
    provider: dict | None = None
    company: CompanyOut | None = None


def _homonym_conflict(db: Session, ticker: str, verified_name: str) -> str | None:
    """Homónimo con otra identidad en el maestro -> motivo de rechazo, o None.

    La doble coincidencia SEC+proveedor solo contrasta el símbolo en EE. UU.;
    sin ancla al emisor esperado confirmaría ALM como Almonty aunque el
    usuario busque Almirall (ALM.MC). Si el maestro ya conoce el ticker base
    (con o sin sufijo de mercado) con un nombre INCOMPATIBLE, el símbolo es
    ambiguo y no se verifica nada automáticamente.
    """
    from app.services.company_identity_verification import names_compatible

    candidates = list(
        db.scalars(
            select(Company).where(
                (Company.ticker == ticker) | (Company.ticker.like(f"{ticker}.%"))
            )
        ).all()
    )
    for company in candidates:
        if not names_compatible(company.name, verified_name):
            return (
                f"ticker_ambiguo: el maestro conoce {company.ticker} "
                f"«{company.name}», que no coincide con la identidad SEC/proveedor"
            )
    return None


async def _identity_lookup(ticker: str) -> tuple[dict | None, dict | None, str | None]:
    """Las dos lecturas externas (SEC company_tickers, Finnhub profile2).

    Sin efectos secundarios. Devuelve (entrada SEC, perfil proveedor, error de
    proveedor); cualquier fuente caída deja su evidencia en None (fail closed).
    """
    from app.services.connectors.finnhub import FinnhubClient
    from app.services.connectors.sec import SECClient

    entry = None
    try:
        mapping = await SECClient().ticker_map()
        for item in mapping.values():
            if isinstance(item, dict) and str(item.get("ticker", "")).upper() == ticker:
                entry = item
                break
    except Exception:  # noqa: BLE001 - la SEC caída no puede verificar: fail closed
        logger.warning("identity-verification: SEC no disponible para %s", ticker, exc_info=True)
    profile = None
    error = None
    finnhub = FinnhubClient()
    if not finnhub.configured():
        error = "proveedor_no_configurado"
    else:
        try:
            profile = await finnhub.profile(ticker)
        except Exception:  # noqa: BLE001 - proveedor caído: fail closed
            error = "proveedor_no_disponible"
            logger.warning("identity-verification: Finnhub no disponible para %s", ticker, exc_info=True)
    return entry, profile, error


def _identity_verdict(db: Session, ticker: str) -> tuple[IdentityVerificationResponse, Company | None]:
    """Veredicto de doble coincidencia + homónimos. SOLO LECTURA: nunca escribe.

    Devuelve (respuesta, compañía existente o None). La creación queda para
    el POST explícito.
    """
    from app.services.company_identity_verification import compare_identities

    existing = resolve_company(db, ticker)
    if existing is not None:
        return (
            IdentityVerificationResponse(
                ticker=ticker, verified=True, already_in_master=True,
                reasons=["ya_en_maestro: la ficha ya existía"],
                company=CompanyOut.model_validate(existing),
            ),
            existing,
        )

    sec_entry, provider_profile, provider_error = run_from_any_context(_identity_lookup(ticker))
    verdict = compare_identities(ticker, sec_entry, provider_profile)
    reasons = list(verdict.reasons)
    if provider_error and provider_profile is None:
        reasons = [provider_error if r.startswith("proveedor_sin_perfil") else r for r in reasons]

    if verdict.verified and verdict.sec is not None:
        conflict = _homonym_conflict(db, ticker, verdict.sec["name"])
        if conflict is not None:
            reasons.append(conflict)
            return (
                IdentityVerificationResponse(
                    ticker=ticker, verified=False, reasons=reasons,
                    sec=verdict.sec, provider=verdict.provider,
                ),
                None,
            )

    return (
        IdentityVerificationResponse(
            ticker=ticker, verified=verdict.verified, reasons=reasons,
            sec=verdict.sec, provider=verdict.provider,
        ),
        None,
    )


@router.get("/identity-verification", response_model=IdentityVerificationResponse)
def get_identity_verification(
    ticker: Annotated[str, Query(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")],
    db: Session = Depends(get_db),
) -> IdentityVerificationResponse:
    """Veredicto de identidad de un ticker fuera del maestro. SOLO LECTURA.

    Lo usa el render de /research/<ticker>: una petición GET de página jamás
    crea una ficha; la creación exige el POST (acción explícita del usuario).
    """
    response, _ = _identity_verdict(db, ticker.strip().upper())
    return response


@router.post("/verify-identity", response_model=IdentityVerificationResponse)
def verify_identity(payload: IdentityVerificationRequest, db: Session = Depends(get_db)) -> IdentityVerificationResponse:
    """Crea la ficha stub SOLO con doble coincidencia SEC + proveedor verificada.

    Repite la comprobación completa (nunca confía en una verificación previa):
    ticker exacto y razón social compatible en SEC y proveedor, bolsa de
    EE. UU. y divisa declaradas por el proveedor, y sin homónimo con otra
    identidad en el maestro. La ficha creada lleva la procedencia etiquetada
    («identity:sec+finnhub»). Sin doble coincidencia no crea nada.
    """
    from app.services.company_identity_verification import compare_identities  # noqa: F401 - documenta la regla

    ticker = payload.ticker.strip().upper()
    response, existing = _identity_verdict(db, ticker)
    if not response.verified or existing is not None:
        return response

    # Doble coincidencia verificada: la identidad se crea con procedencia
    # etiquetada. Nombre = razón social SEC (registro oficial); bolsa, divisa
    # y país salen SIEMPRE de la evidencia del proveedor (sin valores por
    # defecto: el comparador ya rechazó el veredicto si faltan).
    assert response.sec is not None and response.provider is not None
    company = Company(
        ticker=ticker,
        name=response.sec["name"].strip() or response.provider["name"].strip(),
        exchange=response.provider["exchange"].strip().upper(),
        currency=response.provider["currency"].strip().upper(),
        sector="Unknown",
        industry="Unknown",
        cik=str(response.sec["cik"]).zfill(10),
        domicile_country=response.provider["country"] or None,
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=["identity:sec+finnhub"],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    try:
        db.commit()
    except IntegrityError:
        # Doble clic en «Abrir ficha»: dos POST pasan la comprobación a la vez y
        # el segundo choca con el UNIQUE de ticker. La ficha ya existe: se
        # responde igual que si hubiera estado en el maestro (idempotente).
        db.rollback()
        winner = resolve_company(db, ticker)
        if winner is None:
            raise
        return IdentityVerificationResponse(
            ticker=ticker, verified=True, already_in_master=True,
            reasons=["ya_en_maestro: la ficha ya existía"],
            company=CompanyOut.model_validate(winner),
        )
    db.refresh(company)
    response.company = CompanyOut.model_validate(company)
    return response


@router.get("", response_model=list[CompanyOut])
def list_companies(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[Company]:
    return list(
        db.scalars(select(Company).order_by(Company.ticker).limit(limit).offset(offset)).all()
    )


@router.get("/{ticker}", response_model=CompanyOut)
def get_company(ticker: str, db: Session = Depends(get_db)) -> Company:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.get("/{ticker}/facts", response_model=list[FinancialFactOut])
def list_financial_facts(
    ticker: str,
    metric: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[FinancialFact]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    query = (
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id)
        # El frontend enlaza cada cifra a su fuente: una sola query extra para
        # todos los documentos en vez de un lazy load por hecho.
        .options(selectinload(FinancialFact.source))
    )
    if metric:
        query = query.where(FinancialFact.metric == metric)
    query = query.order_by(
        FinancialFact.fiscal_year.desc().nullslast(),
        desc(FinancialFact.created_at),
    ).limit(limit)
    return list(db.scalars(query).all())


@router.get("/{ticker}/financial-terminal")
def financial_terminal(
    ticker: str,
    metrics: str | None = None,
    years: int = Query(default=10, ge=1, le=20),
    periodicity: Literal["all", "annual", "quarterly"] = "all",
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    requested = (
        [item.strip() for item in metrics.split(",") if item.strip()]
        if metrics
        else None
    )
    return FinancialTerminalService().build(
        db,
        company,
        metrics=requested,
        years=years,
        periodicity=periodicity,
    )


@router.get("/{ticker}/ttm", response_model=CompanyTtmOut)
def company_ttm(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Fundamentales actuales en TTM (últimos 4 trimestres), con respaldo FY.

    Flujos = suma de los 4 últimos trimestres consecutivos (Q4 = FY − 9M si no
    hay 10-Q del cuarto); balance = último trimestre. Cada métrica dice su base
    (TTM / FY / Q / SIN_DATOS) y su procedencia (OFICIAL / INFERIDO).
    """
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return build_company_ttm(db, company)


@router.get("/{ticker}/metrics/calculated", response_model=CalculatedMetricsResponse)
def list_calculated_metrics(
    ticker: str,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    metrics = list(
        db.scalars(
            select(CalculatedMetric)
            .where(CalculatedMetric.company_id == company.id)
            .order_by(
                CalculatedMetric.fiscal_year.desc().nullslast(),
                desc(CalculatedMetric.created_at),
            )
            .limit(limit)
        ).all()
    )
    return {
        "ticker": company.ticker,
        "status": "persisted" if metrics else "not_generated",
        "metrics": [
            CalculatedMetricOut(
                id=result.id,
                company_id=company.id,
                metric=result.metric,
                value=result.value,
                unit=result.unit,
                period=result.period,
                fiscal_year=result.fiscal_year,
                fiscal_quarter=result.fiscal_quarter,
                status=result.status,
                definition_version=result.definition_version,
                formula=result.formula,
                numerator=result.numerator,
                denominator=result.denominator,
                source_fact_ids=result.source_fact_ids,
                calculation_trace=result.calculation_trace,
                confidence=result.confidence,
            )
            for result in metrics
        ],
    }


@router.post("/{ticker}/metrics/refresh", response_model=CalculatedMetricsResponse)
def refresh_calculated_metrics(
    ticker: str,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    metrics = MetricCalculationService().calculate_all(db, company, persist=True)
    return {
        "ticker": company.ticker,
        "status": "calculated",
        "metrics": [
            CalculatedMetricOut(
                id=result.id,
                company_id=company.id,
                metric=result.metric,
                value=result.value,
                unit=result.unit,
                period=result.period,
                fiscal_year=result.fiscal_year,
                fiscal_quarter=result.fiscal_quarter,
                status=result.status,
                definition_version=result.definition_version,
                formula=result.formula,
                numerator=result.numerator,
                denominator=result.denominator,
                source_fact_ids=result.source_fact_ids,
                calculation_trace=result.calculation_trace,
                confidence=result.confidence,
            )
            for result in metrics
        ],
    }


@router.get("/{ticker}/changes-since")
def company_changes_since(
    ticker: str,
    since: datetime = Query(..., description="ISO 8601: ultima visita del usuario"),
    db: Session = Depends(get_db),
) -> dict:
    """Documentos, hechos y cambios de tesis creados despues de ``since``."""
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return changes_since(db, company.id, since)


@router.get("/{ticker}/long-term-model")
def long_term_model(
    ticker: str,
    db: Session = Depends(get_db),
) -> dict:
    """Return the source-aware 5–10 year fundamental model for a company."""
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    payload = FundamentalModelRepository().latest_payload(db, company)
    if not payload:
        return {
            "ticker": company.ticker,
            "status": "not_generated",
            "publishable": False,
        }
    return attach_assumption_sources(db, company.id, payload)


@router.post("/{ticker}/long-term-model/generate")
def generate_long_term_model(
    ticker: str,
    horizon: int = Query(default=5, ge=5, le=10),
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return LongTermModelService().build(db, company, horizon=horizon)


@router.get("/{ticker}/driver-assumptions")
def list_driver_assumptions(
    ticker: str,
    driver_key: str | None = None,
    scenario: Literal["bear", "base", "bull"] | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    versions = DriverAssumptionService().list(
        db, company, driver_key=driver_key, scenario=scenario
    )
    driver_keys = {
        driver.id: driver.driver_key
        for driver in db.scalars(
            select(FundamentalDriver).where(
                FundamentalDriver.id.in_({version.driver_id for version in versions})
            )
        ).all()
    } if versions else {}
    return [
        driver_assumption_payload(
            version, driver_key=driver_keys.get(version.driver_id)
        )
        for version in versions
    ]


@router.post("/{ticker}/driver-assumptions", status_code=201)
def create_driver_assumption(
    ticker: str,
    payload: DriverAssumptionCreate,
    horizon: int = Query(default=5, ge=5, le=10),
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        version = DriverAssumptionService().create(
            db,
            company,
            driver_key=payload.driver_key,
            fiscal_year=payload.fiscal_year,
            scenario=payload.scenario,
            value=payload.value,
            source=payload.source,
            user_override=payload.user_override,
            confidence=payload.confidence,
            rationale=payload.rationale,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    model = LongTermModelService().build(db, company, horizon=horizon)
    return {
        "assumption": driver_assumption_payload(version, driver_key=payload.driver_key),
        "model_version": model.get("persistence"),
    }


@router.get("/{ticker}/inferred-inputs")
def list_inferred_inputs(ticker: str, db: Session = Depends(get_db)) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        return []
    rows = db.scalars(
        select(InferredInput)
        .where(InferredInput.tenant_id == tenant_id, InferredInput.company_id == company.id)
        .order_by(desc(InferredInput.id))
        .limit(50)
    ).all()
    return [inferred_input_payload(row) for row in rows]


@router.post("/{ticker}/inferred-inputs", status_code=201)
def create_inferred_input(
    ticker: str,
    payload: InferredInputCreate,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    company_id = company.id
    db.commit()  # Close reads before acquiring the tenant/company-pair write lock.
    try:
        row = InferredInputService().create_guarded(
            db,
            company_id,
            input_key=payload.input_key,
            value=payload.value,
            base=payload.base,
            source_urls=payload.source_urls,
            origin=payload.origin,
        )
    except InferredInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return inferred_input_payload(row)


class InferredInputLLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_key: Literal["fcf_margin", "wacc", "terminal_growth"] = "fcf_margin"


@router.post("/{ticker}/inferred-inputs/llm", status_code=201)
async def create_inferred_input_llm(
    ticker: str,
    payload: InferredInputLLMRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Estima FCF, WACC o crecimiento terminal desde extractos ingeridos. Guarda INFERIDO."""

    def _infer() -> dict:
        try:
            return inferred_input_payload(
                run_from_any_context(infer_input(db, ticker, input_key=payload.input_key))
            )
        except InferenceQuotaExceeded as exc:
            db.rollback()
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except InferenceRejected as exc:
            db.rollback()
            status = {"empresa_no_encontrada": 404, "llm_deshabilitado": 503, "presupuesto_agotado": 503}.get(
                exc.reason, 422
            )
            detail = "N/D: sin extractos ingeridos con URL https para esta empresa" if exc.reason == "sin_fuentes" else (
                f"Inferencia rechazada: {exc.reason}"
            )
            raise HTTPException(status_code=status, detail=detail) from exc

    # SQLAlchemy y el LLM son sincronos: todo corre en un hilo del pool y la
    # corutina del servicio puentea con run_from_any_context. Inline en el
    # "async def", la inferencia bloqueaba el event loop del proceso.
    return await run_in_threadpool(_infer)


@router.get("/{ticker}/snapshot", response_model=CompanySnapshotOut)
def company_snapshot(
    ticker: str,
    db: Session = Depends(get_db),
) -> CompanySnapshotOut:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return CompanySnapshotService().build(db, company)


@router.post("/{ticker}/snapshot/refresh", response_model=CompanySnapshotOut)
def refresh_company_snapshot(
    ticker: str,
    horizon: int = Query(default=5, ge=5, le=10),
    db: Session = Depends(get_db),
) -> CompanySnapshotOut:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    MetricCalculationService().calculate_all(db, company, persist=True)
    LongTermModelService().build(db, company, horizon=horizon)
    MoatService().assess(db, company, persist=True)
    return CompanySnapshotService().build(db, company)


@router.get("/{ticker}/decision-journal")
def decision_journal(ticker: str, db: Session = Depends(get_db)) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    from app.services.journal_trade_link import journal_entry_payload

    return [journal_entry_payload(db, entry) for entry in DecisionJournalService().list(db, company)]


@router.get("/{ticker}/decision-journal/trades")
def decision_journal_trades(ticker: str, db: Session = Depends(get_db)) -> list[dict]:
    """Compras y ventas del ticker que se pueden enlazar a una entrada del diario."""
    from app.services.journal_trade_link import journal_trades

    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return journal_trades(db, company)


@router.put("/{ticker}/decision-journal/{entry_id}/transaction")
def link_decision_journal_trade(
    ticker: str,
    entry_id: int,
    payload: DecisionJournalTradeLink,
    db: Session = Depends(get_db),
) -> dict:
    from app.services.journal_trade_link import journal_entry_payload

    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        entry = DecisionJournalService().link_transaction(
            db, company, entry_id, payload.transaction_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return journal_entry_payload(db, entry)


@router.post("/{ticker}/decision-journal", status_code=201)
def create_decision_journal_entry(
    ticker: str,
    payload: DecisionJournalCreate,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    from app.services.journal_trade_link import journal_entry_payload

    try:
        entry = DecisionJournalService().create(
            db,
            company,
            decision=payload.decision,
            rationale=payload.rationale,
            what_must_be_true=[item.strip() for item in payload.what_must_be_true if item.strip()],
            transaction_id=payload.transaction_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return journal_entry_payload(db, entry)


@router.get("/{ticker}/decision-lessons/taxonomy")
def decision_lesson_taxonomy(ticker: str, db: Session = Depends(get_db)) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"taxonomy": sorted(DECISION_ERROR_TAXONOMY)}


@router.get("/{ticker}/decision-lessons")
def decision_lessons(ticker: str, db: Session = Depends(get_db)) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return [
        DecisionLearningService.payload(item)
        for item in DecisionLearningService.list(db, company)
    ]


@router.post("/{ticker}/decision-lessons/propose")
def propose_decision_lessons(
    ticker: str, db: Session = Depends(get_db)
) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return [
        DecisionLearningService.payload(item)
        for item in DecisionLearningService().propose_from_reviews(db, company)
    ]


@router.put("/{ticker}/decision-lessons/{lesson_id}")
def update_decision_lesson(
    ticker: str,
    lesson_id: int,
    payload: DecisionLessonUpdate,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    lesson = db.get(DecisionLesson, lesson_id)
    if not company or not lesson or lesson.company_id != company.id:
        raise HTTPException(status_code=404, detail="Decision lesson not found")
    try:
        item = DecisionLearningService().update(
            db,
            lesson,
            taxonomy=payload.taxonomy,
            cause=payload.cause,
            error=payload.error,
            lesson_text=payload.lesson,
            future_application=payload.future_application,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DecisionLearningService.payload(item)


@router.post("/{ticker}/decision-lessons/{lesson_id}/action")
def decide_decision_lesson(
    ticker: str,
    lesson_id: int,
    payload: DecisionLessonAction,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    lesson = db.get(DecisionLesson, lesson_id)
    if not company or not lesson or lesson.company_id != company.id:
        raise HTTPException(status_code=404, detail="Decision lesson not found")
    try:
        item = DecisionLearningService().decide(
            db,
            lesson,
            action=payload.action,
            actor=str(db.info.get("user_id") or "local-user"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DecisionLearningService.payload(item)


@router.get("/{ticker}/management-credibility")
def management_credibility(ticker: str, db: Session = Depends(get_db)) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return ManagementCredibilityService().dashboard(db, company)


@router.post("/{ticker}/management-credibility/promises", status_code=201)
def register_management_promise(
    ticker: str,
    payload: ManagementPromiseCreate,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        row = ManagementCredibilityService().register(
            db, company, **payload.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ManagementCredibilityService.payload(row)


@router.post("/{ticker}/management-credibility/import-call-claims")
def import_management_call_claims(
    ticker: str, db: Session = Depends(get_db)
) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return [
        ManagementCredibilityService.payload(row)
        for row in ManagementCredibilityService().import_call_claims(db, company)
    ]


@router.post("/{ticker}/management-credibility/reconcile")
def reconcile_management_promises(
    ticker: str, db: Session = Depends(get_db)
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    ManagementCredibilityService().reconcile(db, company)
    return ManagementCredibilityService().dashboard(db, company)


@router.put("/{ticker}/management-credibility/promises/{promise_id}/explanation")
def update_management_explanation(
    ticker: str,
    promise_id: int,
    payload: ManagementExplanationUpdate,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    promise = db.get(ManagementPromise, promise_id)
    if not company or not promise or promise.company_id != company.id:
        raise HTTPException(status_code=404, detail="Management promise not found")
    row = ManagementCredibilityService().set_explanation(
        db, promise, payload.explanation
    )
    return ManagementCredibilityService.payload(row)


@router.get("/{ticker}/expectation-reality")
def expectation_reality(ticker: str, db: Session = Depends(get_db)) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return [_expectation_payload(item) for item in ExpectationRealityService().list(db, company)]


@router.post("/{ticker}/expectation-reality/review")
def review_expectation_reality(
    ticker: str,
    db: Session = Depends(get_db),
) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return [_expectation_payload(item) for item in ExpectationRealityService().review(db, company)]


def _expectation_payload(item) -> dict:
    return {
        "id": item.id,
        "model_version_id": item.model_version_id,
        "forecast_id": item.forecast_id,
        "actual_fact_id": item.actual_fact_id,
        "actual_metric_id": item.actual_metric_id,
        "actual_source_type": item.actual_source_type,
        "semantics": item.semantics,
        "fiscal_year": item.fiscal_year,
        "metric": item.metric,
        "expected_value": item.expected_value,
        "actual_value": item.actual_value,
        "variance": item.variance,
        "variance_percent": item.variance_percent,
        "status": item.status,
        "reviewed_at": item.reviewed_at,
        "trace": item.trace,
    }


@router.get("/{ticker}/peers/comparison")
def peer_comparison(
    ticker: str,
    limit: int = Query(default=8, ge=1, le=20),
    metrics: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    metric_names = [item.strip() for item in metrics.split(",") if item.strip()] if metrics else DEFAULT_PEER_METRICS
    # GET solo lectura: nunca persiste. Recalcular y guardar metricas va por POST.
    return PeerComparisonService().compare(
        db,
        company,
        limit=limit,
        metrics=metric_names,
        refresh=False,
    )


@router.post("/{ticker}/peers/comparison/refresh")
def refresh_peer_comparison(
    ticker: str,
    limit: int = Query(default=8, ge=1, le=20),
    metrics: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    metric_names = [item.strip() for item in metrics.split(",") if item.strip()] if metrics else DEFAULT_PEER_METRICS
    return PeerComparisonService().compare(
        db,
        company,
        limit=limit,
        metrics=metric_names,
        refresh=True,
    )


@router.get("/{ticker}/peers/analysis")
def peer_analysis(
    ticker: str,
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return PeerAnalysisService().analyze(db, company, limit=limit)


@router.get("/{ticker}/moat")
def moat_assessment(
    ticker: str,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return MoatService().read(db, company)


@router.post("/{ticker}/moat/refresh")
def refresh_moat_assessment(
    ticker: str,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return MoatService().assess(db, company, persist=True)


@router.post("/{ticker}/red-team")
def run_red_team(ticker: str, db: Session = Depends(get_db)) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    run = RedTeamService().run(db, company)
    return _red_team_payload(run)


@router.get("/{ticker}/red-team/latest")
def latest_red_team(ticker: str, db: Session = Depends(get_db)) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    run = RedTeamService().latest(db, company)
    if not run:
        raise HTTPException(status_code=404, detail="No red-team run found")
    return _red_team_payload(run)


def _red_team_payload(run) -> dict:
    return {
        "id": run.id,
        "company_id": run.company_id,
        "thesis_version_id": run.thesis_version_id,
        "status": run.status,
        "score": run.score,
        "strongest_bear_case": run.strongest_bear_case,
        "findings": run.findings,
        "broken_assumptions": run.broken_assumptions,
        "missing_risks": run.missing_risks,
        "falsification_tests": run.falsification_tests,
        "model": run.model,
        "prompt_version": run.prompt_version,
        "trace": run.trace,
        "created_at": run.created_at,
    }


@router.post("/{ticker}/refresh/fmp", response_model=FinancialRefreshResponse)
async def refresh_fmp_financials(ticker: str, db: Session = Depends(get_db)) -> dict:
    # Resolve + ingesta son trabajo sincrono (sqlalchemy, parseo, escrituras):
    # corren en un hilo del pool; la corutina del servicio puentea con
    # run_from_any_context. Inline bloqueaban el event loop del proceso.
    def _refresh() -> dict:
        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        try:
            return run_from_any_context(
                FinancialIngestionService().refresh_from_fmp(
                    db=db,
                    company=company,
                    client=FMPClient(),
                )
            )
        except RuntimeError as exc:
            # El RuntimeError envuelve el texto del error de httpx, que lleva la
            # URL completa con la api key del proveedor en la query.
            raise HTTPException(status_code=424, detail=safe_detail(exc, 424)) from exc
        except httpx.HTTPStatusError as exc:
            # Sanitize: httpx exception text embeds the full request URL,
            # which carries the FMP api key - never log or return it.
            status = exc.response.status_code
            if status == 402:
                # El plan gratuito de FMP no cubre mercados fuera de US ni
                # algunos endpoints; mensaje accionable en vez de un error crudo.
                raise HTTPException(
                    status_code=424,
                    detail=(
                        "El plan gratuito de FMP no cubre este mercado. "
                        "Para emisores europeos usa la fuente ESEF y para "
                        "americanos la SEC."
                    ),
                ) from None
            raise HTTPException(
                status_code=424,
                detail=f"FMP request failed with HTTP {status}",
            ) from None

    return await run_in_threadpool(_refresh)


@router.post("/{ticker}/refresh/sec", response_model=FinancialRefreshResponse)
async def refresh_sec_financials(ticker: str, db: Session = Depends(get_db)) -> dict:
    def _refresh() -> dict:
        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        try:
            service = FinancialIngestionService()
            result = run_from_any_context(service.refresh_from_sec(db=db, company=company))
        except RuntimeError as exc:
            # El RuntimeError envuelve el texto del error de httpx, que lleva la
            # URL completa con la api key del proveedor en la query.
            raise HTTPException(status_code=424, detail=safe_detail(exc, 424)) from exc
        # Completa el contrato FinancialRefreshResponse (la via SEC solo importa
        # hechos, no statements; el resumen se calcula aqui para no meter queries
        # extra en el servicio).
        result["statements_imported"] = 0
        result["latest_periods"] = service.latest_periods(db, company)
        result["valuation_input_ready"] = service.valuation_input_ready(db, company)
        return result

    return await run_in_threadpool(_refresh)


@router.post("/{ticker}/refresh/esef", response_model=FinancialRefreshResponse)
async def refresh_esef_financials(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Fundamentales IFRS anuales desde el snapshot ESEF local (IBEX reviewed)."""

    def _refresh() -> dict:
        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        try:
            service = FinancialIngestionService()
            # refresh_from_esef es una corutina sin awaits internos: la
            # lectura del snapshot y las escrituras son sincronas.
            result = run_from_any_context(service.refresh_from_esef(db=db, company=company))
        except RuntimeError as exc:
            # El RuntimeError envuelve el texto del error de httpx, que lleva la
            # URL completa con la api key del proveedor en la query.
            raise HTTPException(status_code=424, detail=safe_detail(exc, 424)) from exc
        result["statements_imported"] = 0
        return result

    return await run_in_threadpool(_refresh)


@router.post("/{ticker}/refresh/yahoo-fundamentals", response_model=FinancialRefreshResponse)
async def refresh_yahoo_fundamentals(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Fundamentales anuales NO oficiales (Yahoo) para emisores sin SEC/ESEF del mapa revisado."""

    def _refresh() -> dict:
        from app.services.yahoo_fundamentals_service import refresh_from_yahoo

        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        try:
            result = refresh_from_yahoo(db, company)
        except RuntimeError as exc:
            raise HTTPException(status_code=424, detail=safe_detail(exc, 424)) from exc
        service = FinancialIngestionService()
        result["latest_periods"] = service.latest_periods(db, company)
        result["valuation_input_ready"] = service.valuation_input_ready(db, company)
        result["statements_imported"] = 0
        return result

    return await run_in_threadpool(_refresh)


@router.post("/{ticker}/refresh/wacc")
async def refresh_wacc_inputs(
    ticker: str, db: Session = Depends(get_db)
) -> dict:
    def _refresh() -> dict:
        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        try:
            return run_from_any_context(WaccInputService().refresh(db, company))
        except RuntimeError as exc:
            # El RuntimeError envuelve el texto del error de httpx, que lleva la
            # URL completa con la api key del proveedor en la query.
            raise HTTPException(status_code=424, detail=safe_detail(exc, 424)) from exc

    return await run_in_threadpool(_refresh)


@router.get("/{ticker}/share-capital")
def company_share_capital(ticker: str, db: Session = Depends(get_db)) -> dict:
    from app.services.share_capital_service import build_share_capital

    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return build_share_capital(db, company)
