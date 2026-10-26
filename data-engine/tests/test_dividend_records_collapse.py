"""Yahoo reajusta por splits; solo se consolida con evidencia de split. Si no, incierto."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.entities import CorporateAction, DividendRecord
from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.dividend_records import resolve_yahoo_events, split_ratios_for
from tests.test_dividend_ingestion import FakeFMP, FakeYahoo, _company, _position, db  # noqa: F401


def _row(db, company, ex, amount, source, fetched, currency="USD"):
    r = DividendRecord(
        company_id=company.id, ex_date=ex, amount=Decimal(amount), currency=currency,
        source=source, fetched_at=fetched, tenant_id=db.info.get("tenant_id"),
    )
    db.add(r)
    db.commit()
    return r


def _split(db, company, effective, ratio):
    db.add(CorporateAction(
        company_id=company.id, action_type="split", effective_date=effective, ratio=Decimal(ratio),
        source="yahoo_finance", tenant_id=db.info.get("tenant_id"),
    ))
    db.commit()


def _yields(db):
    return DividendIngestionService(fmp=FakeFMP(), yahoo=FakeYahoo()).portfolio_yields(db)["positions"][0]


def test_split_readjustment_with_split_evidence_keeps_latest_only(db):
    company = _company(db)
    _position(db, company, price=100.0)
    ex = date.today() - timedelta(days=60)
    _split(db, company, ex + timedelta(days=10), "4")  # 4:1 posterior a la ex_date
    _row(db, company, ex, "0.77", "yahoo_finance", datetime(2026, 1, 1))
    _row(db, company, ex, "0.1925", "yahoo_finance", datetime(2026, 9, 1))
    pos = _yields(db)
    assert pos["ttm_dividend_per_share"] == 0.1925 and pos["uncertain_dividend_events"] == []
    assert len(db.scalars(select(DividendRecord)).all()) == 2  # nada borrado


def test_different_amounts_without_split_evidence_are_uncertain_not_last_wins(db):
    """Ordinario + especial mismo dia (distinto timestamp): no se elige uno."""
    company = _company(db)
    _position(db, company, price=100.0)
    ex = date.today() - timedelta(days=30)
    _row(db, company, ex, "0.50", "yahoo_finance", datetime(2026, 1, 1))
    _row(db, company, ex, "2.00", "yahoo_finance", datetime(2026, 9, 1))
    pos = _yields(db)
    assert pos["dividend_yield"] is None and pos["ttm_dividend_per_share"] is None
    assert pos["uncertain_dividend_events"] == [{"ex_date": ex.isoformat(), "amounts": ["0.5000000000", "2.0000000000"]}]


def test_split_that_does_not_explain_the_ratio_is_uncertain(db):
    company = _company(db)
    ex = date.today() - timedelta(days=30)
    _split(db, company, ex + timedelta(days=5), "2")  # 2:1 no explica 0.77/0.1925 (=4)
    rows = [
        _row(db, company, ex, "0.77", "yahoo_finance", datetime(2026, 1, 1)),
        _row(db, company, ex, "0.1925", "yahoo_finance", datetime(2026, 9, 1)),
    ]
    kept, uncertain = resolve_yahoo_events(rows, split_ratios_for(db, [company.id]))
    assert kept == [] and len(uncertain) == 1


def test_split_before_ex_date_is_not_evidence(db):
    company = _company(db)
    ex = date.today() - timedelta(days=30)
    _split(db, company, ex - timedelta(days=5), "4")
    rows = [
        _row(db, company, ex, "0.77", "yahoo_finance", datetime(2026, 1, 1)),
        _row(db, company, ex, "0.1925", "yahoo_finance", datetime(2026, 9, 1)),
    ]
    kept, uncertain = resolve_yahoo_events(rows, split_ratios_for(db, [company.id]))
    assert kept == [] and len(uncertain) == 1


def test_other_sources_currencies_and_dates_are_untouched(db):
    company = _company(db)
    ex = date.today() - timedelta(days=30)
    rows = [
        _row(db, company, ex, "0.50", "fmp", datetime(2026, 9, 1)),
        _row(db, company, ex, "2.00", "fmp", datetime(2026, 9, 1)),
        _row(db, company, ex, "1", "yahoo_finance", datetime(2026, 9, 1), "USD"),
        _row(db, company, ex, "1", "yahoo_finance", datetime(2026, 9, 1), "CHF"),
        _row(db, company, ex - timedelta(days=90), "1", "yahoo_finance", datetime(2026, 9, 1)),
    ]
    kept, uncertain = resolve_yahoo_events(rows, {})
    assert len(kept) == 5 and uncertain == []


def test_brain_year_total_uses_evidence_and_flags_uncertain(db):
    from app.services.brain_data_tools import _dividend_answer

    db.info["tenant_id"] = 1
    company = _company(db)
    _position(db, company, price=100.0)
    ex = date(date.today().year, 1, 2)
    _split(db, company, ex + timedelta(days=1), "4")
    _row(db, company, ex, "0.77", "yahoo_finance", datetime(2026, 1, 1))
    _row(db, company, ex, "0.1925", "yahoo_finance", datetime(2026, 9, 1))
    answer = _dividend_answer(db, "cuanto voy a cobrar de mi cartera", tenant=1)
    assert "1 pago(s)" in answer.answer and "$1.93" in answer.answer
    assert "ajustados por splits" in answer.answer
    # sin evidencia de split: excluido y señalado
    db.query(CorporateAction).delete()
    db.commit()
    answer = _dividend_answer(db, "cuanto voy a cobrar de mi cartera", tenant=1)
    assert "dato incierto" in answer.answer and company.ticker in answer.answer
