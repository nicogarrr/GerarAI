"""Pipeline de inputs de la tesis: Recopilador y mezcla de analistas en orden.

Todo hermético: las dos etapas se sustituyen por dobles async; no hay red, LLM
ni base de datos real. Cubre el interruptor, el tenant, el orden, el aislamiento
de fallos por etapa y los estados ok/partial/error.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.i18n import current_language
from app.services.expert_team import pipeline
from app.services.expert_team.pipeline import PipelineInputsResult, run_pipeline_inputs


class FakeDB:
    def __init__(self, tenant_id: Any = 7) -> None:
        self.info = {"tenant_id": tenant_id}


class UntouchableDB:
    @property
    def info(self) -> dict[str, Any]:
        raise AssertionError("la base no se toca con el equipo apagado")


@dataclass
class FakeCompany:
    ticker: str = " synth "


@dataclass
class FakeStageResult:
    status: str
    stored: int = 0


@dataclass
class DatedStageResult:
    status: str
    as_of: date
    amount: Decimal


def _patch_stages(monkeypatch, recopilador, analista) -> None:
    monkeypatch.setattr(pipeline, "run_recopilador", recopilador)
    monkeypatch.setattr(pipeline, "run_analyst_blend", analista)


def test_apagado_no_toca_db_ni_etapas(monkeypatch) -> None:
    called: list[str] = []

    async def recopilador(*args, **kwargs):
        called.append("recopilador")
        return FakeStageResult("stored")

    async def analista(*args, **kwargs):
        called.append("analista")
        return FakeStageResult("stored")

    _patch_stages(monkeypatch, recopilador, analista)

    result = run_pipeline_inputs(UntouchableDB(), FakeCompany(), enabled=False)

    assert result.status == "disabled"
    assert called == []
    assert result.as_dict() == {
        "status": "disabled",
        "recopilador": {},
        "analista": {},
        "errors": [],
    }


def test_apagado_por_defecto_lee_la_config(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline, "get_settings", lambda: SimpleNamespace(expert_team_enabled=False)
    )
    called: list[str] = []

    async def recopilador(*args, **kwargs):
        called.append("recopilador")
        return FakeStageResult("stored")

    async def analista(*args, **kwargs):
        called.append("analista")
        return FakeStageResult("stored")

    _patch_stages(monkeypatch, recopilador, analista)

    result = run_pipeline_inputs(UntouchableDB(), FakeCompany())

    assert result.status == "disabled"
    assert called == []


@pytest.mark.parametrize("tenant", [None, 0, -1, "7", True])
def test_sin_tenant_valido_no_corre_etapas(monkeypatch, tenant) -> None:
    called: list[str] = []

    async def recopilador(*args, **kwargs):
        called.append("recopilador")
        return FakeStageResult("stored")

    async def analista(*args, **kwargs):
        called.append("analista")
        return FakeStageResult("stored")

    _patch_stages(monkeypatch, recopilador, analista)

    result = run_pipeline_inputs(FakeDB(tenant), FakeCompany(), enabled=True)

    assert result.status == "no_tenant"
    assert called == []


def test_recopilador_termina_antes_de_la_mezcla(monkeypatch) -> None:
    order: list[str] = []
    seen: dict[str, dict[str, Any]] = {}
    reasoner = object()

    async def recopilador(db, **kwargs):
        order.append("recopilador")
        seen["recopilador"] = kwargs
        return FakeStageResult("stored", 1)

    async def analista(db, **kwargs):
        order.append("analista")
        seen["analista"] = kwargs
        return FakeStageResult("stored", 2)

    timeouts: list[float | None] = []

    def bridge(coro, timeout=None):
        timeouts.append(timeout)
        return asyncio.run(coro)

    _patch_stages(monkeypatch, recopilador, analista)
    monkeypatch.setattr(pipeline, "run_from_any_context", bridge)

    result = run_pipeline_inputs(
        FakeDB(7),
        FakeCompany(),
        reasoner=reasoner,
        history="historial",
        load_history="cargador",
        extra_sources=("fuente",),
        enabled=True,
        timeout=12.5,
    )

    assert order == ["recopilador", "analista"]
    assert timeouts == [12.5, 12.5]
    recopilador_kwargs = seen["recopilador"]
    ctx = recopilador_kwargs["ctx"]
    assert (ctx.tenant_id, ctx.ticker, ctx.mode) == (7, "SYNTH", "thesis")
    assert ctx.lang == current_language()
    assert recopilador_kwargs["reasoner"] is reasoner
    assert recopilador_kwargs["enabled"] is True
    analista_kwargs = seen["analista"]
    assert analista_kwargs["ctx"] == ctx
    assert analista_kwargs["reasoner"] is reasoner
    assert analista_kwargs["history"] == "historial"
    assert analista_kwargs["load_history"] == "cargador"
    assert analista_kwargs["extra_sources"] == ("fuente",)
    assert analista_kwargs["enabled"] is True
    assert result.status == "ok"
    assert result.recopilador == {"status": "stored", "stored": 1}
    assert result.analista == {"status": "stored", "stored": 2}
    assert result.errors == []


def test_fallo_del_recopilador_no_impide_la_mezcla(monkeypatch) -> None:
    async def recopilador(*args, **kwargs):
        raise RuntimeError("sin datos")

    async def analista(*args, **kwargs):
        return FakeStageResult("stored", 2)

    _patch_stages(monkeypatch, recopilador, analista)

    result = run_pipeline_inputs(FakeDB(), FakeCompany(), reasoner=object(), enabled=True)

    assert result.status == "partial"
    assert result.errors == ["recopilador:RuntimeError"]
    assert result.recopilador == {}
    assert result.analista == {"status": "stored", "stored": 2}


@pytest.mark.parametrize(
    ("recopilador_status", "analista_status", "expected"),
    [
        ("stored", "stored", "ok"),
        ("no_data", "no_data", "ok"),
        ("error", "error", "error"),
        ("error", "stored", "partial"),
        ("stored", "error", "partial"),
    ],
)
def test_estado_agregado(
    monkeypatch, recopilador_status, analista_status, expected
) -> None:
    async def recopilador(*args, **kwargs):
        return FakeStageResult(recopilador_status)

    async def analista(*args, **kwargs):
        return FakeStageResult(analista_status)

    _patch_stages(monkeypatch, recopilador, analista)

    result = run_pipeline_inputs(FakeDB(), FakeCompany(), reasoner=object(), enabled=True)

    assert result.status == expected


def test_resultado_de_etapa_dataclass_se_serializa(monkeypatch) -> None:
    async def recopilador(*args, **kwargs):
        return DatedStageResult("stored", date(2026, 11, 5), Decimal("1.5"))

    async def analista(*args, **kwargs):
        return {"status": "no_data"}

    _patch_stages(monkeypatch, recopilador, analista)

    result = run_pipeline_inputs(FakeDB(), FakeCompany(), reasoner=object(), enabled=True)

    assert result.recopilador == {
        "status": "stored",
        "as_of": "2026-11-05",
        "amount": 1.5,
    }
    assert result.analista == {"status": "no_data"}
    assert json.loads(json.dumps(result.as_dict())) == result.as_dict()


def test_as_dict_incluye_las_cuatro_claves() -> None:
    result = PipelineInputsResult(
        status="partial",
        recopilador={"status": "stored", "drivers": ["a"]},
        analista={"status": "full_data", "gaps": []},
        errors=["recopilador:RuntimeError"],
    )

    payload = result.as_dict()

    assert payload == {
        "status": "partial",
        "recopilador": {"status": "stored", "drivers": ["a"]},
        "analista": {"status": "full_data", "gaps": []},
        "errors": ["recopilador:RuntimeError"],
    }
    assert json.loads(json.dumps(payload)) == payload
