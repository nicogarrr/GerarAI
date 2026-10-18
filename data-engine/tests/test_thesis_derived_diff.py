"""Diff derivado entre versiones consecutivas cuando no hay ThesisDiff persistido."""
from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.routes.thesis import derived_thesis_diff


def _v(**kw):
    base = dict(rating="expensive", bear_value=100, base_value=200, bull_value=300,
                data_confidence_score=85, source_coverage_score=95, red_team_score=36,
                created_at=datetime(2026, 10, 18, tzinfo=UTC))
    base.update(kw)
    return SimpleNamespace(**base)


def test_first_version_has_no_diff():
    assert derived_thesis_diff(None, _v()) is None


def test_identical_scores_say_so_explicitly():
    d = derived_thesis_diff(_v(), _v())
    assert d["rating_changed"] is False
    assert d["change_summary"].startswith("Sin cambios materiales (±0,5 %)")
    assert d["derived"] is True


def test_sub_threshold_move_declares_the_criterion():
    """base_value +0,3 % no se lista: la frase declara el umbral en vez de afirmar ausencia total."""
    d = derived_thesis_diff(_v(), _v(base_value=200.6))
    assert d["change_summary"].startswith("Sin cambios materiales (±0,5 %)")
    assert d["rating_changed"] is False


def test_changes_are_listed_in_spanish():
    d = derived_thesis_diff(_v(), _v(rating="fair", base_value=210, red_team_score=40))
    assert d["rating_changed"] is True
    s = d["change_summary"]
    assert "cambia la calificación" in s and "escenario base +5,0 %" in s and "red team 36 → 40" in s
