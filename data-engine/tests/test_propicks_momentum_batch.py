"""El calculo de momentum del job F2 hacia ~3 consultas por empresa
(historial completo de precios + un scalar por metrica existente).

Ahora son 3 consultas para todo el lote con resultados identicos: el
recuento MIN_BARS sigue siendo sobre toda la historia y las barras se
acotan a la ventana que el momentum puede mirar (una barra mas vieja que
d0-385 seria rechazada por la regla de +-20 dias de momentum_from_series).
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import event, select

from app.models import CalculatedMetric, MarketPrice
from app.services.propicks_price_service import compute_momentum_metrics, momentum_from_series
from tests.test_propicks_prices import _company, _db


def _seed(db, ticker, start, days, price_fn=lambda i: 100 + i * 0.1):
    company = _company(ticker)
    db.add(company)
    db.flush()
    for i in range(days):
        day = start + timedelta(days=i)
        db.add(MarketPrice(company_id=company.id, date=day, close=Decimal(str(price_fn(i))),
                           adj_close=Decimal(str(price_fn(i))), source="test"))
    db.flush()
    return company


def _full_series(db, company_id, as_of):
    rows = db.execute(
        select(MarketPrice.date, MarketPrice.adj_close)
        .where(MarketPrice.company_id == company_id, MarketPrice.date <= as_of)
        .order_by(MarketPrice.date)
    ).all()
    return [(d, Decimal(str(p))) for d, p in rows if p is not None and p > 0]


def _metric(db, company_id, metric):
    return db.scalar(
        select(CalculatedMetric).where(
            CalculatedMetric.company_id == company_id,
            CalculatedMetric.metric == metric,
        )
    )


def test_momentum_batch_uses_constant_queries():
    db = _db()
    start = date(2024, 1, 1)
    companies = [_seed(db, f"M{i:02d}", start, 300) for i in range(6)]
    as_of = start + timedelta(days=299)
    statements = []
    engine = db.get_bind()

    def _count(conn, cursor, statement, parameters, context, executemany):
        if "FROM market_prices" in statement or "FROM calculated_metrics" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        stats = compute_momentum_metrics(db, companies, as_of=as_of)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    # 300 barras: historia suficiente para 6m, no para 12m (sin punto a -365d).
    assert stats == {"momentum_6m": 6, "momentum_12m": 0, "skipped": 0}
    assert len(statements) <= 3, f"{len(statements)} consultas para 6 empresas"


def test_momentum_values_match_full_history_computation():
    db = _db()
    start = date(2024, 1, 1)
    long_co = _seed(db, "LNG", start, 800)
    as_of = start + timedelta(days=799)
    compute_momentum_metrics(db, [long_co], as_of=as_of)
    series = _full_series(db, long_co.id, as_of)
    for metric, days in (("momentum_6m", 182), ("momentum_12m", 365)):
        written = _metric(db, long_co.id, metric)
        assert written is not None, f"{metric} no escrita con 800 barras"
        expected = momentum_from_series(series, days).quantize(Decimal('0.00000001'))
        assert written.value == expected
        assert written.calculation_trace["last_bar_date"] == series[-1][0].isoformat()


def test_momentum_skips_sparse_and_short_histories():
    db = _db()
    start = date(2024, 1, 1)
    # 60 barras que terminan 200 dias antes de as_of: sin punto pasado valido.
    stale = _seed(db, "OLD", start, 60)
    # 30 barras: por debajo de MIN_BARS_6M.
    short = _seed(db, "SHT", start, 30)
    as_of = start + timedelta(days=260)
    stats = compute_momentum_metrics(db, [stale, short], as_of=as_of)
    assert stats == {"momentum_6m": 0, "momentum_12m": 0, "skipped": 1}
    assert _metric(db, stale.id, "momentum_6m") is None
    assert _metric(db, short.id, "momentum_6m") is None


def test_null_price_row_after_valid_bars_does_not_shift_d0():
    """Una fila con adj_close NULL posterior a las barras validas no puede
    mover d0: el momentum se calcula desde la ultima barra VALIDA."""
    db = _db()
    start = date(2024, 1, 1)
    company = _seed(db, "NUL", start, 800)
    db.add(MarketPrice(company_id=company.id, date=start + timedelta(days=900),
                       close=Decimal("5"), adj_close=None, source="test"))
    db.flush()
    as_of = start + timedelta(days=900)
    stats = compute_momentum_metrics(db, [company], as_of=as_of)
    assert stats["momentum_6m"] == 1 and stats["momentum_12m"] == 1
    series = _full_series(db, company.id, as_of)
    written = _metric(db, company.id, "momentum_12m")
    expected = momentum_from_series(series, 365).quantize(Decimal("0.00000001"))
    assert written.value == expected
    assert written.calculation_trace["last_bar_date"] == (start + timedelta(days=799)).isoformat()
