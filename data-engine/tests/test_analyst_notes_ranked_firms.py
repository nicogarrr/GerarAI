"""Ramas residuales de analyst_notes.py: ranked_firms con top vacio y
build_view sin ninguna nota (status se queda en 'empty')."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.analyst_history_service as ahs
from app.api.routes.analyst_notes import build_view, ranked_firms
from app.models.entities import Base


def _score(firm: str = "TopHouse") -> ahs.FirmScore:
    return ahs.FirmScore(
        firm=firm,
        samples=8,
        median_abs_error_pct=1.0,
        median_bias_pct=1.0,
        direction_hit_rate=0.7,
        relative_error=-1.0,
        peer_scored_samples=8,
        last_date="2026-10-01",
        last_target=250.0,
    )


def _history(top_12m, top_6m) -> ahs.AnalystHistory:
    return ahs.AnalystHistory(
        symbol="AAA",
        status="available",
        fetched_at=0,
        best_horizon="12m",
        horizons=[
            ahs.HorizonSummary(horizon="6m", months=6, matured_targets=3, top=top_6m),
            ahs.HorizonSummary(horizon="12m", months=12, matured_targets=30, top=top_12m),
        ],
    )


def test_ranked_firms_salta_un_horizonte_sin_top():
    horizon, top = ranked_firms(_history(top_12m=[], top_6m=[_score()]))
    assert horizon == "6m"
    assert [s.firm for s in top] == ["TopHouse"]


def test_ranked_firms_sin_ningun_top_devuelve_vacio():
    assert ranked_firms(_history(top_12m=[], top_6m=[])) == (None, [])


def test_build_view_sin_notas_se_queda_en_empty():
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    view = build_view(db, 1, "AAA", None, per_firm=2, others=3)
    assert view.status == "empty"
    assert view.notes == []
    assert view.other_notes == []
