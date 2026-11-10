"""SEC JSON must be an object before SIC fields can be read."""

import json

import pytest

from app.services.sic_classification import sec_submissions_sic


@pytest.mark.parametrize("value", [None, [], [{"sic": 6282}], "text", "6282", 6282, 0, 1.25, True, False])
def test_valid_non_object_json_never_raises_or_supplies_sic(value):
    assert sec_submissions_sic("123", lambda _: json.dumps(value)) == (None, None)


@pytest.mark.parametrize("sic", [6282, "6282"])
def test_object_json_still_returns_its_declared_sic(sic):
    payload = {"sic": sic, "sicDescription": "Investment advice"}
    assert sec_submissions_sic("123", lambda _: json.dumps(payload)) == (6282, "Investment advice")
