"""Own-consensus check failures must be visible, never silent or partly successful."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.services import analyst_consensus, estimate_base_rates
from app.services import own_consensus as svc


@pytest.fixture
def inputs(monkeypatch):
    monkeypatch.setattr(analyst_consensus, "history_for", lambda *a: [])
    monkeypatch.setattr(analyst_consensus, "reported_revenue", lambda *a: [])
    monkeypatch.setattr(svc, "_guidance_rows", lambda *a, **kw: [])
    monkeypatch.setattr(svc, "_facts", lambda *a: [])
    monkeypatch.setattr(svc, "_revenue_in_usd", lambda *a: True)
    monkeypatch.setattr(estimate_base_rates, "sector_of_cik", lambda *a: "test")
    cells = {}

    def build(metric, *a, **kw):
        result = {}
        for period, status in [("fy2027", "estimado"), ("fy2026", "vencido"), ("q1_2027", "estimado")]:
            result[period] = svc.Cell(metric, period, date(2027, 12, 31), status, None, [], [], {})
        cells[metric] = result
        return result

    monkeypatch.setattr(svc, "build_cells", build)
    return cells


def run():
    return svc.build_company_consensus(None, SimpleNamespace(ticker="TEST", cik=None), 1,
                                       today=date(2026, 11, 10), base_rate_for=lambda a: None,
                                       measured_errors={})


@pytest.mark.parametrize("function,metric", [("attach_base_rate_checks", "revenue"), ("attach_margin_checks", "operating_income")])
def test_failed_check_is_logged_and_marked_nd_even_after_partial_work(inputs, monkeypatch, caplog, function, metric):
    def fail(cells, *a):
        cells["fy2027"].base_rate_check = {"share": 1.0, "reason": "partial"}
        raise ValueError("invalid external table detail")

    monkeypatch.setattr(svc, function, fail)
    monkeypatch.setattr(svc, "attach_base_rate_checks" if function == "attach_margin_checks" else "attach_margin_checks", lambda *a: None)
    report = run()
    annual = next(c for c in report["cells"] if c["metric"] == metric and c["period"] == "fy2027")
    assert annual["base_rate_check"]["share"] is None
    assert annual["base_rate_check"]["reason"] == "tasa base no disponible: fallo al comprobar la tabla"
    assert any(metric in record.getMessage() and (record.exc_info or record.exc_text) for record in caplog.records)
    assert all(c["base_rate_check"] is None for c in report["cells"] if c["metric"] == metric and c["period"] != "fy2027")
    assert "invalid external table detail" not in str(report)


def test_non_usd_marks_nd_without_attempt_or_spurious_exception(inputs, monkeypatch, caplog):
    monkeypatch.setattr(svc, "_revenue_in_usd", lambda *a: False)

    def forbidden(*a):
        pytest.fail("non-USD must not try a dollar-sized cohort")

    monkeypatch.setattr(svc, "attach_base_rate_checks", forbidden)
    monkeypatch.setattr(svc, "attach_margin_checks", forbidden)
    report = run()
    for cell in report["cells"]:
        check = cell["base_rate_check"]
        if cell["metric"] in ("revenue", "operating_income") and cell["period"] == "fy2027":
            assert check["share"] is None and "otra divisa" in check["reason"]
        else:
            assert check is None
    assert not caplog.records


def test_success_keeps_checks_and_no_failure_warning(inputs, monkeypatch, caplog):
    def attach(cells, *a):
        cells["fy2027"].base_rate_check = {"share": 0.25, "reason": "verified synthetic"}

    monkeypatch.setattr(svc, "attach_base_rate_checks", attach)
    monkeypatch.setattr(svc, "attach_margin_checks", attach)
    report = run()
    checks = [c["base_rate_check"] for c in report["cells"] if c["base_rate_check"]]
    assert checks == [{"share": 0.25, "reason": "verified synthetic"}] * 2
    assert not caplog.records
