"""New means prior 13F exists without this CUSIP, never missing-prior."""
from datetime import date
from decimal import Decimal

from app.services import institutional_holders as ih
from app.services.connectors import form13f_dataset as ds
from tests.test_institutional_holders import APPLE, OTHER, _db, _info, _zip


def parsed_pair():
    prev = _zip([f'P{i}\t15-MAY-2026\t13F-HR\t{i}\t31-MAR-2026' for i in range(1, 15)], [],
                [_info(f'P{i}', OTHER, 1) for i in range(1, 15)])
    subs = [f'C{i}\t15-AUG-2026\t13F-HR\t{i}\t30-JUN-2026' for i in range(1, 16)]
    infos = [_info(f'C{i}', APPLE, i).replace('\t1\t'+str(i)+'\tSH', '\t'+str(1000-i*10)+'\t'+str(i)+'\tSH')
             for i in range(1, 16)]
    now = _zip(subs, [], infos)
    return [ds.parse_dataset(now, {APPLE}, url='https://www.sec.gov/current.zip'),
            ds.parse_dataset(prev, {APPLE}, url='https://www.sec.gov/prior.zip')]


def test_new_lists_are_not_filtered_from_top_buyers_and_have_reported_value():
    parses = parsed_pair()
    periods, _ = ds.resolve_periods(parses)
    summary = ih.summarize(periods, APPLE, date(2026, 6, 30), date(2026, 3, 31))
    # cik15 has no previous filing, so NOT a newly opened position.
    assert summary['totals']['nuevo'] == 14
    assert [r.cik for r in summary['new_by_shares']] == [str(i).zfill(10) for i in range(14, 4, -1)]
    assert [r.cik for r in summary['new_by_value']] == [str(i).zfill(10) for i in range(1, 11)]
    with _db() as db:
        ih.ingest_parsed(db, parses, ['new', 'old'], ih.universe_cusips(db))
        out = ih.institutional_holders(db, 'aapl')['new_positions']
        assert out['count'] == 14 and out['value_known_count'] == 14
        assert out['status'] == 'ok'
        assert out['top_by_shares'][0]['shares'] == 14
        assert out['top_by_value'][0]['value_usd'] == 990
        assert out['top_by_value'][0]['accession'] == 'C1'
        assert len(out['top_by_shares']) == len(out['top_by_value']) == 10


def test_parser_value_units_missing_values_and_new_holdings():
    src = _zip(['OLD\t01-JAN-2023\t13F-HR\t1\t30-SEP-2022',
                'NEW\t03-JAN-2023\t13F-HR\t2\t31-DEC-2022',
                'ADD\t04-JAN-2023\t13F-HR/A\t2\t31-DEC-2022'],
               ['ADD\t31-DEC-2022\tY\t1\tNEW HOLDINGS\tTwo'],
               [_info('OLD', APPLE, 10), _info('NEW', APPLE, 10), _info('ADD', APPLE, 10)])
    p = ds.parse_dataset(src, {APPLE})
    assert p.filings['OLD'].values_usd[APPLE] == Decimal(1000)
    assert p.filings['NEW'].values_usd[APPLE] == Decimal(1)
    periods, _ = ds.resolve_periods([p])
    assert periods[date(2022, 12, 31)]['0000000002'].values_usd[APPLE] == Decimal(2)
    bad = _zip(['BAD\t15-AUG-2026\t13F-HR\t3\t30-JUN-2026'], [],
               [_info('BAD', APPLE, 10).replace('\t1\t10\tSH', '\t\t10\tSH'), _info('BAD', APPLE, 20)])
    assert ds.parse_dataset(bad, {APPLE}).filings['BAD'].values_usd[APPLE] is None


