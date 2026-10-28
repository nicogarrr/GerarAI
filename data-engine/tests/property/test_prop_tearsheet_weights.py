"""Pesos de concentracion sobre exposicion bruta: siempre en [0, 1]."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from app.services.tearsheet_service import exposure_from_snapshot

value = st.one_of(st.none(), st.floats(min_value=-1e7, max_value=1e7))


@given(st.lists(value, max_size=12), st.floats(min_value=-1e7, max_value=1e7))
def test_gross_weights_stay_in_unit_interval(values, cash):
    rows = [SimpleNamespace(market_value_base=v) for v in values]
    positions = sum(v for v in values if v is not None)
    snap = SimpleNamespace(
        snapshot_date=date(2026, 1, 2),
        base_currency="EUR",
        total_value_base=positions + cash,
        positions_value_base=positions,
        cash_value_base=cash,
    )
    out = exposure_from_snapshot(snap, rows)
    top1, top5 = out["top_1_gross_positions_weight"], out["top_5_gross_positions_weight"]
    if any(v is None for v in values) or not values:
        # sin todas las valoraciones el denominador bruto no se conoce
        assert top1 is None and top5 is None
        return
    if all(v == 0 for v in values):
        assert top1 is None
        return
    assert 0 <= top1 <= top5 <= 1 + 1e-12
