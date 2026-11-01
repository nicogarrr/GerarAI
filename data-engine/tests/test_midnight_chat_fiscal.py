"""Año y «hoy» del chat y del flujo fiscal con la fecha de Madrid.

Producción corre con TZ=UTC. El 1 de enero a las 00:30 de Madrid el reloj UTC
todavía marca el 31 de diciembre: el contexto del chat salía fechado «ayer» y
pedía el IRPF de dos años atrás, y el flujo de resultados proponía el año
fiscal anterior.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base

NOW = datetime(2026, 12, 31, 23, 30, tzinfo=UTC)  # 00:30 del 1 de enero de 2027 en Madrid
UTC_DAY = date(2026, 12, 31)
MADRID_DAY = date(2027, 1, 1)


class UtcDate(date):
    @classmethod
    def today(cls):
        return UTC_DAY


class UtcDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


@pytest.fixture
def madrid_new_year(monkeypatch):
    import app.core.local_date as local_date

    monkeypatch.setattr(local_date, "_utc_now", lambda: NOW)
    return monkeypatch


def test_contexto_del_chat_usa_el_dia_y_el_año_fiscal_de_madrid(madrid_new_year):
    import app.services.user_context as user_context

    madrid_new_year.setattr(user_context, "date", UtcDate)
    years: list[int] = []

    def fake_fiscal_block(db, year):
        years.append(year)
        return user_context.ContextBlock(key="fiscal")

    madrid_new_year.setattr(user_context, "_fiscal_block", fake_fiscal_block)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        ctx = user_context.build_user_context(db, sections=["fiscal"])
    engine.dispose()

    assert ctx is not None
    assert ctx.as_of == MADRID_DAY
    assert years == [2026]  # IRPF del año cerrado: 2027 - 1, no 2026 - 1


def test_flujo_de_resultados_propone_el_año_de_madrid(madrid_new_year):
    import app.api.routes.workflows as workflows

    madrid_new_year.setattr(workflows, "datetime", UtcDateTime, raising=False)

    assert workflows.EarningsRunParams().fiscal_year == 2027
