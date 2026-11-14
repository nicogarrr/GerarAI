"""An explicit unknown flag outranks a contradictory numeric total."""
import asyncio
from datetime import date

import pytest
from sqlalchemy import select

from app.models import InsiderTransaction
from app.services.connectors.uk_pdmr_tracefour import map_entry
from app.services.insider_feed import build_feed
from app.services.uk_pdmr_ingestion import ingest_uk_pdmr
from tests.test_uk_pdmr_ingestion import RECORDED, _client_with, db  # noqa: F401


@pytest.mark.parametrize('flag', [False, None, 'true', 1])
def test_only_boolean_true_changes_the_amount(flag):
    entry = {**RECORDED['data'][0], 'valueUnknown': flag}
    result = map_entry(entry)
    assert result['value'] == entry['totalValue']


def test_explicit_unknown_preserves_other_fields_without_inferring_total():
    entry = {**RECORDED['data'][0], 'valueUnknown': True}
    known = map_entry({**entry, 'valueUnknown': False})
    result = map_entry(entry)
    assert result == {**known, 'value': None, 'value_unknown': True}
    assert result['shares'] and result['price']  # never multiply them to fill the total


def test_unknown_amount_stays_missing_in_persistence_and_feed(db):
    entry = {**RECORDED['data'][0], 'valueUnknown': True}
    result = asyncio.run(ingest_uk_pdmr(db, 1, client=_client_with([entry])))
    assert result['saved'] == 1
    stored = db.scalar(select(InsiderTransaction))
    assert stored.value is None
    assert stored.data_quality['value_unknown'] is True
    feed = build_feed(db, days=365, today=date(2026, 10, 20))
    assert feed['transactions'][0]['value'] is None
    assert feed['transactions'][0]['currency'] == 'GBP'
