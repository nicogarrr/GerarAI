"""Fuera la función de satélites/órbitas de ASTS (orden de Nico, 12-nov).

Nico: «Quita esa funcion no aporta». La función era solo de ASTS: conector
CelesTrak (GP + SupGP), catálogo y órbitas guardados, lectura generativa del
catálogo y las rutas /api/market/asts/*. ASTS sigue siendo una empresa normal
(ficha, valoración, SOTP); solo desaparece lo orbital.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.workers import scheduler as sched

ROOT = Path(__file__).resolve().parents[1]


def test_la_app_no_expone_rutas_de_satelites_asts():
    import main

    rutas = list(main.app.openapi()["paths"])
    assert any(r.startswith("/api/market/") for r in rutas), "la app no expone rutas de mercado"
    assert not [r for r in rutas if "/market/asts" in r]


def test_openapi_sin_rutas_asts():
    spec = json.loads((ROOT / "openapi.json").read_text())
    assert not [p for p in spec["paths"] if "/market/asts" in p]


@pytest.mark.parametrize(
    "modulo",
    [
        "app.api.routes.asts",
        "app.services.asts_catalog_service",
        "app.services.asts_orbit_service",
        "app.services.asts_llm_service",
        "app.services.connectors.celestrak_ast",
        "app.services.connectors.celestrak_ast_supgp",
    ],
)
def test_modulos_de_la_funcion_ya_no_existen(modulo):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(modulo)


def test_scheduler_no_descarga_celestrak(monkeypatch):
    seen: dict[str, Any] = {}
    orig = sched._register

    def spy(scheduler, func, trigger, *, job_id, **kw):
        orig(scheduler, func, trigger, job_id=job_id, **kw)
        seen[job_id] = func

    monkeypatch.setattr(sched, "_register", spy)
    sched.build_scheduler(background=True)
    assert seen, "el scheduler no registró ningún job"
    assert "asts_celestrak_refresh" not in seen


def test_sin_actor_ni_cola_ni_fuente_ni_prompt_orbital():
    from app.services.data_source_health import get_data_source_registry
    from app.services.prompt_registry import PROMPTS
    from app.workers import dramatiq_app
    from app.workers.queue_taxonomy import ACTOR_CLASS

    assert not hasattr(dramatiq_app, "refresh_asts_catalog")
    assert "refresh_asts_catalog" not in ACTOR_CLASS
    assert "celestrak" not in get_data_source_registry().sources
    assert "asts_llm_service" not in PROMPTS
