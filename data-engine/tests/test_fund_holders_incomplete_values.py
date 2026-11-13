"""Unknown N-PORT components must not become complete subtotals or zero."""
from datetime import date
from decimal import Decimal

import pytest

from app.services import fund_holders as fh
from app.services.connectors import form_nport_dataset as nport
from tests.test_fund_holders import APPLE, REF, _db, _zip


@pytest.mark.parametrize('missing_first', [False, True])
def test_missing_component_absorbs_value_and_weight_in_either_order(missing_first):
    rows = [f'A1\t9\tApple\t\tCOM\t{APPLE}\t10\tNS\t\tUSD\t\t\t\tLong']
    reports = nport.parse_dataset(_zip(rows), {APPLE})
    rep = reports['A1']
    assert rep.value[APPLE] is None
    assert rep.weight[APPLE] is None
    # Also exercise unknown-before-known, independent of ZIP ordering.
    if missing_first:
        reports = nport.parse_dataset(_zip(rows + [
            f'A1\t10\tApple\t\tCOM\t{APPLE}\t10\tNS\t\tUSD\t500\t\t1\tLong'
        ]), {APPLE})
        assert reports['A1'].value[APPLE] is None
        assert reports['A1'].weight[APPLE] is None


def test_incomplete_value_is_unknown_through_storage_and_public_contract():
    db = _db()
    try:
        reports = nport.parse_dataset(_zip([
            f'A1\t9\tApple\t\tCOM\t{APPLE}\t10\tNS\t\tUSD\t\t\t\tLong'
        ]), {APPLE})
        summary = fh.summarize(nport.latest_by_series(reports), APPLE)
        assert summary['value'] is None
        assert summary['shares'] == 1070
        fh.ingest_reports(db, reports, REF, 'incomplete', fh.universe_cusips(db))
        view = fh.fund_holders(db, 'AAPL')
        assert view['totals']['value_usd'] is None
        assert view['totals']['funds'] == 2
        assert view['totals']['shares'] == 1070
        assert view['top_funds'][0]['value_usd'] is None
        assert view['top_funds'][0]['weight_pct'] is None
        assert any('incomplet' in note.lower() for note in view['limitations'])
    finally:
        db.close()


def test_missing_whole_fund_value_is_not_zero_and_real_zero_is_preserved():
    rep = nport.FundReport('A', date(2026, 8, 20), date(2026, 6, 30), 'NPORT-P',
        shares={APPLE: Decimal(1)})
    assert fh.summarize({'A': rep}, APPLE)['value'] is None
    rep.value[APPLE] = Decimal(0)
    assert fh.summarize({'A': rep}, APPLE)['value'] == 0
    assert fh.summarize({}, APPLE)['value'] == 0


def test_legacy_snapshot_is_marked_unverified_without_changing_its_numbers():
    from app.models.public_market_data import PublicFinancialFact

    db = _db()
    try:
        fh.ingest_reports(db, nport.parse_dataset(_zip(), {APPLE}), REF, 'legacy', fh.universe_cusips(db))
        assert not any('previo' in note for note in fh.fund_holders(db, 'AAPL')['limitations'])
        for fact in db.query(PublicFinancialFact).all():
            fact.derived_from_refs = [ref for ref in (fact.derived_from_refs or []) if ref != fh.INTEGRITY_REF]
        db.commit()
        view = fh.fund_holders(db, 'AAPL')
        assert view['totals']['value_usd'] == 212000
        assert any('no verificada hasta recalcular' in note for note in view['limitations'])
    finally:
        db.close()
