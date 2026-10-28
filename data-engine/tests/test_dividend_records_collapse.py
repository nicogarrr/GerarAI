"""Yahoo reajusta por splits; solo se consolida con evidencia de split. Si no, incierto."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.entities import CorporateAction, DividendRecord
from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.dividend_records import resolve_yahoo_events
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


def test_split_ratio_coincidence_is_not_event_identity_stays_uncertain(db):
    """0.77 -> 0.1925 coincide con un 4:1, pero tambien podria ser ordinario + especial
    (o subcuenta): sin timestamp/version del proveedor no se consolida."""
    company = _company(db)
    _position(db, company, price=100.0)
    ex = date.today() - timedelta(days=60)
    _split(db, company, ex + timedelta(days=10), "4")
    _row(db, company, ex, "0.77", "yahoo_finance", datetime(2026, 1, 1))
    _row(db, company, ex, "0.1925", "yahoo_finance", datetime(2026, 9, 1))
    pos = _yields(db)
    assert pos["dividend_yield"] is None and pos["ttm_dividend_per_share"] is None
    assert len(pos["uncertain_dividend_events"]) == 1
    assert len(db.scalars(select(DividendRecord)).all()) == 2  # nada borrado


def test_ordinary_plus_special_whose_ratio_equals_a_split_is_not_merged(db):
    """Caso reproducido por el auditor: ordinario 0.20 + especial 0.80 (ratio 4) con un 4:1."""
    company = _company(db)
    ex = date.today() - timedelta(days=30)
    _split(db, company, ex + timedelta(days=5), "4")
    rows = [
        _row(db, company, ex, "0.80", "yahoo_finance", datetime(2026, 1, 1)),
        _row(db, company, ex, "0.20", "yahoo_finance", datetime(2026, 1, 1)),
    ]
    kept, uncertain = resolve_yahoo_events(rows)
    assert kept == [] and len(uncertain) == 1


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
    kept, uncertain = resolve_yahoo_events(rows)
    assert len(kept) == 5 and uncertain == []


def test_brain_year_total_excludes_uncertain_instead_of_picking_one(db):
    from app.services.brain_data_tools import _dividend_answer

    db.info["tenant_id"] = 1
    company = _company(db)
    _position(db, company, price=100.0)
    ex = date(date.today().year, 1, 2)
    _split(db, company, ex + timedelta(days=1), "4")
    _row(db, company, ex, "0.77", "yahoo_finance", datetime(2026, 1, 1))
    _row(db, company, ex, "0.1925", "yahoo_finance", datetime(2026, 9, 1))
    answer = _dividend_answer(db, "cuanto voy a cobrar de mi cartera", tenant=1)
    assert "incierto" in answer.answer and company.ticker in answer.answer


def test_cross_provider_unit_rule_groups_by_company_date_and_currency(db):
    from app.services.dividend_records import resolve_cross_provider_events

    company = _company(db)
    ex = date.today() - timedelta(days=30)
    y = _row(db, company, ex, "0.1925", "yahoo_finance", datetime(2026, 9, 1))
    f = _row(db, company, ex, "0.77", "fmp", datetime(2026, 9, 1))
    other_day = _row(db, company, ex - timedelta(days=90), "0.5", "fmp", datetime(2026, 9, 1))
    other_ccy = _row(db, company, ex, "5", "fmp", datetime(2026, 9, 1), "GBX")
    same_src_a = _row(db, company, ex - timedelta(days=200), "0.5", "fmp", datetime(2026, 9, 1))
    same_src_b = _row(db, company, ex - timedelta(days=200), "2", "fmp", datetime(2026, 9, 1))

    kept, uncertain = resolve_cross_provider_events([y, f, other_day, other_ccy, same_src_a, same_src_b])

    assert {r.id for r in kept} == {other_day.id, other_ccy.id, same_src_a.id, same_src_b.id}
    assert [(u.ex_date, u.currency, u.amounts) for u in uncertain] == [
        (ex, "USD", (Decimal("0.1925"), Decimal("0.77")))
    ]


def test_cross_provider_unit_rule_keeps_prior_uncertain_events(db):
    from app.services.dividend_records import resolve_cross_provider_events, resolve_yahoo_events

    company = _company(db)
    ex = date.today() - timedelta(days=30)
    rows = [
        _row(db, company, ex, "0.5", "yahoo_finance", datetime(2026, 1, 1)),
        _row(db, company, ex, "2.0", "yahoo_finance", datetime(2026, 9, 1)),
    ]
    kept, uncertain = resolve_cross_provider_events(*resolve_yahoo_events(rows))
    assert kept == [] and len(uncertain) == 1
