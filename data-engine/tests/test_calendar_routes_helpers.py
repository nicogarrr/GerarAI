"""Tests de routes/calendar.py: validacion de rangos, zona horaria de Madrid,
degradacion de proveedores y contratos de los endpoints.

Los endpoints nunca devuelven 5xx por un fallo del proveedor y las fechas por
defecto son "hoy" en Europe/Madrid, no el dia UTC del contenedor: esos
contratos son los que se fijan aqui. Los conectores se sustituyen por fakes
que solo graban llamadas.
"""

import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.api.routes import calendar as cal
from app.services import catalyst_calendar_service as catalyst_service
from app.services.connectors import earnings_calendar as calendar_connector
from app.services.connectors import ipo_calendar as ipo_connector


def run_async(coroutine):
    return asyncio.run(coroutine)


MADRID = ZoneInfo("Europe/Madrid")


def test_madrid_today_usa_la_zona_de_madrid_no_utc():
    # 23:30 UTC del 1 de enero ya es 2 de enero en Madrid (UTC+1)
    now = datetime(2024, 1, 1, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert cal._madrid_today(now) == date(2024, 1, 2)
    # mediodia UTC: mismo dia
    noon = datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert cal._madrid_today(noon) == date(2024, 1, 1)


def test_plus_days_desbordado_es_400_no_500():
    with pytest.raises(HTTPException) as exc:
        cal._plus_days(date(9999, 12, 31), 1)
    assert exc.value.status_code == 400


def test_resolve_range_por_defecto_7_dias_desde_hoy_madrid():
    start, end = cal._resolve_range(None, None)
    assert start == cal._madrid_today()
    assert (end - start).days == 7


def test_resolve_range_desde_posterior_a_hasta_es_400():
    with pytest.raises(HTTPException) as exc:
        cal._resolve_range(date(2024, 2, 10), date(2024, 2, 1))
    assert exc.value.status_code == 400


def test_resolve_range_supera_maximo_es_400():
    over = calendar_connector.MAX_DAYS_PER_REQUEST  # rango de dias > maximo
    with pytest.raises(HTTPException) as exc:
        cal._resolve_range(date(2024, 1, 1), date(2024, 1, 1) + timedelta(days=over))
    assert exc.value.status_code == 400


def test_earnings_calendar_pasa_el_rango_resuelto(monkeypatch):
    calls = {}

    async def fake_range(start, end):
        calls["args"] = (start, end)
        return {"status": "ok", "events": []}

    monkeypatch.setattr(calendar_connector, "fetch_earnings_range", fake_range)
    out = run_async(cal.earnings_calendar(date(2024, 3, 1), date(2024, 3, 5)))
    assert out == {"status": "ok", "events": []}
    assert calls["args"] == (date(2024, 3, 1), date(2024, 3, 5))


def test_earnings_calendar_valueerror_del_conector_es_400(monkeypatch):
    async def boom(start, end):
        raise ValueError("rango máximo: 31 días")

    monkeypatch.setattr(calendar_connector, "fetch_earnings_range", boom)
    with pytest.raises(HTTPException) as exc:
        run_async(cal.earnings_calendar(date(2024, 3, 1), date(2024, 3, 5)))
    assert exc.value.status_code == 400


def test_dividends_calendar_valueerror_del_conector_es_400(monkeypatch):
    async def boom(start, end):
        raise ValueError("rango máximo: 31 días")

    monkeypatch.setattr(calendar_connector, "fetch_dividends_range", boom)
    with pytest.raises(HTTPException) as exc:
        run_async(cal.dividends_calendar(date(2024, 3, 1), None))
    assert exc.value.status_code == 400


def test_followed_valida_rango():
    with pytest.raises(HTTPException) as exc:
        cal.followed_earnings_calendar(date(2024, 2, 10), date(2024, 2, 1), db=None)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        cal.followed_earnings_calendar(date(2024, 1, 1), date(2025, 1, 2), db=None)
    assert exc.value.status_code == 400


def test_followed_happy_path_usa_el_servicio(monkeypatch):
    from app.services import earnings_dates_service

    calls = {}

    def fake_followed(db, start, end):
        calls["args"] = (db, start, end)
        return {"days": []}

    monkeypatch.setattr(earnings_dates_service, "followed_calendar", fake_followed)
    sentinel = object()
    out = cal.followed_earnings_calendar(date(2024, 3, 1), date(2024, 3, 10), db=sentinel)
    assert out == {"days": []}
    assert calls["args"] == (sentinel, date(2024, 3, 1), date(2024, 3, 10))


def test_followed_materials_solo_eventos_confirmados(monkeypatch):
    from app.services import earnings_dates_service, earnings_materials_service

    def fake_followed(db, start, end):
        return {
            "days": [
                {
                    "date": "2024-03-01",
                    "events": [
                        {"ticker": "A", "confirmed": True},
                        {"ticker": "B", "confirmed": False},
                        {"ticker": "C", "confirmed": None},
                    ],
                }
            ]
        }

    captured = {}

    async def fake_materials(events, today, sec=None):
        captured["events"] = events
        return [{"ticker": "A"}]

    monkeypatch.setattr(earnings_dates_service, "followed_calendar", fake_followed)
    monkeypatch.setattr(earnings_materials_service, "materials_for_events", fake_materials)
    out = run_async(cal.followed_materials(db=None))
    assert captured["events"] == [{"ticker": "A", "confirmed": True}]  # solo confirmados
    assert out["items"] == [{"ticker": "A"}]
    assert out["as_of"] == datetime.now(MADRID).date().isoformat()


def test_catalysts_sin_cartera_ni_watchlist_no_llama_proveedores(monkeypatch):
    monkeypatch.setattr(catalyst_service, "held_tickers", lambda db: ([], []))
    monkeypatch.setattr(catalyst_service, "watchlist_us_tickers", lambda db, held: [])
    monkeypatch.setattr(catalyst_service, "watchlist_tickers", lambda db, held: [])

    async def boom(*args, **kwargs):
        raise AssertionError("no debe llamar a NASDAQ sin cartera ni watchlist")

    monkeypatch.setattr(calendar_connector, "fetch_earnings_range", boom)
    out = run_async(cal.catalysts_calendar(date(2024, 3, 1), date(2024, 3, 5), db=None))
    assert out["status"] == "ok"
    assert out["held_count"] == 0 and out["watchlist_count"] == 0 and out["count"] == 0
    assert out["events"] == []
    assert out["desde"] == "2024-03-01" and out["hasta"] == "2024-03-05"


def test_ipo_calendar_meses_desde_hoy_madrid(monkeypatch):
    captured = {}

    async def fake_ipos(months):
        captured["months"] = months
        return {"status": "ok", "months": months}

    monkeypatch.setattr(ipo_connector, "fetch_ipo_calendar", fake_ipos)
    out = run_async(cal.ipo_calendar())
    expected = [ipo_connector.add_months(cal._madrid_today(), i) for i in range(ipo_connector.DEFAULT_MONTHS)]
    assert captured["months"] == expected
    assert out["status"] == "ok"


def test_feed_state_sin_suscripcion_y_con_ella():
    assert cal._feed_state(None) == {
        "active": False,
        "scope": None,
        "created_at": None,
        "last_used_at": None,
    }
    row = SimpleNamespace(
        scope="watchlist",
        created_at=datetime(2024, 3, 1, 12, 0, 0),
        last_used_at=None,
    )
    state = cal._feed_state(row)
    assert state["active"] is True
    assert state["scope"] == "watchlist"
    assert state["created_at"] == "2024-03-01T12:00:00"
    assert state["last_used_at"] is None


def test_feed_create_scope_invalido_es_422():
    with pytest.raises(HTTPException) as exc:
        cal.calendar_feed_create(cal.FeedCreate(scope="todo"), db=None)
    assert exc.value.status_code == 422
