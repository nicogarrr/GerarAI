"""USAspending missing observations are not reported zero obligations."""
import pytest

from app.services import money_flows as svc


@pytest.mark.parametrize("bad", [None, "", "bad", True, False, float("nan"), float("inf"), {}, []])
def test_recipient_with_unknown_amount_is_not_zero_or_partial_total(bad):
    rows = svc.aggregate_recipients([{"name": "Example Corp", "amount": 100},
                                     {"name": "Example Inc", "amount": bad}])
    assert rows == [{"name": "Example Corp", "amount": None}]


def test_reported_zero_and_negative_deobligations_remain_real_data():
    assert svc.aggregate_recipients([{"name": "Zero", "amount": 0}, {"name": "Negative", "amount": -25}]) == [
        {"name": "Zero", "amount": 0}, {"name": "Negative", "amount": -25}]


def test_overflowing_recipient_sum_is_unavailable():
    rows = svc.aggregate_recipients([{"name": "Example", "amount": 1e308}, {"name": "Example", "amount": 1e308}])
    assert rows[0]["amount"] is None


@pytest.fixture(autouse=True)
def cache():
    svc._cache.clear()
    yield
    svc._cache.clear()


def test_theme_keeps_missing_rows_but_warns_and_does_not_claim_coverage(monkeypatch):
    monkeypatch.setattr(svc, "fetch_agency_obligations", lambda *args: 1000)
    monkeypatch.setattr(svc, "fetch_top_categories", lambda *args: [{"code": "1510", "amount": None}])
    monkeypatch.setattr(svc, "fetch_top_recipients", lambda *args: [{"name": "EXAMPLE", "amount": None}])
    spenders, destinations, suppliers, _, notes, dest_note, supp_note = svc.build_usaspending_theme(svc.FLOW_THEMES["defensa"])
    assert spenders[0]["amount"] == 1000
    assert destinations[0]["amount"] is None
    assert suppliers[0]["amount"] is None
    assert notes and "sin importe" in " ".join(notes)
    assert dest_note is None and supp_note is None


def test_agency_total_must_be_finite_not_boolean(monkeypatch):
    for bad in [float("nan"), float("inf"), True, None]:
        monkeypatch.setattr(svc, "_usaspending_post", lambda *args: {"results": [{"aggregated_amount": bad}]})
        with pytest.raises(ValueError):
            svc.fetch_agency_obligations("agency", "start", "end")
