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

    def _on_load(*a):
        loaded["n"] += 1

    # Listener nombrado y retirado en finally: un listener sobre la clase
    # mapeada es global y sobrevive al engine si no se quita.
    engine = db.bind
    event.listen(MarketPrice, "load", _on_load)
    try:
        upsert_prices(db, company, _bars(60))  # solo 60 dias en la tanda
        assert loaded["n"] <= 60, loaded
    finally:
        event.remove(MarketPrice, "load", _on_load)
        db.close()
        if engine is not None:
            engine.dispose()


class _PGDialectStub:
    name = "postgresql"


class _PGBindStub:
    dialect = _PGDialectStub()


class _PGCapturingDB:
    """Sesion minima con bind Postgres falsa: captura la sentencia ejecutada."""

    def __init__(self) -> None:
        self.bind = _PGBindStub()
        self.executed: list = []
        self.info: dict = {}

    def execute(self, stmt, *args, **kwargs):
        self.executed.append(stmt)
        return None


def _pg_insert(sql: str, params: dict, suffix: str = "_m0") -> dict:
    """Campos del primer registro del multi-VALUES compilado."""
    return {k[: -len(suffix)]: v for k, v in params.items() if k.endswith(suffix)}


def _captura_pg(bars) -> tuple[str, dict, _PGCapturingDB]:
    from sqlalchemy.dialects import postgresql

    db = _PGCapturingDB()
    company = _make_company("UPG")
    company.id = 7
    assert upsert_prices(db, company, bars) == len(bars)
    assert len(db.executed) == 1  # una sola sentencia por tanda
    stmt = db.executed[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params), db


def test_pg_dup_en_tanda_conserva_secuencia_fila_a_fila():
    # Secuencia vieja (upsert fila a fila) con (close 100, vol 2000) y luego
    # (close 101, vol None): la fila queda OHLC=100 (la 1.a barra), close/
    # adj_close=101 (la ultima) y volumen 2000 (coalesce: ausente no borra).
    day = date(2026, 1, 5)
    sql, params, _ = _captura_pg([
        PriceBar(day=day, close=Decimal("100"), adj_close=Decimal("100"), volume=2000, quote_currency="USD"),
        PriceBar(day=day, close=Decimal("101"), adj_close=Decimal("101"), volume=None, quote_currency="USD"),
    ])
    row = _pg_insert(sql, params)
    esperado = {
        "company_id": 7,
        "date": day,
        "open": Decimal("100"),  # primer OHLC, no el de la ultima barra
        "high": Decimal("100"),
        "low": Decimal("100"),
        "close": Decimal("101"),  # ultimo cierre
        "adj_close": Decimal("101"),
        "volume": 2000,  # ultimo volumen con dato
        "source": "yfinance",
        "quote_currency": "USD",
    }
    assert row == esperado
    assert "ON CONFLICT" in sql
    assert "coalesce" in sql.lower()  # volumen ausente no pisa el guardado


def test_pg_dup_en_tanda_ultimo_volumen_con_dato_gana():
    # Fila a fila: (close 100, vol 1000) y luego (close 101, vol 3000) ->
    # coalesce(3000, 1000) = 3000. La reduccion por tanda debe dar lo mismo.
    day = date(2026, 1, 5)
    _, params, _ = _captura_pg([
        PriceBar(day=day, close=Decimal("100"), adj_close=Decimal("100"), volume=1000, quote_currency="USD"),
        PriceBar(day=day, close=Decimal("101"), adj_close=Decimal("101"), volume=3000, quote_currency="USD"),
    ])
    row = _pg_insert("x", params)
    assert row["volume"] == 3000
    assert row["close"] == Decimal("101")
    assert row["open"] == Decimal("100")
