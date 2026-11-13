"""An existing 13F position with missing shares is not an absent position."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FundManager, ManagerHolding
from app.schemas.api import ManagerChangesOut
from app.services.manager_holding_ingestion_service import (
    ManagerHoldingIngestionService,
    share_change_label,
)


@pytest.mark.parametrize('now,before', [(None, 10), (10, None), (None, None),
                                         ('NaN', 10), (10, 'Infinity'), (-1, 10), (True, 10), ('bad', 10)])
def test_missing_or_invalid_shares_are_unknown(now, before):
    assert share_change_label(SimpleNamespace(shares=now), SimpleNamespace(shares=before)) == 'unknown'


def test_comparison_retains_row_and_warns_without_breaking_contract():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info['tenant_id'] = 'tenant-test'
        manager = FundManager(cik='0001067983', name='Test Manager', coverage='ok')
        db.add(manager)
        db.flush()
        for accession, report, shares in [('a', date(2026, 3, 31), Decimal(10)),
                                          ('b', date(2026, 6, 30), None)]:
            db.add(ManagerHolding(manager_id=manager.id, accession_number=accession,
                report_date=report, filing_date=report, is_amendment=False,
                name_of_issuer='Example', title_of_class='COM', cusip='037833100',
                value_usd_thousands=Decimal(100), shares=shares, share_type='SH', put_call=''))
        db.commit()
        service = ManagerHoldingIngestionService()
        result = service.changes(db, cik=manager.cik)
        row = result['changes'][0]
        assert row['change'] == 'unknown'
        assert row['shares_latest'] is None
        assert row['shares_previous'] == 10
        assert 'incompleta' in row['notice']
        assert any('incompleta' in notice for notice in result['limitations'])
        assert ManagerChangesOut.model_validate(result).changes[0].change == 'unknown'
        assert service.change_labels_for_cusip(db, cik=manager.cik, cusip='037833100') == ['unknown']
        # Existing consumers must not treat the unknown comparison as a buy/sell.
        from app.services.investors import INVESTORS, most_bought
        from app.services.ticker_ownership_signals import _manager_changes_for_cusip
        inv = next(inv for inv in INVESTORS if inv.cik == manager.cik)
        assert most_bought(db)['items'] == []
        assert _manager_changes_for_cusip(db, inv, '037833100') is None
        # Unknown shares are not the same as a real, reported zero.
        latest = next(row for row in db.query(ManagerHolding).all() if row.accession_number == 'b')
        latest.shares = Decimal(0)
        db.commit()
        known = service.changes(db, cik=manager.cik)
        assert known['changes'][0]['change'] == 'decreased'
        assert known['changes'][0]['notice'] is None

