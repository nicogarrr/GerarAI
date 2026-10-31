"""La congelacion mensual cargaba TODAS las barras historicas de cada
empresa aprobada (~100 x historia completa) para quedarse con el ultimo
cierre con dato.

Ahora una ventana row_number trae solo ese ultimo cierre por empresa.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import event

from app.models import MarketPrice
from app.services.propicks_snapshot_service import freeze_monthly_snapshot
from tests.test_propicks_funnel import _company, _db, _five_good_years, _full_metrics


def _passing_company(db, ticker):
    c = _company(ticker)
    db.add(c)
    db.flush()
    _full_metrics(db, c)
    _five_good_years(db, c)
    return c


def test_freeze_reads_latest_price_with_window_function():
    with _db() as db:
        c = _passing_company(db, "FRZ1")
        first_day = date(2024, 1, 1)
        for i in range(600):
            db.add(MarketPrice(company_id=c.id, date=first_day + timedelta(days=i),
                               close=Decimal("10") + i, volume=1))
        db.commit()
        statements = []
        engine = db.get_bind()

        def _capture(conn, cursor, statement, parameters, context, executemany):
            if "FROM market_prices" in statement:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", _capture)
        try:
            snap = freeze_monthly_snapshot(db, now=datetime(2026, 10, 19, tzinfo=UTC))
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert snap is not None
        assert "row_number" in " ".join(statements).lower(), \
            "la lectura de precios sigue recorriendo toda la historia"
        pick = snap.payload["picks"][0]
        assert pick["price"] == float(Decimal("10") + 599)
        assert pick["price_date"] == (first_day + timedelta(days=599)).isoformat()


def test_freeze_uses_latest_date_not_insertion_order():
    with _db() as db:
        c = _passing_company(db, "FRZ2")
        db.add(MarketPrice(company_id=c.id, date=date(2026, 10, 10), close=Decimal("50"), volume=1))
        db.add(MarketPrice(company_id=c.id, date=date(2026, 9, 1), close=Decimal("99"), volume=1))
        db.commit()
        snap = freeze_monthly_snapshot(db, now=datetime(2026, 10, 19, tzinfo=UTC))
        pick = snap.payload["picks"][0]
        assert pick["price_date"] == "2026-10-10"
        assert pick["price"] == 50.0
