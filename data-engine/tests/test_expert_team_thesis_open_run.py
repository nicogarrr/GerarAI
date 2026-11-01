"""GET /thesis/{ticker}/experts?run=N: abrir entera una corrida anterior.

El historial de la pantalla de la tesis solo daba el resumen de cada corrida
anterior (fecha, veredicto, quién respondió). Ahora ``?run=N`` devuelve esa
corrida COMPLETA (secciones, fuentes, choques, veredicto) con ``is_latest``
a false, y en ``history`` las demás corridas (incluida la última, para
volver). Solo lectura y solo las corridas del propio tenant, del mismo ticker
y completadas: cualquier otra cosa es 404, igual que una que no existe.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.thesis import latest_expert_thesis
from tests.test_expert_team_thesis_history import db, flag_on  # noqa: F401 — fixtures compartidas


def test_open_an_earlier_run_in_full(db):
    out = latest_expert_thesis("MSFT", db, run=1)
    assert out is not None and out.run_id == 1 and out.is_latest is False
    assert [s.expert for s in out.sections] == ["fundamental", "valuation", "news"]
    valuation = next(s for s in out.sections if s.expert == "valuation")
    assert [c.text for c in valuation.claims] == ["PER 30"]  # la corrida 1 sí tenía valoración
    assert out.verdict is not None and out.verdict.label == "en contra"
    assert [s.n for s in out.sources] == [1]
    # el historial deja volver a la última y no repite la abierta
    assert [h.run_id for h in out.history] == [6, 2]


def test_latest_is_marked_latest(db):
    out = latest_expert_thesis("MSFT", db)
    assert out is not None and out.run_id == 6 and out.is_latest is True
    same = latest_expert_thesis("MSFT", db, run=6)
    assert same is not None and same.is_latest is True and [h.run_id for h in same.history] == [2, 1]


@pytest.mark.parametrize(
    "run_id",
    [
        3,  # fallida
        4,  # de otro tenant
        5,  # de otro ticker
        999,  # no existe
    ],
)
def test_other_runs_are_404(db, run_id):
    with pytest.raises(HTTPException) as exc:
        latest_expert_thesis("MSFT", db, run=run_id)
    assert exc.value.status_code == 404


def test_other_tenant_run_is_404_even_without_orm_filter(db):
    """Segunda capa: el tenant grabado en la corrida también tiene que ser el tuyo."""
    from app.models.entities import WorkflowRun

    run = db.get(WorkflowRun, 1)
    run.result_payload = {
        **run.result_payload,
        "result": {**run.result_payload["result"], "context": {"tenant_id": 2}},
    }
    db.commit()
    with pytest.raises(HTTPException) as exc:
        latest_expert_thesis("MSFT", db, run=1)
    assert exc.value.status_code == 404


def test_flag_off_is_404(db, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("EXPERT_TEAM_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        latest_expert_thesis("MSFT", db, run=1)
    assert exc.value.status_code == 404
