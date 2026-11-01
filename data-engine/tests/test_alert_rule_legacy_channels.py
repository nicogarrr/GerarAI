"""Legacy alert channels must not make an entire account's rule list fail."""

import pytest

from app.schemas.api import AlertRuleOut


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ["in_app"]),
        (42, ["in_app"]),
        ({"channel": "email"}, ["in_app"]),
        ("email", ["email"]),
        (["push", 1, None, {}], ["push"]),
        ([1, None], ["in_app"]),
        ([], ["in_app"]),
    ],
)
def test_rule_channels_validate_legacy_shapes_without_inventing_external_channel(raw, expected):
    # Exercise Pydantic's actual field validator, not a direct helper call.
    values = dict.fromkeys(AlertRuleOut.model_fields)
    values.update(
        id=1, company_id=1, name="legacy", rule_type="price", condition={},
        target={}, severity="info", channels=raw, active=True,
        cooldown_seconds=0, trigger_count=0, last_result={}, metadata_={},
        created_at="2026-11-01T00:00:00Z", updated_at="2026-11-01T00:00:00Z",
    )
    values.pop("metadata", None)
    assert AlertRuleOut.model_validate(values).channels == expected
