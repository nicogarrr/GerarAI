from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import select

from app.models.entities import ValuationModel
from tests.test_snapshot_derived_net_debt import _company, db  # noqa: F401

_spec = importlib.util.spec_from_file_location(
    "recompute_valuation_models",
    Path(__file__).resolve().parent.parent / "scripts" / "recompute_valuation_models.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_recompute_persists_a_new_model_version_without_llm(db):
    c = _company(db)
    first = _mod.recompute_company(db, c)
    second = _mod.recompute_company(db, c)
    versions = db.scalars(
        select(ValuationModel.version).where(ValuationModel.company_id == c.id).order_by(ValuationModel.version)
    ).all()
    assert versions == [1, 2]
    assert first["status"] in {"insufficient_data", "draft", "final"}
    assert second["ticker"] == c.ticker
