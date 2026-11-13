"""A portfolio with missing position values has no complete total or weights."""
from decimal import Decimal
from types import SimpleNamespace

from app.services import investors as svc
from tests.test_investors_batched import _seed, db  # noqa: F401


def test_missing_component_is_not_zero_and_complete_zero_stays_zero():
    assert svc._total([SimpleNamespace(value_usd_thousands=Decimal(25)),
                       SimpleNamespace(value_usd_thousands=None)]) is None
    assert svc._total([SimpleNamespace(value_usd_thousands=Decimal(0))]) == 0


def test_summary_and_detail_do_not_present_partial_values_as_complete(db):
    _seed(db)
    first = next(inv for inv in svc.INVESTORS if inv.cik in svc.REVIEWED_MANAGERS)
    summary = next(row for row in svc.list_investors(db)['investors'] if row['slug'] == first.slug)
    assert summary['positions'] == 3
    assert summary['value_usd_thousands'] is None
    assert summary['note']
    detail = svc.investor_detail(db, first.slug)
    assert detail['positions'] == 3 and detail['value_usd_thousands'] is None
    assert detail['note']
    assert all(row['weight_pct'] is None for row in detail['holdings'])
