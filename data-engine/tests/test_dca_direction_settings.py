"""Destination thresholds, persistence/isolation and migration reversal."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.dca_settings import router
from app.core.database import Base, get_db
from app.models import DcaAlertOverride, Tenant
from app.services.dca_alert_settings_service import effective_policy, save_policy, settings_view
from app.services.dca_signal_service import should_alert


@pytest.mark.parametrize('previous,level,expected', [
    (None, 3, False), (1, 2, False), (2, 3, True), (3, 2, False),
    (2, 1, True), (3, 4, True), (4, 3, False), (3, 3, False),
    (1, 4, True), (4, 1, True),
])
def test_destination_thresholds(previous, level, expected):
    # Legacy per-ticker OFF must not suppress the global directional policy.
    assert should_alert(level=level, previous_level=previous, min_level=0,
        trims_enabled=False, up_min_level=3, down_max_level=1) is expected


def test_direction_off_and_trim_opt_in():
    assert should_alert(level=3, previous_level=-1, min_level=0, trims_enabled=False, up_min_level=3, down_max_level=1)
    assert not should_alert(level=2, previous_level=-1, min_level=0, trims_enabled=False, up_min_level=3, down_max_level=1)
    assert not should_alert(level=4, previous_level=2, min_level=4, trims_enabled=False, up_min_level=0, down_max_level=1)
    assert should_alert(level=1, previous_level=2, min_level=0, trims_enabled=False, up_min_level=0, down_max_level=1)
    assert not should_alert(level=1, previous_level=2, min_level=1, trims_enabled=False, up_min_level=3, down_max_level=0)
    assert not should_alert(level=-1, previous_level=1, min_level=1, trims_enabled=False, up_min_level=3, down_max_level=1)
    assert should_alert(level=-1, previous_level=1, min_level=1, trims_enabled=True, up_min_level=3, down_max_level=1)


@pytest.fixture
def db():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=4101, external_id='direction-a'), Tenant(id=4102, external_id='direction-b')])
        session.commit()
        session.info['tenant_id'] = 4101
        yield session
    engine.dispose()


def test_effective_defaults_isolation_and_preserved_overrides(db):
    db.add(DcaAlertOverride(tenant_id=4101, symbol='TEST', min_level=0)); db.commit()
    p = effective_policy(db)
    assert (p.up_min_level, p.down_max_level) == (3, 1)
    assert not settings_view(db)['configured']
    assert settings_view(db)['legacy_override_count'] == 1
    save_policy(db, 4, 0)
    assert settings_view(db)['configured']
    assert db.scalar(select(DcaAlertOverride).where(DcaAlertOverride.tenant_id == 4101)).min_level == 0
    db.info['tenant_id'] = 4102
    assert effective_policy(db).up_min_level == 3
    assert settings_view(db)['legacy_override_count'] == 0
    save_policy(db, 2, 1)
    db.info['tenant_id'] = 4101
    assert effective_policy(db).up_min_level == 4
    with pytest.raises(ValueError): save_policy(db, True, 1)
    db.info.pop('tenant_id')
    with pytest.raises(ValueError): save_policy(db, 3, 1)


def test_http_contract_auth_validation_persistence(db):
    app = FastAPI(); app.include_router(router, prefix='/api/settings/dca')
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    assert client.get('/api/settings/dca').json()['up_min_level'] == 3
    result = client.put('/api/settings/dca', json={'up_min_level': 4, 'down_max_level': 0})
    assert result.status_code == 200 and result.json()['configured']
    for value in [-1, 5, True, 2.5, '3']:
        assert client.put('/api/settings/dca', json={'up_min_level': value, 'down_max_level': 1}).status_code == 422
    assert client.put('/api/settings/dca', json={'up_min_level': 3, 'down_max_level': 1, 'tenant_id': 4102}).status_code == 422
    assert client.get('/api/settings/dca').json()['down_max_level'] == 0
    db.info.pop('tenant_id')
    assert client.get('/api/settings/dca').status_code == 401
    assert client.put('/api/settings/dca', json={'up_min_level': 3, 'down_max_level': 1}).status_code == 401


def test_migration_upgrade_downgrade_preserves_legacy(db):
    db.add(DcaAlertOverride(tenant_id=4101, symbol='KEPT', min_level=4)); db.commit()
    path = Path(__file__).parents[1] / 'alembic/versions/0098_dca_direction_settings.py'
    spec = spec_from_file_location('migration_dca', path); migration = module_from_spec(spec); spec.loader.exec_module(migration)
    with db.get_bind().begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()  # create_all adoption
        migration.downgrade()
        assert not inspect(connection).has_table('dca_alert_settings')
        assert connection.execute(select(DcaAlertOverride.min_level).where(DcaAlertOverride.symbol == 'KEPT')).scalar() == 4
        migration.upgrade()  # clean creation
        assert inspect(connection).has_table('dca_alert_settings')
    assert len(migration.revision) <= 32
