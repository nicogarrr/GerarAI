"""Chat «mi plan de aportación»: el reparto objetivo respeta los puntos de la etiqueta.

Antes la línea entera pasaba por ``.replace(".", ",")`` para poner la coma
decimal del porcentaje, y con ella la etiqueta: «EE.UU.» salía «EE,UU,» y
«BRK.B» salía «BRK,B». Ahora la coma decimal solo toca el número.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, InvestmentPlan, Portfolio
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el plan no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 1))


def _ask(targets):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.add(Portfolio(tenant_id=1, name="Principal", base_currency="EUR"))
    db.add(InvestmentPlan(tenant_id=1, monthly_contribution=Decimal("300"), monthly_contribution_currency="EUR",
                          start_date=date(2026, 6, 1), horizon_years=20, target_allocations=targets))
    db.commit()
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, "¿Cuál es mi plan de aportación?", "global", None))


def test_label_dots_are_kept():
    resp = _ask([{"kind": "region", "label": "EE.UU.", "target_pct": 62.5},
                 {"kind": "ticker", "label": "BRK.B", "target_pct": 37.5}])
    assert resp.llm_trace.get("path") == "account_plan"
    assert "Reparto objetivo: EE.UU. 62,5 %, BRK.B 37,5 %." in resp.answer


def test_whole_percentages_unchanged():
    resp = _ask([{"kind": "ticker", "label": "MSFT", "target_pct": 60},
                 {"kind": "ticker", "label": "KO", "target_pct": 40}])
    assert "Reparto objetivo: MSFT 60 %, KO 40 %." in resp.answer
