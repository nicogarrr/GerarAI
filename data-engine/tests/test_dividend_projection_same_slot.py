"""El mismo cobro en dos años seguidos no se proyecta dos veces.

La historia son las ex-dates de los últimos 12 meses. Cuando la ex-date de
este año cae unos días ANTES que la del año pasado (3-nov-2025 y 30-oct-2026),
los dos registros entran en la ventana y la proyección replicaba los dos:
un pagador anual salía con 2 cobros en los próximos 12 meses y un trimestral
con 5.
"""

from datetime import date, timedelta

import pytest

from app.services.dividend_projection_service import DividendProjectionService
from tests.test_dividend_projection import _company, _dividend, _fx, _position, db  # noqa: F401


def test_annual_payer_with_earlier_ex_date_this_year_counts_once(db):  # noqa: F811
    company = _company(db)
    _position(db, company)
    today = date.today()
    last_year = today - timedelta(days=362)
    _dividend(db, company, last_year, "1.00", pay_date=last_year + timedelta(days=17))
    this_year = today - timedelta(days=3)
    _dividend(db, company, this_year, "1.00", pay_date=this_year + timedelta(days=18))
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    # Un solo cobro (el pendiente de este año): 10 acciones x 1,00.
    assert pos["frequency_last_year"] == 1
    assert pos["gross_native"] == pytest.approx(10.0)


def test_quarterly_payer_drifting_ex_date_projects_four_payments(db):  # noqa: F811
    company = _company(db)
    _position(db, company)
    today = date.today()
    for days_ago in (362, 271, 180, 89):
        ex = today - timedelta(days=days_ago)
        _dividend(db, company, ex, "0.25", pay_date=ex + timedelta(days=20))
    pending = today - timedelta(days=2)
    _dividend(db, company, pending, "0.25", pay_date=pending + timedelta(days=20))
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["frequency_last_year"] == 4
    assert pos["gross_native"] == pytest.approx(10.0)


def test_annual_payer_already_paid_this_year_counts_once(db):  # noqa: F811
    company = _company(db)
    _position(db, company)
    today = date.today()
    last_year = today - timedelta(days=362)
    _dividend(db, company, last_year, "1.00", pay_date=last_year + timedelta(days=10))
    this_year = today - timedelta(days=10)
    _dividend(db, company, this_year, "1.00", pay_date=this_year + timedelta(days=5))
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    # Ya cobrado este año: el próximo es la réplica de ESTE año (no la del pasado).
    assert out["positions"][0]["gross_native"] == pytest.approx(10.0)


def test_monthly_payer_keeps_twelve_payments(db):  # noqa: F811
    company = _company(db)
    _position(db, company)
    today = date.today()
    for k in range(1, 13):
        ex = today - timedelta(days=30 * k - 5)
        _dividend(db, company, ex, "0.10", pay_date=ex + timedelta(days=10))
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    assert out["positions"][0]["frequency_last_year"] == 12
