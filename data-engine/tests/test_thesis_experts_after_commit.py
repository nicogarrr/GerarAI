"""El equipo de expertos de la tesis corre por defecto tras confirmar la tesis y deja su trabajo a la v2.

Antes (8-nov-2026): EXPERT_TEAM_ENABLED=false por defecto y nunca en las tesis de seguimiento
(stored_evidence_only): 0 llamadas del Recopilador, la mezcla y el escéptico en el lote de 22 tesis.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from app.core.config import Settings, get_settings
from app.services import thesis_service as thesis
from app.services.expert_team import service, thesis_v2_experts


def test_encendido_por_defecto_sin_encender_el_chat():
    s = Settings(_env_file=None)
    assert s.thesis_experts_enabled is True
    assert s.expert_team_enabled is False


def test_tras_confirmar_corre_sin_transaccion_abierta_y_guarda_la_salida(monkeypatch):
    monkeypatch.setattr(get_settings(), "thesis_experts_enabled", True)
    db = SimpleNamespace(commit=Mock(), rollback=Mock())
    order = []

    async def base(system, user, max_tokens, task):
        order.append(("llm", db.commit.call_count))
        return "{}"

    monkeypatch.setattr(service, "provider_reasoner", lambda **kw: base)

    async def run(session, ticker, *, reasoner):
        await reasoner("s", "u", 10, "expert_team.recopilador")
        return {"stages": [{"name": "esceptico", "status": "ok", "beliefs": []}], thesis._SKEPTIC_LABELS: {"x": 1}}

    monkeypatch.setattr(thesis, "_run_thesis_experts", run)
    stored = []
    monkeypatch.setattr(thesis_v2_experts, "store_pipeline", lambda s, cid, p: stored.append((cid, p)))
    import app.services.company_resolver as resolver
    monkeypatch.setattr(resolver, "resolve_company", lambda s, t: SimpleNamespace(id=7))
    out = thesis.run_thesis_experts_after_commit(db, "POOL")
    assert out["stages"][0]["name"] == "esceptico"
    assert order and order[0][1] >= 2  # confirmó la tesis y otra vez justo antes de la llamada
    assert stored == [(7, {"stages": [{"name": "esceptico", "status": "ok", "beliefs": []}]})]


def test_apagado_o_ya_corrido_no_llama_al_modelo(monkeypatch):
    called = Mock()
    monkeypatch.setattr(thesis, "_run_thesis_experts", called)
    monkeypatch.setattr(get_settings(), "thesis_experts_enabled", False)
    assert thesis.run_thesis_experts_after_commit(None, "POOL") is None
    monkeypatch.setattr(get_settings(), "thesis_experts_enabled", True)
    assert thesis.run_thesis_experts_after_commit(None, "POOL", ran_before=True) is None
    called.assert_not_called()


def test_un_plazo_vencido_no_rompe_nada(monkeypatch):
    monkeypatch.setattr(get_settings(), "thesis_experts_enabled", True)
    db = SimpleNamespace(commit=Mock(), rollback=Mock())
    monkeypatch.setattr(service, "provider_reasoner", lambda **kw: None)

    async def slow(session, ticker, *, reasoner):
        raise TimeoutError

    monkeypatch.setattr(thesis, "_run_thesis_experts", slow)
    assert thesis.run_thesis_experts_after_commit(db, "POOL") == {"stages": [], "error": "TimeoutError"}
    db.rollback.assert_called_once()


def test_el_job_lo_llama_antes_de_la_v2():
    import inspect

    from app.services import thesis_job_service

    src = inspect.getsource(thesis_job_service.run_thesis_job)
    assert src.index("run_thesis_experts_after_commit") < src.index("expert_team.thesis_v2 import attach_to_thesis_run")


def test_el_job_de_tesis_tiene_plazo_para_expertos_y_v2():
    """Antes: sin ``time_limit`` Dramatiq cortaba el job a los 10 min por defecto, con la tesis v2 (hasta 600 s)
    y el equipo (hasta 300 s) dentro."""
    from app.services.expert_team import thesis_v2
    from app.workers import dramatiq_app

    limit_s = dramatiq_app.generate_thesis_job.options["time_limit"] / 1000
    assert limit_s >= thesis.AFTER_COMMIT_TIMEOUT_S + thesis_v2.CALL_TIMEOUT_SECONDS + 600
