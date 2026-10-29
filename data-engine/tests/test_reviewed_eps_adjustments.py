from decimal import Decimal

import pytest

from app.models import Document, FinancialFact
from app.services.reviewed_eps_adjustments import (
    REVIEW_ID,
    REVIEWED,
    SOURCE_TYPE,
    is_reviewed_eps_adjustment,
)


def make(lei, period, value):
    url, checksum, page = REVIEWED[(lei, period, Decimal(value))]
    # Modelos ORM reales (transitorios, sin sesión): el gate lee los mismos
    # atributos mapeados que en producción, no un falso SimpleNamespace.
    return FinancialFact(
        source_type=SOURCE_TYPE,
        metric="eps_diluted",
        value=Decimal(value),
        period=period,
        fiscal_year=int(period[:4]),
        fiscal_quarter="FY",
        is_reported=False,
        is_adjusted=True,
        unit="EUR/share",
        company_id=1,
        tenant_id=1,
        source=Document(
            company_id=1,
            tenant_id=1,
            source_type=SOURCE_TYPE,
            source_url=url,
            checksum=checksum,
            metadata_={"lei": lei, "review_id": REVIEW_ID, "pdf_page": page},
        ),
    )


@pytest.mark.parametrize("lei,period,value", list(REVIEWED))
def test_exact_pdf_transcription_eligible_not_official(lei, period, value):
    row = make(lei, period, value)
    assert is_reviewed_eps_adjustment(row)
    assert row.is_reported is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", Decimal("1351")),
        ("is_reported", True),
        ("is_adjusted", False),
        ("unit", "USD/share"),
        ("fiscal_year", 2025),
        ("metric", "shares_diluted"),
        ("source", None),
    ],
)
def test_does_not_allow_arbitrary_manual_or_wrong_period(field, value):
    row = make(*next(iter(REVIEWED)))
    setattr(row, field, value)
    assert not is_reviewed_eps_adjustment(row)


def test_wrong_pdf_hash_rejected():
    row = make(*next(iter(REVIEWED)))
    row.source.checksum = "wrong"
    assert not is_reviewed_eps_adjustment(row)


@pytest.mark.parametrize("field,value", [("tenant_id", 2), ("company_id", 2), ("source_type", "ESEF")])
def test_source_bound_to_same_owner_and_company(field, value):
    row = make(*next(iter(REVIEWED)))
    setattr(row.source, field, value)
    assert not is_reviewed_eps_adjustment(row)


def test_provenance_fields_and_numeric_invalid_fail_closed():
    row = make(*next(iter(REVIEWED)))
    row.source.metadata_["review_id"] = "unreviewed"
    assert not is_reviewed_eps_adjustment(row)
    row = make(*next(iter(REVIEWED)))
    row.value = "not-number"
    assert not is_reviewed_eps_adjustment(row)
    row = make(*next(iter(REVIEWED)))
    row.fiscal_quarter = "Q4"
    assert not is_reviewed_eps_adjustment(row)
    row = make(*next(iter(REVIEWED)))
    row.source.source_url = "https://invalid.example/report.pdf"
    assert not is_reviewed_eps_adjustment(row)


def test_selector_preserves_empty_plain_and_unrelated_issuer():
    from app.services.reviewed_eps_adjustments import select_watchlist_eps

    assert select_watchlist_eps([]) is None
    plain = make(*next(iter(REVIEWED)))
    plain.source_type = "SEC"
    assert select_watchlist_eps([plain]) is plain
    from app.services.esef_fact_quarantine import EBRO_LEI, LOG_LEI

    raw = make(EBRO_LEI, "2024-12-31:FY", "1.351")
    raw.source_type = "ESEF"
    raw.value = Decimal("1351")
    raw.period = "2025-01-01:FY"
    other = make(LOG_LEI, "2025-09-30:FY", "2.13")
    assert select_watchlist_eps([raw, other]) is raw
