"""Data-quality reads diagnostics, not full historical valuation objects."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Portfolio, PortfolioDailySnapshot
from app.services.portfolio_quality_service import portfolio_quality


def test_snapshot_diagnostics_do_not_hydrate_history_or_load_unused_money():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            portfolio = Portfolio(name='quality-budget', base_currency='EUR', is_default=True)
            db.add(portfolio)
            db.flush()
            for i in range(730):
                db.add(PortfolioDailySnapshot(portfolio_id=portfolio.id,
                    snapshot_date=date(2024, 1, 1) + timedelta(days=i), base_currency='EUR',
                    positions_value_base=1000, cash_value_base=0, total_value_base=1000,
                    pricing_coverage=Decimal('1'), daily_return=None if i == 0 else Decimal('.01'),
                    cumulative_twr=None if i == 0 else Decimal('.01'),
                    metadata_={'unused_blob': 'x' * 1000}))
            db.commit()
            db.expunge_all()
            loads = []
            queries = []
            def loaded(_session, row):
                if isinstance(row, PortfolioDailySnapshot):
                    loads.append(row)
            def query(_conn, _cursor, sql, *_args):
                if 'FROM portfolio_daily_snapshots' in sql:
                    queries.append(sql)
            event.listen(db, 'loaded_as_persistent', loaded)
            event.listen(engine, 'before_cursor_execute', query)
            try:
                result = portfolio_quality(db)
            finally:
                event.remove(db, 'loaded_as_persistent', loaded)
                event.remove(engine, 'before_cursor_execute', query)
            assert result['snapshots'] == result['complete_snapshots'] == 730
            assert result['return_observations'] == 729
            assert result['twr_chain'] == {'status': 'linked', 'unlinked_snapshots': 0, 'first_unlinked_date': None}
            assert not loads, f'loaded {len(loads)} full snapshot objects'
            assert len(queries) == 1
            assert 'positions_value_base' not in queries[0]
    finally:
        engine.dispose()


def test_projection_matches_previous_service_for_json_flags_and_broken_chains():
    def reference(db, portfolio):
        snapshots = list(db.scalars(select(PortfolioDailySnapshot).where(
            PortfolioDailySnapshot.portfolio_id == portfolio.id,
        ).order_by(PortfolioDailySnapshot.snapshot_date)))
        complete = [s for s in snapshots if s.pricing_coverage == Decimal("1")]
        returns = [s for s in snapshots if s.daily_return is not None
                   and s.cumulative_twr is not None and s.pricing_coverage == Decimal("1")]
        unlinked = [s for s in snapshots[1:]
                    if (s.daily_return is None or s.cumulative_twr is None)
                    and not (s.metadata_ or {}).get("twr_base_after_scope_change")]
        return {
            "snapshots": len(snapshots), "complete_snapshots": len(complete),
            "return_observations": len(returns),
            "latest_snapshot_date": snapshots[-1].snapshot_date.isoformat() if snapshots else None,
            "latest_pricing_coverage": float(snapshots[-1].pricing_coverage) if snapshots else None,
            "twr_chain": {
                "status": "no_snapshots" if not snapshots else "broken" if unlinked else "linked",
                "unlinked_snapshots": len(unlinked),
                "first_unlinked_date": unlinked[0].snapshot_date.isoformat() if unlinked else None,
            },
        }

    def check(db, portfolio):
        expected = reference(db, portfolio)
        result = portfolio_quality(db)
        assert {key: result[key] for key in expected} == expected
        assert ('twr_chain_broken' in result['reasons']) == (expected['twr_chain']['status'] == 'broken')
        assert ('insufficient_verified_returns' in result['reasons']) == (expected['return_observations'] < 2)
        assert ('latest_snapshot_incomplete' in result['reasons']) == (
            expected['snapshots'] > 0 and expected['latest_pricing_coverage'] != 1)
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            portfolio = Portfolio(name='quality-parity', base_currency='EUR', is_default=True)
            db.add(portfolio)
            db.flush()
            check(db, portfolio)
            flags = [None, False, True, 0, 1, '', 'false', [], [1], {}, {'x': 1}]
            for i, flag in enumerate(flags):
                db.add(PortfolioDailySnapshot(portfolio_id=portfolio.id,
                    snapshot_date=date(2024, 1, 1) + timedelta(days=i), base_currency='EUR',
                    positions_value_base=1000, cash_value_base=0, total_value_base=1000,
                    pricing_coverage=Decimal('1') if i % 3 else Decimal('.5'),
                    daily_return=Decimal('0') if i % 2 else None,
                    cumulative_twr=None if i % 4 else Decimal('0'),
                    metadata_={'twr_base_after_scope_change': flag}))
                db.flush()
                check(db, portfolio)
    finally:
        engine.dispose()


def test_projected_snapshots_remain_tenant_scoped():
    from app.models import Tenant
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            tenants = [Tenant(external_id=f'quality-projection-{i}', name=str(i)) for i in range(2)]
            db.add_all(tenants)
            db.flush()
            ids = [tenant.id for tenant in tenants]
            for tenant_id, count in zip(ids, (2, 5), strict=True):
                db.info['tenant_id'] = tenant_id
                portfolio = Portfolio(name='tenant', base_currency='EUR', is_default=True)
                db.add(portfolio)
                db.flush()
                for i in range(count):
                    db.add(PortfolioDailySnapshot(portfolio_id=portfolio.id,
                        snapshot_date=date(2024, 1, 1) + timedelta(days=i), base_currency='EUR',
                        positions_value_base=1000, cash_value_base=0, total_value_base=1000,
                        pricing_coverage=Decimal('1')))
                db.commit()
            for tenant_id, count in zip(ids, (2, 5), strict=True):
                db.info['tenant_id'] = tenant_id
                assert portfolio_quality(db)['snapshots'] == count
    finally:
        engine.dispose()
