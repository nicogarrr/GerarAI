import pytest

from app.services.expert_team.analyst_blend import _number


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, False, "1", None])
def test_non_finite_or_non_numeric_is_rejected(value):
    assert _number(value) is None

@pytest.mark.parametrize("value", [0, -2, 1.25, 1e300])
def test_finite_number_is_preserved(value):
    assert _number(value) == float(value)
