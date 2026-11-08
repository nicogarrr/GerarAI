"""La tesis v2 pide respuestas de hasta 24.000 tokens: su llamada al proveedor de la app no puede usar el
plazo general de 120 s por petición (POOL: la parte larga se cortaba a los 120,1 s y la tesis salía en error)."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.config import get_settings
from app.services.expert_team import thesis_v2 as T


def test_reasoner_por_defecto_usa_plazo_largo(monkeypatch):
    seen: dict = {}

    def fake_provider(*args, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr("app.llm.factory.create_llm_provider", fake_provider)
    monkeypatch.setattr(T, "build_context", lambda *a, **k: SimpleNamespace(valuation={"status": "sin_datos"}))
    company = SimpleNamespace(ticker="X", id=1)
    db = SimpleNamespace(info={"tenant_id": 1})
    out = T.generate_thesis_v2(db, company, tenant_id=1)  # type: ignore[arg-type]
    assert out["status"] == "sin_datos"
    assert seen.get("timeout_seconds", 0) >= 600 > get_settings().llm_timeout_seconds
    assert seen.get("total_timeout_seconds", 0) >= seen["timeout_seconds"]


def test_reasoner_de_la_tesis_anota_el_gasto_con_commit(monkeypatch):
    seen: dict = {}
    import app.services.expert_team.service as S

    real = S.provider_reasoner

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr("app.llm.factory.create_llm_provider", lambda *a, **k: object())
    monkeypatch.setattr(S, "provider_reasoner", spy)
    monkeypatch.setattr(T, "build_context", lambda *a, **k: SimpleNamespace(valuation={"status": "sin_datos"}))
    T.generate_thesis_v2(SimpleNamespace(info={}), SimpleNamespace(ticker="X", id=1), tenant_id=1)  # type: ignore[arg-type]
    assert seen.get("commit_usage") is True


def test_no_queda_transaccion_abierta_durante_la_llamada(monkeypatch):
    """Con commit_usage la sesión se confirma tras la consulta de gasto y ANTES de esperar al modelo."""
    import asyncio

    import app.services.expert_team.service as S

    events: list[str] = []

    class FakeBudget:
        def can_spend(self, db, amount):
            events.append("consulta_gasto")
            return True

    class FakeDb:
        def commit(self):
            events.append("commit")

        def flush(self):
            events.append("flush")

    async def fake_guarded(llm, request, **kwargs):
        events.append("llamada")
        return SimpleNamespace(response=SimpleNamespace(text="ok"))

    monkeypatch.setattr("app.services.budget.BudgetController", FakeBudget)
    monkeypatch.setattr("app.services.llm_output_guard.complete_guarded", fake_guarded)
    reason = S.provider_reasoner(object(), db=FakeDb(), commit_usage=True)  # type: ignore[arg-type]
    assert asyncio.run(reason("s", "u", 10, "t")) == "ok"
    assert events[:3] == ["consulta_gasto", "commit", "llamada"]
