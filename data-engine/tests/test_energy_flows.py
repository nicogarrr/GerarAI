import pytest

from app.services import energy_flows
from app.services.money_flows import FLOW_THEMES


def rows():
    amounts = {"RES": "262079.35817", "COM": "200316.21062", "IND": "89878.15655", "TRA": "1011.10902", "OTH": "0", "ALL": "553284.83436"}
    return [{"period": "2025", "stateid": "US", "sectorid": k, "revenue": v,
             "revenue-units": "million dollars"} for k, v in amounts.items()]


def test_live_response_fixture_units_and_no_double_count():
    year, sectors, total = energy_flows.parse_retail_revenue(rows())
    assert year == "2025"
    assert len(sectors) == 5
    assert total == pytest.approx(553284834360)
    assert sum(r["amount"] for r in sectors) == pytest.approx(total)


@pytest.mark.parametrize("bad", ["NaN", "inf", "-1", "not money"])
def test_invalid_amount_fails_closed(bad):
    data = rows()
    data[0]["revenue"] = bad
    with pytest.raises(ValueError):
        energy_flows.parse_retail_revenue(data)


def test_unit_is_verified_not_assumed():
    data = rows()
    data[0]["revenue-units"] = "million kilowatt hours"
    with pytest.raises(ValueError):
        energy_flows.parse_retail_revenue(data)


def test_missing_duplicate_and_non_reconciling_fail_closed():
    for data in (rows()[:-1], rows() + [rows()[0]]):
        with pytest.raises(ValueError):
            energy_flows.parse_retail_revenue(data)
    data = rows()
    data[-1]["revenue"] = "1"
    with pytest.raises(ValueError):
        energy_flows.parse_retail_revenue(data)


def test_outage_no_fabricated_data_or_secret(monkeypatch):
    def fail():
        raise RuntimeError("private secret must never reach payload")
    monkeypatch.setattr(energy_flows, "load_revenue", fail)
    payload = energy_flows.build_energy_flow(FLOW_THEMES["utilities"])
    assert payload["spenders"] == []
    assert payload["suppliers"] == []
    assert "private secret" not in str(payload)
    assert "N/D" in payload["notes"][0]


def test_success_no_company_allocation(monkeypatch):
    monkeypatch.setattr(energy_flows, "load_revenue", lambda: energy_flows.parse_retail_revenue(rows()))
    payload = energy_flows.build_energy_flow(FLOW_THEMES["utilities"])
    assert payload["spenders_total"]["amount"] == payload["destinations"][0]["amount"]
    assert payload["suppliers"][0]["ticker"] is None
    assert payload["suppliers"][0]["source"]["url"] == energy_flows.SOURCE_URL
    assert "api_key" not in str(payload)
