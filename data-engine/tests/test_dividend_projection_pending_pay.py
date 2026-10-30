"""Un dividendo con ex-date ya pasada y pago aún pendiente es un cobro real
dentro del horizonte: la proyección no puede saltárselo.

Pagador trimestral: ex-dates hace 10, 100, 190 y 280 días, cada pago 25 días
después de su ex-date. El de hace 10 días se paga dentro de 15 días.
En los próximos 12 meses se cobran 4 pagos (el pendiente + las réplicas a un
año de los otros tres). La réplica a un año del pendiente cae fuera (365+15).
10 acciones x 0,25 x 4 = 10,00 USD; a 0,9 = 9,00 EUR. Antes salían 7,50 USD
(3 pagos): se perdía el trimestre ya declarado y pendiente de cobro.
"""

from datetime import date, timedelta

import pytest

from app.services.dividend_projection_service import DividendProjectionService
from tests.test_dividend_projection import _company, _dividend, _fx, _position, db  # noqa: F401


def test_pending_payment_after_past_ex_date_is_projected(db):  # noqa: F811
    company = _company(db)
    _position(db, company)
    today = date.today()
    for days_ago in (10, 100, 190, 280):
        ex = today - timedelta(days=days_ago)
        _dividend(db, company, ex, "0.25", pay_date=ex + timedelta(days=25))
    _fx(db)

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["frequency_last_year"] == 4
    assert pos["gross_native"] == pytest.approx(10.0)
    assert pos["gross_base"] == pytest.approx(9.0)
    pending_month = f"{(today + timedelta(days=15)):%Y-%m}"
    months = {m["month"]: m for m in out["months"]} if "month" in out["months"][0] else None
    if months is not None:
        assert months[pending_month]["gross_base"] == pytest.approx(2.25)
    assert sum(m["gross_base"] for m in out["months"]) == pytest.approx(9.0)


def test_pending_payment_is_not_double_counted_over_24_months(db):  # noqa: F811
    company = _company(db)
    _position(db, company)
    today = date.today()
    for days_ago in (10, 100, 190, 280):
        ex = today - timedelta(days=days_ago)
        _dividend(db, company, ex, "0.25", pay_date=ex + timedelta(days=25))
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=24)

    # 24 meses: pendiente (1) + réplicas a 1 año (4, incluida la del pendiente)
    # + réplicas a 2 años de los tres ya cobrados (3) = 8 pagos x 2,50 = 20,00.
    assert out["positions"][0]["gross_native"] == pytest.approx(20.0)


def test_ex_date_today_without_pay_date_counts_once(db):  # noqa: F811
    company = _company(db)
    _position(db, company)
    today = date.today()
    _dividend(db, company, today, "1.00")
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    assert out["positions"][0]["gross_native"] == pytest.approx(10.0)
