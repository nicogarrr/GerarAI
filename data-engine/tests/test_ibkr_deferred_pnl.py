"""IBKR may return a successful XML before its P/L computation finishes."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Position, Tenant
from app.services.ibkr_import_service import IBKRImportService, IBKRPnlNotReadyError, validate_flex_xml
from app.services.portfolio_ledger_service import PortfolioLedgerService

DEFERRED = '''<FlexQueryResponse><Message>Realized P/L is not ready and has been disabled for this statement.</Message><FlexStatements><FlexStatement fromDate="20261015" toDate="20261015" period="LastBusinessDay"><OpenPositions><OpenPosition symbol="TEST" position="10" markPrice="100" positionValue="1000" costBasisPrice="0" costBasisMoney="0" fifoPnlUnrealized="0" currency="EUR" reportDate="20261015" levelOfDetail="SUMMARY"/></OpenPositions></FlexStatement></FlexStatements></FlexQueryResponse>'''


def test_deferred_pnl_snapshot_rejected_before_any_write():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id='pnl-test', name='Synthetic')
        db.add(tenant)
        db.flush()
        db.info['tenant_id'] = tenant.id
        company = Company(ticker='TEST', name='Synthetic', currency='EUR', exchange='TEST', company_type='holding', valuation_model='unassigned')
        db.add(company)
        db.flush()
        position = Position(company_id=company.id, quantity=Decimal('5'), average_cost=Decimal('80'),
                            market_value_base=Decimal('500'), cost_basis_base=Decimal('400'), source='ibkr_flex')
        db.add(position)
        db.commit()
        with pytest.raises(IBKRPnlNotReadyError, match='conserva la cartera anterior'):
            IBKRImportService().import_flex_xml(db, DEFERRED)
        db.expire_all()
        p = db.scalar(select(Position))
        assert p.quantity == 5
        assert p.average_cost == 80
        assert p.cost_basis_base == 400
        assert db.query(Company).count() == 1


def test_deferred_pnl_warning_handles_whitespace_and_nested_text():
    xml = DEFERRED.replace('Realized P/L is not ready', 'Realized  P/L\n is not <b>ready</b>')
    assert "todavia no ha preparado" in validate_flex_xml(xml)[0]


def test_unrelated_message_not_mistaken_for_deferred_pnl():
    assert validate_flex_xml(DEFERRED.replace('Realized P/L is not ready and has been disabled for this statement.', 'Report generated.')) == []


def test_price_refresh_never_turns_unknown_zero_cost_into_profit():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id='refresh-test', name='Synthetic')
        db.add(tenant)
        db.flush()
        db.info['tenant_id'] = tenant.id
        company = Company(ticker='TEST', name='Synthetic', currency='EUR', exchange='TEST', company_type='holding', valuation_model='unassigned')
        db.add(company)
        db.flush()
        position = Position(company_id=company.id, quantity=Decimal('10'), average_cost=Decimal('0'),
                            market_value_base=Decimal('1000'), cost_basis_base=Decimal('0'), currency='EUR')
        db.add(position)
        db.commit()
        result = PortfolioLedgerService().update_market_price(db, company_id=company.id, price=Decimal('110'), position=position, fx_rate=Decimal('1'))
        assert result.market_value_base == 1100
        assert result.unrealized_pnl_base is None
        assert result.unrealized_pnl == 0


def test_api_does_not_expose_legacy_invented_profit_for_zero_cost():
    from datetime import date

    from app.api.routes.portfolio import positions
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id='api-test', name='Synthetic')
        db.add(tenant)
        db.flush()
        db.info['tenant_id'] = tenant.id
        company = Company(ticker='TEST', name='Synthetic', currency='EUR', exchange='TEST', company_type='holding', valuation_model='unassigned')
        db.add(company)
        db.flush()
        db.add(Position(company_id=company.id, quantity=Decimal('10'), average_cost=Decimal('0'),
                        market_value_base=Decimal('1000'), cost_basis_base=Decimal('0'),
                        unrealized_pnl=Decimal('1000'), unrealized_pnl_base=Decimal('1000'), as_of=date(2026, 10, 15)))
        db.commit()
        row = positions(db=db)["items"][0]  # sobre paginado {items, page_info}
        assert row['market_value_base'] == 1000
        assert row['unrealized_pnl'] is None
        assert row['unrealized_pnl_native'] is None
        assert row['unrealized_pnl_base'] is None


def test_worker_deferred_pnl_retries_hourly_with_bounded_actor_budget(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import dramatiq

    from app.core import config
    from app.services.connectors.ibkr import IBKRFlexClient
    from app.workers import dramatiq_app as worker
    settings = SimpleNamespace(ibkr_flex_tenant_id=1, ibkr_flex_account_id='SYNTHETIC',
                               ibkr_flex_complete_query_id='1', ibkr_flex_query_id='1')
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(IBKRFlexClient, 'configured', lambda self: True)
    async def fetch(self):
        return DEFERRED
    monkeypatch.setattr(IBKRFlexClient, 'fetch_latest_xml', fetch)
    monkeypatch.setattr(worker, 'tenant_contexts', lambda: [(1, 'synthetic')])
    # El worker consulta ibkr_connections con una sesion admin REAL (SessionLocal):
    # el test crea su propio esquema en memoria en vez de depender de que otro
    # test haya dejado el SQLite compartido migrado (dependencia de orden).
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core import database as database_module
    admin_engine = create_engine('sqlite:///:memory:', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(admin_engine)
    monkeypatch.setattr(database_module, 'SessionLocal', sessionmaker(bind=admin_engine))
    db = MagicMock()
    monkeypatch.setattr(worker, '_session', lambda *args: db)
    with pytest.raises(dramatiq.Retry) as exc:
        worker.sync_ibkr_flex.fn()
    assert exc.value.delay == 3_600_000
    assert worker.sync_ibkr_flex.options['max_retries'] == 2
    db.rollback.assert_called_once()
    db.close.assert_called_once()
    db.add.assert_not_called()


def test_regenerated_report_with_real_cost_imports_after_deferred_snapshot():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id='ready-test', name='Synthetic')
        db.add(tenant)
        db.flush()
        db.info['tenant_id'] = tenant.id
        service = IBKRImportService()
        with pytest.raises(IBKRPnlNotReadyError):
            service.import_flex_xml(db, DEFERRED)
        assert db.query(Position).count() == 0
        ready = DEFERRED.replace('<Message>Realized P/L is not ready and has been disabled for this statement.</Message>', '')
        ready = ready.replace('costBasisPrice="0"', 'costBasisPrice="120"').replace('costBasisMoney="0"', 'costBasisMoney="1200"').replace('fifoPnlUnrealized="0"', 'fifoPnlUnrealized="-200"')
        result = service.import_flex_xml(db, ready)
        assert result['status'] == 'imported'
        position = db.scalar(select(Position))
        assert position.quantity == 10
        assert position.average_cost == 120
        assert position.cost_basis_base == 1200
        assert position.unrealized_pnl_base == -200
