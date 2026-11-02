"""Rendimiento: _db_history recibe los cierres como float de la base.

El CAST a double y la lectura por Core (MarketPrice no es de tenant) quitan
un Decimal y una fila ORM por cierre. Este test fija que cada cierre sale
exactamente igual que ``float(Decimal)`` (mismo redondeo, bit a bit).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.models.entities import MarketPrice
from app.services import dca_signal_service as svc
from tests.test_dca_signal_service import _company, db  # noqa: F401  (fixture db)

_CIERRES = ["0.1", "2.52", "123.456789", "9999.999999", "0.000001", "317.3333", "0", "1.005"]


def test_db_history_cierres_float_identicos_a_decimal(db):
    company = _company(db, "FLT", currency="USD", exchange="NASDAQ")
    start = date(2026, 1, 5)
    for i, raw in enumerate(_CIERRES):
        value = Decimal(raw)
        db.add(
            MarketPrice(
                company_id=company.id,
                date=start + timedelta(days=i),
                open=value,
                high=value,
                low=value,
                close=value,
                adj_close=None if i % 3 == 0 else value,
                volume=10,
                source="test",
            )
        )
    db.flush()

    hist = svc._db_history(db, company)

    expected = [
        (start + timedelta(days=i), float(Decimal(raw)), None if i % 3 == 0 else float(Decimal(raw)))
        for i, raw in enumerate(_CIERRES)
        if Decimal(raw) > 0
    ]
    got = [(r.day, r.close, r.adj_close) for r in hist.rows]
    assert got == expected
    assert all(type(r.close) is float for r in hist.rows)
    assert all(r.adj_close is None or type(r.adj_close) is float for r in hist.rows)
