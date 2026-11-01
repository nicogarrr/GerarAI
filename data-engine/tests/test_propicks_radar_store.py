from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, ProPicksRadarCursor, ProPicksRadarSnapshot
from app.services.propicks_radar_store import latest_public_signals, save_snapshot, scan_cursor


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Company(id=1, ticker='AAA', name='Alpha', exchange='NASDAQ', currency='USD', company_type='large_cap', valuation_model='dcf'))
        session.add(Company(id=2, ticker='BBB', name='Beta', exchange='NASDAQ', currency='USD', company_type='large_cap', valuation_model='dcf'))
        session.commit()
        yield session
    engine.dispose()


def payload(level=1, price_date='2026-10-28'):
    return dict(status='ok', formula_version='nico-v2', price_date=price_date,
                current={'level': level}, confirmed={'level': 1}, price_verified=False)


def test_atomic_idempotent_cursor_and_public_change(db):
    now = datetime(2026, 10, 28, tzinfo=UTC)
    assert scan_cursor(db, now.date()) == (0, 0)
    assert latest_public_signals(db, as_of=now.date()) == []
    save_snapshot(db, 1, payload(), now=now)
    assert scan_cursor(db, now.date()) == (1, 1)
    save_snapshot(db, 1, payload(), now=now)
    assert scan_cursor(db, now.date()) == (1, 1)
    first = latest_public_signals(db, as_of=now.date())
    assert first[0]['change']['status'] == 'history_pending'
    tomorrow = datetime(2026, 10, 29, tzinfo=UTC)
    save_snapshot(db, 1, payload(2, '2026-10-29'), now=tomorrow)
    save_snapshot(db, 2, {'status': 'invalid', 'reason': 'stale'}, now=tomorrow)
    latest = latest_public_signals(db, as_of=tomorrow.date())
    assert latest[0]['change']['changed'] is True
    assert latest[1]['payload']['reason'] == 'stale'
    assert len(latest_public_signals(db, as_of=now.date())) == 1
    assert len(latest_public_signals(db, as_of=tomorrow.date(), company_limit=1)) == 1
    assert len(db.scalars(select(ProPicksRadarSnapshot)).all()) == 3


@pytest.mark.parametrize('changes', [{'private_quality': True}, {'status': 'fabricated'},
                                    {'formula_version': 'other'}])
def test_private_or_unrecognized_snapshot_is_rejected(db, changes):
    with pytest.raises(ValueError):
        save_snapshot(db, 1, {**payload(), **changes}, now=datetime(2026, 10, 28, tzinfo=UTC))
    assert scan_cursor(db, date(2026, 10, 28)) == (0, 0)


def test_unknown_company_does_not_advance_cursor(db):
    with pytest.raises(ValueError, match='unknown company'):
        save_snapshot(db, 9, payload(), now=datetime(2026, 10, 28, tzinfo=UTC))


def test_company_limit_applies_to_evaluated_universe_not_company_table(db):
    # Early Company ids may have no market history or scan. Do not let them
    # hide a later evaluated company from the bounded snapshot read.
    now = datetime(2026, 10, 28, tzinfo=UTC)
    save_snapshot(db, 2, payload(), now=now)
    signals = latest_public_signals(db, as_of=now.date(), company_limit=1)
    assert [row["company_id"] for row in signals] == [2]


def test_cursor_is_scoped_by_formula_version_same_day(db):
    """Cambio de formula el mismo dia: el cursor de v1 no salta el barrido de v2.

    Reproduce el bug de prod del 31-oct-2026: cursor v1 en (1060, 1000) con
    cero snapshots v2 -> scan_cursor devolvia el progreso de v1 y el barrido
    v2 se saltaba 1000 empresas aparentando completado.
    """
    day = date(2026, 10, 31)
    now = datetime(2026, 10, 31, 8, tzinfo=UTC)
    # Semilla realista del estado de prod: snapshots v1 de hoy Y la fila de
    # cursor legada que sus guardados escribieron (sin formula_version).
    db.add(ProPicksRadarSnapshot(
        company_id=1, scan_date=day, formula_version='nico-v1',
        evaluated_at=now, status='ok', payload={'status': 'ok'}))
    db.add(ProPicksRadarSnapshot(
        company_id=2, scan_date=day, formula_version='nico-v1',
        evaluated_at=now, status='ok', payload={'status': 'ok'}))
    db.add(ProPicksRadarCursor(scan_date=day, after_company_id=2, saved_count=2))
    db.commit()
    # El cursor de la formula vigente (nico-v2) NO hereda el progreso de v1.
    assert scan_cursor(db, day) == (0, 0)
    # El barrido v2 guarda la empresa 1 y reanuda desde ella sin saltos.
    save_snapshot(db, 1, payload(price_date='2026-10-30'), now=now)
    assert scan_cursor(db, day) == (1, 1)
    save_snapshot(db, 2, payload(price_date='2026-10-30'), now=now)
    assert scan_cursor(db, day) == (2, 2)
    # Reintento del mismo dia (misma empresa): no infla el contador.
    save_snapshot(db, 2, payload(price_date='2026-10-30'), now=now)
    assert scan_cursor(db, day) == (2, 2)
    # Las senales publicas siguen mostrando solo la formula vigente.
    signals = latest_public_signals(db, as_of=day)
    assert {s['payload']['formula_version'] for s in signals} == {'nico-v2'}
