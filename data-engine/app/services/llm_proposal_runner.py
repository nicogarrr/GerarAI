"""Cableado del motor de propuestas LLM (item 1): contexto real, cuota y presupuesto.

El modelo solo ve titulares ya guardados para la empresa, una cotizacion fresca y,
si existe, la tesis vigente del tenant (solo campos publicables), que queda anclada.
Sin empresa seguida, sin titulares recientes, sin cotizacion, sin presupuesto o
con la cuota diaria agotada no se llama al modelo o no se guarda nada.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.tenancy import tenant_filters
from app.llm import create_llm_provider
from app.llm.model_aliases import is_owner_approved_model
from app.models.entities import Company, NewsEvent
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.budget import BudgetController, BudgetExceededError
from app.services.llm_proposal_service import ProposalRejected, build_request, propose
from app.services.paper_thesis_anchor import current_thesis, prompt_context
from app.services.paper_trading_service import create_proposal
from app.services.proposal_momentum import load_momentum

DAILY_QUOTA = 5  # propuestas LLM guardadas por tenant y dia UTC
NEWS_WINDOW = timedelta(days=14)
MAX_HEADLINES = 8
_TICKER = re.compile(r"^[A-Za-z0-9.^=-]{1,20}$")


class QuotaExceeded(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"cuota diaria de {limit} propuestas LLM agotada")
        self.limit = limit


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def paid_model_risk(
    provider, *, request=None, settings: Settings | None = None
) -> str | None:
    """Motivo de bloqueo si la peticion REAL podria usar un modelo no aprobado.

    Aprobados: free verificados o el modelo Go de la suscripcion del dueno (solo
    con ``chat_go_subscription_enabled``). `request` permite verificar la
    petición real de otros flujos (p. ej. narrativa). Por defecto la sonda es la
    misma peticion que `propose` envia (build_request: sin modelo fijado, solo
    task), de modo que los overrides de entorno por tarea se resuelven igual que
    en la llamada real. Tambien se mira el modelo de fallback del adaptador.
    Fail-closed: si no se puede verificar, se bloquea.
    """
    settings = settings or get_settings()
    router = getattr(provider, "model_router", None)
    if router is None:
        return "modelo_no_verificable"
    probe = request if request is not None else build_request("X", Decimal(1), "USD", [], None)
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


def todays_llm_proposals(db: Session, now: datetime) -> int:
    start = _utc(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count(PaperTrade.id)).where(
                PaperTrade.proposal_key.like("llm:%"),
                PaperTrade.created_at >= start,
                *tenant_filters(db, PaperTrade),
            )
        )
        or 0
    )


_quota_guard = threading.Lock()
_quota_locks: dict[tuple, threading.Lock] = {}


def _quota_lock(db: Session, now: datetime) -> threading.Lock:
    key = (db.info.get("tenant_id"), _utc(now).date())
    with _quota_guard:
        return _quota_locks.setdefault(key, threading.Lock())


def save_within_quota(
    db: Session, proposal: PaperProposal, now: datetime, *, thesis_version_id: int | None = None
) -> PaperTrade:
    """Cuenta y guarda en una transaccion corta serializada por tenant y dia.

    Candado de proceso mas pg_advisory_xact_lock (varios workers). Se toma DESPUES
    del LLM y se suelta con el commit de create_proposal: nunca cubre cotizacion ni modelo.
    """
    db.commit()  # sin instantanea vieja: el count ve lo ya confirmado
    with _quota_lock(db, now):
        if db.get_bind().dialect.name == "postgresql":
            raw = f"llm-quota:{db.info.get('tenant_id')}:{_utc(now).date()}".encode()
            key = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") >> 1
            db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
        if todays_llm_proposals(db, now) >= DAILY_QUOTA:
            db.rollback()
            raise QuotaExceeded(DAILY_QUOTA)
        try:
            return create_proposal(db, proposal, thesis_version_id=thesis_version_id)
        except Exception:
            db.rollback()
            raise


def headline_matches_company(title: str, ticker: str, name: str) -> bool:
    """Match publisher headline only. No inference from legacy composite titles."""
    ticker_pattern = (rf"(?:\$|(?:NYSE|NASDAQ):){re.escape(ticker)}(?!\w)" if len(ticker) == 1
                      else rf"(?<!\w){re.escape(ticker)}(?!\w)")
    if re.search(ticker_pattern, title, re.I):
        return True
    clean_name = re.sub(r"(?:[,\s]+(?:inc\.?|corp\.?|corporation|plc|ltd\.?))+$", "", name.strip(), flags=re.I)
    return bool(clean_name) and re.search(rf"(?<!\w){re.escape(clean_name)}(?!\w)", title, re.I) is not None


def load_headlines(db: Session, ticker: str, now: datetime) -> list[dict]:
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        raise ProposalRejected("empresa_no_seguida")
    rows = db.scalars(
        select(NewsEvent)
        .where(NewsEvent.company_id == company.id,
            NewsEvent.date >= _utc(now) - NEWS_WINDOW,
            NewsEvent.date <= _utc(now),  # sin evidencia con fecha futura
        )
        .order_by(NewsEvent.date.desc(), NewsEvent.id.desc())
        .limit(MAX_HEADLINES * 4)
    ).all()
    # Copia escalares: la sesion se libera antes de cualquier E/S de red.
    return [
        {"id": f"news:{n.id}", "title": n.metadata_["source_headline"].strip(), "published_at": _utc(n.date).isoformat(), "source": n.source}
        for n in rows if isinstance((n.metadata_ or {}).get("source_headline"), str)
        and n.metadata_["source_headline"].strip()
        and headline_matches_company(n.metadata_["source_headline"].strip(), ticker, company.name)
    ][:MAX_HEADLINES]


async def generate_proposal(
    db: Session,
    ticker: str,
    *,
    provider=None,
    fetch_quote=None,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PaperTrade:
    # Reloj: `clock` (inyectable) > `now` fijo (tests/replay) > reloj real. La frescura de
    # la cotizacion se valida contra el reloj POSTERIOR al fetch, no el del inicio: una
    # cotizacion recibida segundos despues de arrancar no es "futura".
    fixed_now = now

    def _real_clock() -> datetime:
        return fixed_now if fixed_now is not None else datetime.now(UTC)

    read_clock: Callable[[], datetime] = clock or _real_clock
    now = read_clock()
    ticker = (ticker or "").strip().upper()
    if not _TICKER.match(ticker):
        raise ProposalRejected("ticker_invalido")
    provider = provider or create_llm_provider()
    if provider.name == "disabled":
        raise ProposalRejected("llm_deshabilitado")
    # Solo modelos gratuitos (EUR 0): se resuelve ANTES de gastar nada, con el router
    # del adaptador y una peticion construida por build_request (la misma que se enviara).
    blocked = paid_model_risk(provider)
    if blocked:
        raise ProposalRejected(blocked)
    budget = BudgetController()
    if not budget.can_spend(db, 0.02):
        raise ProposalRejected("presupuesto_agotado")
    if todays_llm_proposals(db, now) >= DAILY_QUOTA:
        raise QuotaExceeded(DAILY_QUOTA)
    headlines = load_headlines(db, ticker, now)
    if not headlines:
        raise ProposalRejected("sin_titulares")
    momentum = load_momentum(db, ticker, now)
    # La tesis que vera el modelo es la que queda anclada, aunque otra version
    # se publique mientras dura la llamada.
    thesis_row = current_thesis(db, ticker)
    thesis = prompt_context(db, thesis_row) if thesis_row is not None else None
    thesis_version_id = thesis_row.id if thesis_row is not None else None
    db.commit()  # sin conexion ni transaccion abiertas durante cotizacion y LLM
    if fetch_quote is None:
        from app.api.routes.market import market_quote as fetch_quote
    try:
        quote = await asyncio.to_thread(fetch_quote, ticker)
    except Exception:  # noqa: BLE001 - sin cotizacion no hay propuesta
        quote = None
    now = read_clock()  # recepcion de la cotizacion: base de frescura, cuota y fechas

    def _record(resp) -> None:
        # Cada respuesta del proveedor, tambien la que el validador descarta, consume presupuesto.
        cost = budget.estimate_cost_eur(resp.model, resp.usage.input_tokens, resp.usage.output_tokens)
        budget.record(db, resp.model, "llm_proposal", cost, resp.usage.total_tokens)

    def _can_retry() -> None:
        try:
            allowed = budget.can_spend(db, 0.02)
        finally:
            db.commit()  # el SELECT del tope abre transaccion: se libera antes del 2o LLM
        if not allowed:
            raise BudgetExceededError("LLM budget exhausted")

    try:
        proposal = await propose(
            provider, ticker, quote=quote, headlines=headlines, momentum=momentum, thesis=thesis, now=now,
            on_response=_record, before_retry=_can_retry,
        )
    except BudgetExceededError as exc:
        raise ProposalRejected("presupuesto_agotado") from exc
    return save_within_quota(db, proposal, now, thesis_version_id=thesis_version_id)
