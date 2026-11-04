"""Chat: lo realizado de un ticker vendido cuenta TODAS sus ventas guardadas.

«¿Cuánto he ganado con AAPL?» con ventas en más de seis ejercicios solo sumaba
los seis últimos (``years[-6:]``): la venta más antigua desaparecía del total y
del recuento sin aviso, y la respuesta seguía diciendo «tus ventas guardadas».
Vale para cualquier empresa y tenant: ningún ejercicio con ventas queda fuera.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models import Company, FXRate, Transaction
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401


def _db_with_eight_years_of_sales():
    db = _db()
    aapl = db.scalar(select(Company).where(Company.ticker == "AAPL"))
    day = date(2017, 12, 1)
    while day < date(2021, 12, 1):
        db.add(FXRate(tenant_id=1, base_currency="EUR", quote_currency="USD", rate=Decimal("0.9"),
                      rate_date=day, source="ecb"))
        day += timedelta(days=1)
    db.add(Transaction(tenant_id=1, company_id=aapl.id, trade_date=date(2018, 1, 10), action="buy",
                       quantity=Decimal(80), price=Decimal("50"), fees=Decimal("0"), currency="USD"))
    # Una venta de 10 al año de 2019 a 2026: ocho ejercicios, +500 $ (+450 €) cada una.
    for year in range(2019, 2027):
        db.add(Transaction(tenant_id=1, company_id=aapl.id, trade_date=date(year, 2, 3), action="sell",
                           quantity=Decimal(10), price=Decimal("100"), fees=Decimal("0"), currency="USD"))
    db.commit()
    return db, aapl


def test_realized_counts_every_year_with_sales():
    from app.services.brain_account_tools import realized_line_for_closed_ticker

    db, aapl = _db_with_eight_years_of_sales()
    assert realized_line_for_closed_ticker(db, 1, aapl.id, "AAPL", "¿cuánto he ganado con AAPL?", False) == (
        "Realizado con tus ventas guardadas de AAPL: +3.600,00 € "
        "(8 ventas: 3 feb 2024, 3 feb 2025, 3 feb 2026…; en euros, FIFO como en el informe fiscal)."
    )


def test_a_year_question_still_reads_only_that_year():
    from app.services.brain_account_tools import realized_line_for_closed_ticker

    db, aapl = _db_with_eight_years_of_sales()
    assert realized_line_for_closed_ticker(db, 1, aapl.id, "AAPL", "¿cuánto gané con AAPL en 2019?", False) == (
        "Realizado en 2019 con tus ventas guardadas de AAPL: +450,00 € "
        "(1 venta: 3 feb 2019; en euros, FIFO como en el informe fiscal)."
    )


def test_other_tenant_sales_never_count():
    db, _ = _db_with_eight_years_of_sales()
    db.info["tenant_id"] = 2
    answer = _ask(db, "¿cuánto he ganado con AAPL?").answer
    assert "3.600" not in answer
