"""Puente del equipo de expertos con la app: LLM real, presupuesto y contexto.

Solo se usa con ``EXPERT_TEAM_ENABLED`` encendido. El LLM es el proveedor
único de la app (``create_llm_provider``); cada llamada pasa el control de
salida (idioma/tokens rotos, un reintento) y gasta presupuesto del tenant como
el debate de tesis: sin saldo no hay llamada y el experto queda en ``error``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Company, Position
from app.services.expert_team.coordinator import ExpertTeam
from app.services.expert_team.experts import Reasoner
from app.services.expert_team.models import Mode, RunContext, TeamResult
from app.services.expert_team.roster import default_experts
from app.services.expert_team.tools import build_tools

#: Coste estimado reservado antes de cada llamada (mismo criterio que el debate).
SPEND_PER_CALL_EUR = 0.02


def provider_reasoner(provider: Any | None = None, *, db: Session | None = None) -> Reasoner:
    async def reason(system: str, user: str, max_tokens: int, task: str) -> str:
        from app.core.i18n import current_language
        from app.llm import LLMRequest, Message
        from app.services.budget import BudgetController, BudgetExceededError
        from app.services.llm_output_guard import complete_guarded

        llm = provider
        if llm is None:
            from app.llm.factory import create_llm_provider

            llm = create_llm_provider()
        budget = BudgetController() if db is not None else None
        if budget is not None and db is not None and not budget.can_spend(db, SPEND_PER_CALL_EUR):
            raise BudgetExceededError("LLM budget exhausted")

        def tally(resp: Any) -> None:
            if budget is None or db is None:
                return
            usage = resp.usage
            model = getattr(resp, "model", None) or "unknown"
            cost = budget.estimate_cost_eur(model, usage.input_tokens, usage.output_tokens)
            budget.record(db, model, task, cost, usage.total_tokens)

        request = LLMRequest(
            messages=[Message("system", system), Message("user", user)],
            task="main_financial_analysis",
            temperature=0.2,
            max_tokens=max_tokens,
            metadata={"expert_team_task": task},
        )
        guarded = await complete_guarded(
            llm, request, source=task, expected_language=current_language(), on_response=tally
        )
        return (guarded.response.text or "").strip()

    return reason


def holds_position(db: Session, tenant_id: int | str | None, ticker: str) -> bool:
    company = db.scalars(select(Company).where(Company.ticker == ticker.strip().upper())).first()
    if company is None:
        return False
    rows = db.scalars(
        select(Position.quantity).where(Position.tenant_id == tenant_id, Position.company_id == company.id)
    ).all()
    return any((q or 0) > 0 for q in rows)


def build_team(db: Session, *, reasoner: Reasoner | None = None, provider: Any | None = None) -> ExpertTeam:
    return ExpertTeam(default_experts(), build_tools(db), reasoner or provider_reasoner(provider, db=db))


def run_context(
    db: Session, *, ticker: str | None, mode: Mode = "thesis", question: str | None = None
) -> RunContext:
    """Contexto de la corrida: tenant y usuario salen de la sesión, nunca del modelo."""
    from app.core.config import get_settings
    from app.core.i18n import current_language

    tenant_id = db.info.get("tenant_id")
    settings = get_settings()
    if tenant_id is None and (settings.research_auth_required or settings.is_production):
        # Igual que tenant_filters: sin tenant y con auth obligatoria, no se lee nada.
        raise RuntimeError("expert team requires a tenant context")
    symbol = (ticker or "").strip().upper() or None
    return RunContext(
        tenant_id=tenant_id,
        user_id=str(db.info.get("user_id") or "") or None,
        ticker=symbol,
        question=question,
        mode=mode,
        lang=current_language(),
        holds_position=symbol is not None and holds_position(db, tenant_id, symbol),
    )


async def run_team(
    db: Session,
    *,
    ticker: str | None,
    mode: Mode = "thesis",
    question: str | None = None,
    reasoner: Reasoner | None = None,
    provider: Any | None = None,
    total_timeout_s: float | None = None,
    judge_timeout_s: float | None = None,
) -> TeamResult:
    ctx = run_context(db, ticker=ticker, mode=mode, question=question)
    team = build_team(db, reasoner=reasoner, provider=provider)
    if total_timeout_s is not None:
        # El chat da menos tiempo que la tesis: el experto que no llegue sale como «timeout».
        team.total_timeout_s = total_timeout_s
    if judge_timeout_s is not None:
        team.judge_timeout_s = judge_timeout_s
    return await team.run(ctx)
