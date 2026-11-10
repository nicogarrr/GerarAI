"""SIC lookup transport seams and real SQLite calibration, no SEC access."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services import sic_classification as sic
from app.services.connectors import form4


def test_lookup_pads_cik_and_uses_shared_sec_transport(monkeypatch):
    request = Mock(return_value=json.dumps({"sic": " 6282 ", "sicDescription": "Investment advice"}))
    monkeypatch.setattr(form4, "_get_text", request)
    assert sic.sec_submissions_sic("60667") == (6282, "Investment advice")
    request.assert_called_once_with("https://data.sec.gov/submissions/CIK0000060667.json", None)


@pytest.mark.parametrize("raw", [{}, {"sic": "bad"}, {"sic": None}])
def test_missing_or_malformed_sic_does_not_invent_classification(raw):
    assert sic.sec_submissions_sic(123, lambda _: json.dumps(raw)) == (None, None)


def test_lookup_transport_and_json_errors_are_unknown():
    fetch = Mock(side_effect=RuntimeError("local failure"))
    assert sic.sec_submissions_sic(123, fetch) == (None, None)
    assert sic.sec_submissions_sic(123, lambda _: "not JSON") == (None, None)
    fetch = Mock(side_effect=AssertionError("invalid CIK must not fetch"))
    assert sic.sec_submissions_sic("not-a-cik", fetch) == (None, None)
    fetch.assert_not_called()


def test_description_missing_and_unknown_range_stay_honest():
    assert sic.sec_submissions_sic(123, lambda _: '{"sic": 9999}') == (9999, None)
    assert sic.classify(9999, None, {}) == {
        "sector": None,
        "sector_source": None,
        "industry": "Sin descripción en la SEC (SIC 9999)",
    }
    assert sic.declared_sector(None) is None
    assert sic.classify(None, "Ignored", {}) == {"sector": None, "sector_source": None, "industry": None}
    assert sic.apply(SimpleNamespace(), None, "Ignored", {}) == {}
    assert sic.sic_from_tags(["sic:bad"]) is None


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def company(ticker, sector, industry, cik=None, tags=None):
    return Company(
        ticker=ticker,
        name=ticker,
        exchange="NYSE",
        sector=sector,
        industry=industry,
        cik=cik,
        currency="USD",
        factor_tags=tags or [],
        company_type="quality",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
    )


def test_fill_uses_real_calibration_preserves_curated_fields_and_tags(db):
    # Alphabetical tie-breaking is deterministic, not row-order dependent.
    known_a = company("ZZZ", "Materials", "Known (SIC 7370)", "3")
    known_b = company("AAA", "Information Technology", "Known (SIC 7370)", "1")
    target = company("BBB", "Unknown", "Unknown", "2", ["curated", "sic:1111"])
    no_cik = company("CCC", "Unknown", "Unknown")
    db.add_all([known_a, known_b, target, no_cik])
    db.commit()
    lookup = Mock(return_value=(7370, "COMPUTER SERVICES"))
    result = sic.fill_from_sic(db, lookup=lookup)
    assert lookup.call_args_list == [(("1",),), (("2",),), (("3",),)]
    assert result["rules"] == sic.RULES_VERSION
    assert result["with_sic"] == 3
    assert result["calibration"] == {"7370": "Information Technology"}
    assert result["changed"]["BBB"] == {
        "industry": "Computer services (SIC 7370)",
        "sector": "Information Technology",
        "sector_source": "sector mayoritario de las fichas de la base con SIC 7370",
        "tag": "sic:7370",
        "sic": 7370,
    }
    assert known_a.sector == "Materials" and known_a.industry == "Known (SIC 7370)"
    assert target.factor_tags == ["curated", "sic:7370"]
    assert no_cik.industry == "Unknown" and "CCC" not in result["changed"]
    db.flush()
    assert not sic.tag_sic(target, 7370)
    again = sic.fill_from_sic(db, companies=[target], lookup=lookup)
    assert again["changed"] == {}


def test_fill_injected_subset_and_unknown_sic_leave_other_rows_untouched(db):
    target = company("AAA", "Unknown", "Unknown", "1")
    ignored = company("BBB", "Unknown", "Unknown", "2")
    db.add_all([target, ignored])
    db.commit()
    lookup = Mock(return_value=(None, None))
    result = sic.fill_from_sic(db, companies=[target], lookup=lookup)
    lookup.assert_called_once_with("1")
    assert result["with_sic"] == 0 and result["changed"] == {}
    assert target.industry == ignored.industry == "Unknown"
