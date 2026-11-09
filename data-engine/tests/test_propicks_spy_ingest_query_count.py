"""Ingesta SPY (benchmark_prices): las lecturas no crecen por barra.

Antes, ``ingest_spy_prices`` lanzaba un SELECT POR BARRA de la serie (~250
sentencias en una ingesta anual, cada dia, en el job diario). Ahora las
filas existentes salen de UNA consulta acotada por los dias de la tanda (la
clave (symbol, date) es unica: no hay historial que hidratar de mas) y una
re-pasada con los mismos valores no reescribe nada. Este test fija el coste
plano en estado estacionario, la paridad del comportamiento (valor nuevo
actualiza, misma tanda duplicada actualiza el pendiente) y la hidratacion
ORM acotada por el tamano de la tanda.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.benchmark_price import BenchmarkPrice
from app.models.entities import Base
from app.services.propicks_price_service import PriceBar
from app.services.propicks_track_record_service import ingest_spy_prices

BASE = date(2026, 1, 1)


def _bars(n_days: int, close: str = "500") -> list[PriceBar]:
    return [
        PriceBar(
            day=BASE - timedelta(days=i),
            close=Decimal(close),
            adj_close=Decimal(close),
            volume=1,
        )
        for i in range(n_days)
    ]


def _session(n_days: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    for i in range(n_days):
        db.add(
            BenchmarkPrice(
                symbol="SPY",
                date=BASE - timedelta(days=i),
                close=Decimal("500"),
                adj_close=Decimal("500"),
                source="yfinance",
            )
        )
    db.commit()
    return engine, db


def _fetcher(bars):
    return lambda symbols, period="1y": {"SPY": bars}


def _count_steady(n_days: int) -> tuple[int, dict]:
    engine, db = _session(n_days)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    result = ingest_spy_prices(db, fetcher=_fetcher(_bars(n_days)))
    db.close()
    return len(statements), result


def test_ingesta_spy_estacionaria_no_escala_por_barra():
    pocas, r60 = _count_steady(60)
    muchas, r250 = _count_steady(250)
    assert muchas == pocas, (pocas, muchas)
    # 1 preload acotado por la tanda + 1 SELECT de latest_date; sin updates
    # porque los valores no cambian.
    assert pocas <= 3
    assert r60["bars_written"] == 60 and r250["bars_written"] == 250


def test_ingesta_spy_paridad_update_e_idempotencia():
    engine, db = _session(0)
    bars = _bars(50)
    first = ingest_spy_prices(db, fetcher=_fetcher(bars))
    assert first["bars_written"] == 50
    assert db.query(BenchmarkPrice).count() == 50
    # Re-pasada con los mismos valores: misma cuenta, ninguna fila nueva.
    again = ingest_spy_prices(db, fetcher=_fetcher(bars))
    assert again["bars_written"] == 50
    assert db.query(BenchmarkPrice).count() == 50
    # Yahoo corrige dos cierres: esas filas se actualizan, las demas intactas.
    bars = list(bars)
    bars[3] = replace(bars[3], close=Decimal("501"), adj_close=Decimal("501"))
    bars[7] = replace(bars[7], close=Decimal("502"), adj_close=Decimal("502"))
    ingest_spy_prices(db, fetcher=_fetcher(bars))
    assert db.query(BenchmarkPrice).count() == 50
    updated = db.query(BenchmarkPrice).filter(
        BenchmarkPrice.date == BASE - timedelta(days=3)
    ).one()
    assert float(updated.close) == 501.0
    untouched = db.query(BenchmarkPrice).filter(
        BenchmarkPrice.date == BASE - timedelta(days=4)
    ).one()
    assert float(untouched.close) == 500.0
    # Dia duplicado en la misma tanda: gana la ultima barra, una sola fila.
    dup = [
        PriceBar(day=date(2026, 3, 2), close=Decimal("600"), adj_close=Decimal("600"), volume=1),
        PriceBar(day=date(2026, 3, 2), close=Decimal("601"), adj_close=Decimal("601"), volume=1),
    ]
    ingest_spy_prices(db, fetcher=_fetcher(dup))
    rows = db.query(BenchmarkPrice).filter(BenchmarkPrice.date == date(2026, 3, 2)).all()
    assert len(rows) == 1 and float(rows[0].close) == 601.0
    db.close()


def test_ingesta_spy_hidratacion_acotada_por_la_tanda():
    # La clave (symbol, date) es unica: el preload hidrata como mucho una
    # instancia por dia de la tanda, nunca mas que las barras pedidas.
    engine, db = _session(120)
    db.expire_all()
    loaded = {"n": 0}

    def _on_load(*a):
        loaded["n"] += 1

    # Listener nombrado y retirado en finally: un listener sobre la clase
    # mapeada es global y sobrevive al engine si no se quita.
    event.listen(BenchmarkPrice, "load", _on_load)
    try:
        ingest_spy_prices(db, fetcher=_fetcher(_bars(120)))
        assert loaded["n"] <= 120, loaded
    finally:
        event.remove(BenchmarkPrice, "load", _on_load)
        db.close()
        engine.dispose()
