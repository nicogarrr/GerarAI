"""Upsert de cierres (market_prices): las lecturas no crecen por barra.

Antes, ``upsert_prices`` lanzaba un SELECT por barra en la via SQLite y un
upsert fila a fila en Postgres (~250 sentencias por empresa en el sync
diario de cierres). Ahora la via SQLite precarga la tanda en UNA consulta
acotada por los dias de entrada (la clave (company_id, date) es unica: no
hay historial que hidratar de mas) y la via Postgres envia un unico
multi-VALUES con el mismo ON CONFLICT. Este test fija el coste plano en
estado estacionario (re-sync con los mismos valores: sin reescrituras) y la
paridad: valor nuevo actualiza, volumen ausente no borra el guardado y un
dia duplicado en la tanda actualiza el pendiente.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice, Tenant
from app.models.entities import Base
from app.services.propicks_price_service import PriceBar, upsert_prices
from tests.test_propicks_funnel import _company as _make_company

BASE = date(2026, 1, 5)  # dias antiguos: pasan el gate de cierre de sesion


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="upsert-count", name="Upsert count")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def _company(db: Session) -> Company:
    company = _make_company("UPS")
    db.add(company)
    db.flush()
    return company


def _bars(n_days: int, close: str = "100") -> list[PriceBar]:
    return [
        PriceBar(
            day=BASE + timedelta(days=i),
            close=Decimal(close),
            adj_close=Decimal(close),
            volume=1000,
            quote_currency="USD",
        )
        for i in range(n_days)
    ]


def _seed(db: Session, company: Company, n_days: int) -> None:
    for bar in _bars(n_days):
        db.add(
            MarketPrice(
                company_id=company.id,
                date=bar.day,
                open=bar.close,
                high=bar.close,
                low=bar.close,
                close=bar.close,
                adj_close=bar.adj_close,
                volume=bar.volume,
                source="yfinance",
                quote_currency="USD",
            )
        )
    db.commit()


def _count_steady(n_days: int) -> tuple[int, int]:
    db = _db()
    company = _company(db)
    _seed(db, company, n_days)
    statements: list[str] = []
    event.listen(db.bind, "before_cursor_execute", lambda *a: statements.append(a[2]))
    written = upsert_prices(db, company, _bars(n_days))
    db.commit()
    db.close()
    return len(statements), written


def test_upsert_estacionario_no_escala_por_barra():
    pocas, w60 = _count_steady(60)
    muchas, w250 = _count_steady(250)
    assert muchas == pocas, (pocas, muchas)
    # 1 preload acotado por la tanda; sin reescrituras (mismos valores).
    assert pocas <= 2
    assert w60 == 60 and w250 == 250


def test_upsert_paridad_update_volumen_y_dup_en_tanda():
    db = _db()
    company = _company(db)
    _seed(db, company, 10)
    bars = _bars(10)
    # Yahoo corrige un cierre y omite el volumen en otro dia.
    bars[3] = PriceBar(
        day=bars[3].day, close=Decimal("101"), adj_close=Decimal("101"),
        volume=2000, quote_currency="USD",
    )
    bars[5] = PriceBar(
        day=bars[5].day, close=Decimal("100"), adj_close=Decimal("100"),
        volume=None, quote_currency="USD",
    )
    assert upsert_prices(db, company, bars) == 10
    db.commit()
    rows = {
        row.date: row
        for row in db.scalars(
            select(MarketPrice).where(MarketPrice.company_id == company.id)
        )
    }
    assert len(rows) == 10
    assert rows[bars[3].day].close == Decimal("101")
    assert rows[bars[3].day].volume == 2000
    # Ausente no borra el volumen real ya guardado.
    assert rows[bars[5].day].volume == 1000
    # Dia duplicado en la misma tanda: gana la ultima barra, una sola fila.
    dup_day = date(2026, 2, 2)
    dup = [
        PriceBar(day=dup_day, close=Decimal("110"), adj_close=Decimal("110"), volume=1, quote_currency="USD"),
        PriceBar(day=dup_day, close=Decimal("111"), adj_close=Decimal("111"), volume=2, quote_currency="USD"),
    ]
    assert upsert_prices(db, company, dup) == 2
    db.commit()
    dups = db.scalars(
        select(MarketPrice).where(
            MarketPrice.company_id == company.id, MarketPrice.date == dup_day
        )
    ).all()
    assert len(dups) == 1 and dups[0].close == Decimal("111") and dups[0].volume == 2
    db.close()


def test_upsert_hidratacion_acotada_por_la_tanda():
    # Clave (company_id, date) unica: el preload hidrata como mucho una
    # instancia por dia de la tanda, nunca toda la historia de la empresa.
    db = _db()
    company = _company(db)
    _seed(db, company, 120)
    db.expire_all()
    loaded = {"n": 0}
    event.listen(MarketPrice, "load", lambda *a: loaded.__setitem__("n", loaded["n"] + 1))
    upsert_prices(db, company, _bars(60))  # solo 60 dias en la tanda
    assert loaded["n"] <= 60, loaded
    db.close()
