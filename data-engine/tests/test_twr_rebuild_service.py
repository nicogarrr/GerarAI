"""Herramienta de reconstrucción de la serie de snapshots/TWR (twr_rebuild).

La serie solo se escribe con reconstrucción verificada, es idempotente, deja
backup restaurable y la primera captura real posterior no encadena sobre una
foto solo-posiciones (cambio de alcance declarado, no mezcla silenciosa).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    MarketPrice,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    Transaction,
)
from app.services.portfolio_snapshot_service import PortfolioSnapshotService
from app.services.twr_rebuild_service import REBUILD_SOURCE, TwrRebuildService

D0 = date(2026, 9, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        session.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        session.commit()
        yield session


def _world(db: Session) -> Company:
    """10 compradas a 10 el día 1, 10 más a 11 el día 3; cierres 10/10/11/12."""
    company = Company(
        ticker="AAA",
        name="AAA",
        exchange="X",
        currency="EUR",
        sector="T",
        industry="I",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    portfolio = db.scalars(select(Portfolio)).one()
    db.add_all(
        [
            Transaction(
                company_id=company.id,
                portfolio_id=portfolio.id,
                trade_date=D0,
                action="buy",
                quantity=Decimal("10"),
                price=Decimal("10"),
                fees=Decimal("0"),
                currency="EUR",
                raw_payload={},
            ),
            Transaction(
                company_id=company.id,
                portfolio_id=portfolio.id,
                trade_date=D0 + timedelta(days=2),
                action="buy",
                quantity=Decimal("10"),
                price=Decimal("11"),
                fees=Decimal("0"),
                currency="EUR",
                raw_payload={},
            ),
        ]
    )
    for offset, close in enumerate([10, 10, 11, 12]):
        db.add(
            MarketPrice(
                company_id=company.id,
                date=D0 + timedelta(days=offset),
                close=Decimal(str(close)),
                adj_close=Decimal(str(close)),
                source="t",
            )
        )
    db.add(
        Position(
            portfolio_id=portfolio.id,
            company_id=company.id,
            quantity=Decimal("20"),
            market_price=Decimal("12"),
            currency="EUR",
            market_value=Decimal("240"),
            market_value_base=Decimal("240"),
            average_cost=Decimal("11"),
            cost_basis_base=Decimal("220"),
            as_of=D0 + timedelta(days=3),
        )
    )
    db.commit()
    return company


def test_plan_is_dry_run_and_writes_nothing(db, tmp_path):
    _world(db)
    service = TwrRebuildService()
    plan = service.plan(db)
    assert plan["status"] == "ok"
    assert plan["rows_to_insert"] == 4
    assert plan["range"] == {"first": "2026-09-01", "last": "2026-09-04"}
    assert db.scalar(select(func.count()).select_from(PortfolioDailySnapshot)) == 0


def test_plan_refuses_unverified_reconstruction(db, tmp_path):
    _world(db)
    # Valor guardado incoherente con la reconstrucción (>3 %): no se escribe.
    position = db.scalars(select(Position)).one()
    position.market_value_base = Decimal("999")
    position.market_value = Decimal("999")
    db.commit()
    service = TwrRebuildService()
    plan = service.plan(db)
    assert plan["status"] == "end_value_mismatch"
    assert "reconstruction_not_verified" in plan["reason"]
    result = service.apply(db, backup_path=tmp_path / "b.json")
    assert result["applied"] is False
    assert db.scalar(select(func.count()).select_from(PortfolioDailySnapshot)) == 0


def test_apply_builds_verified_twr_chain(db, tmp_path):
    _world(db)
    result = TwrRebuildService().apply(db, backup_path=tmp_path / "b.json")
    assert result["applied"] is True
    assert result["inserted_snapshots"] == 4
    rows = list(
        db.scalars(select(PortfolioDailySnapshot).order_by(PortfolioDailySnapshot.snapshot_date)).all()
    )
    assert {row.source for row in rows} == {REBUILD_SOURCE}
    base, d2, d3, d4 = rows
    # Base de la serie: sin retorno por definición.
    assert base.daily_return is None and base.cumulative_twr is None
    assert base.total_value_base == Decimal("100")
    # día 2: 100 -> 100 sin flujos = 0 %
    assert d2.daily_return == pytest.approx(Decimal("0"))
    # día 3: valor 220, flujo +110 (10×11), previo 100 -> (220-110)/100-1 = 10 %
    assert d3.daily_return == pytest.approx(Decimal("0.10"))
    assert d3.cumulative_twr == pytest.approx(Decimal("0.10"))
    # día 4: 240/220 - 1; acumulado = 1,1 × 12/11 - 1 = 20 %
    assert d4.daily_return == pytest.approx(Decimal(12) / Decimal(11) - 1)
    assert d4.cumulative_twr == pytest.approx(Decimal("0.20"))
    for row in rows:
        assert row.metadata_["positions_only"] is True
        assert row.pricing_coverage == Decimal("1")


def test_apply_is_idempotent(db, tmp_path):
    _world(db)
    service = TwrRebuildService()
    service.apply(db, backup_path=tmp_path / "b1.json")
    first = [
        (r.snapshot_date, r.total_value_base, r.daily_return, r.cumulative_twr)
        for r in db.scalars(
            select(PortfolioDailySnapshot).order_by(PortfolioDailySnapshot.snapshot_date)
        ).all()
    ]
    service.apply(db, backup_path=tmp_path / "b2.json")
    second = [
        (r.snapshot_date, r.total_value_base, r.daily_return, r.cumulative_twr)
        for r in db.scalars(
            select(PortfolioDailySnapshot).order_by(PortfolioDailySnapshot.snapshot_date)
        ).all()
    ]
    assert first == second


def test_apply_backs_up_and_restore_reverts(db, tmp_path):
    _world(db)
    portfolio = db.scalars(select(Portfolio)).one()
    legacy = PortfolioDailySnapshot(
        portfolio_id=portfolio.id,
        snapshot_date=D0 + timedelta(days=1),
        base_currency="EUR",
        positions_value_base=Decimal("999"),
        cash_value_base=Decimal("1"),
        total_value_base=Decimal("1000"),
        pricing_coverage=Decimal("1"),
        source="market_refresh",
    )
    db.add(legacy)
    db.commit()
    service = TwrRebuildService()
    result = service.apply(db, backup_path=tmp_path / "backup.json")
    assert result["deleted_snapshots"] == 1
    assert (tmp_path / "backup.json").exists()
    restored = service.restore_backup(db, backup_path=tmp_path / "backup.json")
    assert restored == {"status": "restored", "restored": 1, "deleted": 4}
    rows = db.scalars(select(PortfolioDailySnapshot)).all()
    assert len(rows) == 1
    assert rows[0].source == "market_refresh"
    assert rows[0].total_value_base == Decimal("1000")


def test_capture_does_not_chain_real_day_over_positions_only_rebuild(db, tmp_path):
    _world(db)
    TwrRebuildService().apply(db, backup_path=tmp_path / "b.json")
    service = PortfolioSnapshotService()
    position = db.scalars(select(Position)).one()

    position.market_price = Decimal("12.5")
    position.as_of = D0 + timedelta(days=4)
    db.commit()
    boundary = service.capture(db, as_of=D0 + timedelta(days=4))
    # No encadena: mezclaría posiciones+caja con la serie solo-posiciones.
    assert boundary.daily_return is None
    assert boundary.cumulative_twr is None
    assert boundary.metadata_["twr_blocked_by_scope_change"] is True
    assert boundary.metadata_["twr_base_after_scope_change"] is True

    # El día siguiente sí enlaza: la foto bloqueada es base nueva declarada.
    position.market_price = Decimal("13")
    position.as_of = D0 + timedelta(days=5)
    db.commit()
    nxt = service.capture(db, as_of=D0 + timedelta(days=5))
    assert nxt.daily_return == pytest.approx(Decimal("0.04"))
    assert nxt.cumulative_twr == pytest.approx(Decimal("0.04"))