def test_legacy_snapshot_never_claims_empty_new_positions():
    with _db() as db:
        parses = parsed_pair()
        periods, _ = ds.resolve_periods(parses)
        summary = ih.summarize(periods, APPLE, date(2026, 6, 30), date(2026, 3, 31))
        # Simulate persisted pre-feature summary: only top/buyers/sellers.
        summary.pop('new_by_shares')
        summary.pop('new_by_value')
        summary.pop('new_value_known_count')
        ih.persist(db, db.query(ih.Company).filter_by(ticker='AAPL').one(), summary, cusip=APPLE,
                   dataset_url=parses[0].url, prior_url=parses[1].url, checksum='legacy')
        db.commit()
        out = ih.institutional_holders(db, 'AAPL')['new_positions']
        assert out['status'] == 'sin_detalle' and out['count'] == 14
        assert out['top_by_shares'] == out['top_by_value'] == []
        assert out['value_known_count'] is None


def test_missing_value_is_not_ranked_and_reads_only_stored_data():
    from sqlalchemy import event

    from app.api.routes.ownership import institutional_holders_route
    parses = parsed_pair()
    # An incomplete dollar value must not be rescued from shares or price.
    parses[0].filings['C1'].values_usd[APPLE] = None
    with _db() as db:
        ih.ingest_parsed(db, parses, ['new', 'old'], ih.universe_cusips(db))
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.bind, 'before_cursor_execute', record)
        try:
            out = institutional_holders_route('AAPL', db=db)['new_positions']
        finally:
            event.remove(db.bind, 'before_cursor_execute', record)
        assert out['status'] == 'valor_parcial'
        assert out['count'] == 14 and out['value_known_count'] == 13
        assert out['top_by_value'][0]['cik'] == '0000000002'
        assert len(statements) == 4  # company, reference, linked document, facts
        assert all('SELECT' in statement.upper() for statement in statements)
        assert out['top_by_value'][0]['prev_filing_url'] is not None
        assert len(out['top_by_value'][0]['value_filing_urls']) == 1


def test_zero_new_is_known_but_missing_snapshot_is_unknown():
    parses = parsed_pair()
    with _db() as db:
        assert ih.institutional_holders(db, 'AAPL')['new_positions']['count'] is None
        periods, _ = ds.resolve_periods(parses)
        summary = ih.summarize(periods, OTHER, date(2026, 6, 30), date(2026, 3, 31))
        assert summary['totals']['nuevo'] == 0
        ih.persist(db, db.query(ih.Company).filter_by(ticker='AAPL').one(), summary, cusip=APPLE,
                   dataset_url=parses[0].url, prior_url=parses[1].url, checksum='zero')
        db.commit()
        out = ih.institutional_holders(db, 'AAPL')['new_positions']
        assert out['status'] == 'ok' and out['count'] == out['value_known_count'] == 0
        assert out['top_by_shares'] == out['top_by_value'] == []


def test_nonfinite_and_negative_reported_values_are_unknown():
    for raw in ['NaN', 'Infinity', '-1', 'bad']:
        src = _zip(['BAD\t15-AUG-2026\t13F-HR\t3\t30-JUN-2026'], [],
                   [_info('BAD', APPLE, 10).replace('\t1\t10\tSH', f'\t{raw}\t10\tSH')])
        assert ds.parse_dataset(src, {APPLE}).filings['BAD'].values_usd[APPLE] is None


def test_additive_facts_remain_readable_by_legacy_role_and_current_metric_loop():
    from app.models.public_market_data import PublicFinancialFact
    with _db() as db:
        ih.ingest_parsed(db, parsed_pair(), ['new', 'old'], ih.universe_cusips(db))
        rows = db.query(PublicFinancialFact).order_by(PublicFinancialFact.id).all()
        # Freeze old reader's role and cur/prev interpretation. An unknown
        # role would KeyError; a dollar value after shares would corrupt cur.
        roles = {'top': [], 'buyers': [], 'sellers': []}
        holders = {}
        for fact in rows:
            if fact.concept_name == ih.TOTAL:
                continue
            h = holders.setdefault(fact.concept_name, {'tags': fact.derived_from_refs})
            h['prev' if fact.metric == '13f.holder.prev_shares' else 'cur'] = fact
        for name, holder in holders.items():
            assert holder['cur'].unit == 'shares'
            for tag in holder['tags']:
                if tag.startswith('role:'):
                    roles[tag.split(':', 1)[1]].append(name)
        assert len(roles['top']) == len(roles['buyers']) == 10
