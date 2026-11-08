"""Rutas /api/calendar: helpers de rango, conectores degradados y feed ICS.

Sobre main (44.8%) estaban sin ejercitar los endpoints /earnings,
/dividends, /followed, /portfolio-upcoming, /followed/materials,
/catalysts, /ipos y las rutas del feed ICS. Los conectores y servicios se
sustituyen por dobles: aqui se fija el comportamiento de la ruta (rangos,
400 de validacion, nunca 5xx por el proveedor), no el de los servicios.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.catalyst_calendar_service as catalyst_service
import app.services.connectors.earnings_calendar as earnings_connector
import app.services.connectors.ipo_calendar as ipo_connector
from app.api.routes.calendar import (
    FeedCreate,
    _empty_connector,
    _feed_state,
    _madrid_today,
    _plus_days,
    _resolve_range,
    calendar_feed_create,
    calendar_feed_public,
    calendar_feed_revoke,
    calendar_feed_status,
    catalysts_calendar,
    dividends_calendar,
    earnings_calendar,
    followed_earnings_calendar,
    followed_materials,
    ipo_calendar,
    portfolio_upcoming_dates,
)
from app.models.entities import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        yield db
    engine.dispose()


# --- helpers de fechas -------------------------------------------------


def test_madrid_today_usa_la_zona_de_madrid():
    # 23:30 UTC del 10 de enero ya es dia 11 en Madrid (CET, UTC+1).
    now = datetime(2026, 1, 10, 23, 30, tzinfo=UTC)
    assert _madrid_today(now) == date(2026, 1, 11)


def test_empty_connector_tiene_el_contrato_de_uno_vacio():
    assert asyncio.run(_empty_connector()) == {"status": "ok", "events": [], "errors": []}


def test_plus_days_desbordamiento_es_400_no_500():
    with pytest.raises(HTTPException) as exc:
        _plus_days(date(9999, 12, 31), 1)
    assert exc.value.status_code == 400


def test_resolve_range_por_defecto_siete_dias():
    start, end = _resolve_range(date(2026, 3, 1), None)
    assert (end - start).days == 7


def test_resolve_range_invertido_es_400():
    with pytest.raises(HTTPException) as exc:
        _resolve_range(date(2026, 3, 10), date(2026, 3, 1))
    assert exc.value.status_code == 400


def test_resolve_range_por_encima_del_maximo_es_400():
    with pytest.raises(HTTPException) as exc:
        _resolve_range(date(2026, 3, 1), date(2026, 12, 31))
    assert exc.value.status_code == 400
    assert "31" in exc.value.detail


# --- /earnings y /dividends ---------------------------------------------


def test_earnings_delega_en_el_conector(monkeypatch):
    llamadas = {}

    async def fake(start, end):
        llamadas["rango"] = (start, end)
        return {"status": "ok", "events": [], "errors": []}

    monkeypatch.setattr(earnings_connector, "fetch_earnings_range", fake)
    out = asyncio.run(earnings_calendar(desde=date(2026, 3, 1), hasta=date(2026, 3, 5)))
    assert out["status"] == "ok"
    assert llamadas["rango"] == (date(2026, 3, 1), date(2026, 3, 5))


def test_earnings_error_de_conector_es_400(monkeypatch):
    async def fake(start, end):
        raise ValueError("rango no soportado")

    monkeypatch.setattr(earnings_connector, "fetch_earnings_range", fake)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(earnings_calendar(desde=date(2026, 3, 1), hasta=date(2026, 3, 5)))
    assert exc.value.status_code == 400


def test_dividends_delega_en_el_conector(monkeypatch):
    async def fake(start, end):
        return {"status": "partial", "events": [{"ticker": "AAPL"}], "errors": ["timeout"]}

    monkeypatch.setattr(earnings_connector, "fetch_dividends_range", fake)
    out = asyncio.run(dividends_calendar(desde=date(2026, 3, 1), hasta=date(2026, 3, 5)))
    # El fallo del proveedor se declara en status, nunca 5xx.
    assert out["status"] == "partial"
    assert out["errors"] == ["timeout"]


# --- /followed y /portfolio-upcoming ------------------------------------


def test_followed_rango_invertido_es_400(db):
    with pytest.raises(HTTPException) as exc:
        followed_earnings_calendar(desde=date(2026, 3, 10), hasta=date(2026, 3, 1), db=db)
    assert exc.value.status_code == 400


def test_followed_rango_largo_es_400(db):
    with pytest.raises(HTTPException) as exc:
        followed_earnings_calendar(desde=date(2026, 1, 1), hasta=date(2027, 6, 1), db=db)
    assert exc.value.status_code == 400


def test_followed_delega_en_el_servicio(db, monkeypatch):
    import app.services.earnings_dates_service as eds

    capturado = {}

    def fake_calendar(db_, start, end):
        capturado["rango"] = (start, end)
        return {"days": []}

    monkeypatch.setattr(eds, "followed_calendar", fake_calendar)
    out = followed_earnings_calendar(desde=date(2026, 3, 1), hasta=date(2026, 3, 10), db=db)
    assert out == {"days": []}
    assert capturado["rango"] == (date(2026, 3, 1), date(2026, 3, 10))


def test_portfolio_upcoming_delega_en_el_servicio(db, monkeypatch):
    import app.services.earnings_dates_service as eds

    monkeypatch.setattr(eds, "portfolio_upcoming", lambda db_, start, end: {"items": []})
    out = portfolio_upcoming_dates(desde=date(2026, 3, 1), hasta=date(2026, 3, 10), db=db)
    assert out == {"items": []}


def test_portfolio_upcoming_rango_invertido_es_400(db):
    with pytest.raises(HTTPException) as exc:
        portfolio_upcoming_dates(desde=date(2026, 3, 10), hasta=date(2026, 3, 1), db=db)
    assert exc.value.status_code == 400


# --- /followed/materials -------------------------------------------------


def test_followed_materials_solo_eventos_confirmados(db, monkeypatch):
    import app.services.connectors.sec as sec_mod
    import app.services.earnings_dates_service as eds
    import app.services.earnings_materials_service as ems

    monkeypatch.setattr(
        eds,
        "followed_calendar",
        lambda db_, start, end: {
            "days": [
                {
                    "events": [
                        {"ticker": "AAPL", "confirmed": True},
                        {"ticker": "MSFT", "confirmed": None},
                    ]
                }
            ]
        },
    )
    vistos = {}

    async def fake_materials(events, today, *, sec):
        vistos["events"] = events
        return {"AAPL|x": {"ok": True}}

    monkeypatch.setattr(ems, "materials_for_events", fake_materials)
    monkeypatch.setattr(sec_mod, "SECClient", lambda: SimpleNamespace())
    out = asyncio.run(followed_materials(db=db))
    # Solo el evento confirmado pasa a buscar materiales.
    assert [e["ticker"] for e in vistos["events"]] == ["AAPL"]
    assert out["items"] == {"AAPL|x": {"ok": True}}
    assert out["as_of"]


# --- /catalysts ----------------------------------------------------------


def _fake_catalyst_common(monkeypatch, held, held_us, watch_us, watch_all):
    monkeypatch.setattr(catalyst_service, "held_tickers", lambda db_: (held, held_us))
    monkeypatch.setattr(catalyst_service, "watchlist_us_tickers", lambda db_, us: watch_us)
    monkeypatch.setattr(catalyst_service, "watchlist_tickers", lambda db_, h: watch_all)
    monkeypatch.setattr(catalyst_service, "pending_actions", lambda db_, s, e: [])
    monkeypatch.setattr(catalyst_service, "upcoming_dividend_records", lambda db_, t, s, e: [])


def test_catalysts_sin_cartera_ni_watchlist_devuelve_ceros(db, monkeypatch):
    _fake_catalyst_common(monkeypatch, set(), set(), set(), set())
    out = asyncio.run(catalysts_calendar(desde=date(2026, 3, 1), hasta=date(2026, 3, 14), db=db))
    assert out["status"] == "ok"
    assert out["count"] == 0
    assert out["events"] == []
    assert out["held_count"] == 0 and out["watchlist_count"] == 0


def test_catalysts_con_us_cruza_conectores(db, monkeypatch):
    _fake_catalyst_common(monkeypatch, {"AAPL"}, {"AAPL"}, set(), set())
    monkeypatch.setattr(
        catalyst_service,
        "build_catalysts",
        lambda **kw: [{"date": "2026-03-05", "type": "earnings", "ticker": "AAPL"}],
    )

    async def fake_earnings(start, end):
        return {"status": "ok", "events": [], "errors": []}

    async def fake_dividends(start, end):
        return {"status": "ok", "events": [], "errors": []}

    async def fake_filings(tickers, start, end, budget_seconds):
        return {
            "status": "ok",
            "events": [{"date": "2026-03-06", "type": "filing_deadline", "ticker": "AAPL"}],
            "errors": [],
        }

    monkeypatch.setattr(earnings_connector, "fetch_earnings_range", fake_earnings)
    monkeypatch.setattr(earnings_connector, "fetch_dividends_range", fake_dividends)
    monkeypatch.setattr(catalyst_service, "fetch_filing_deadlines", fake_filings)
    out = asyncio.run(catalysts_calendar(desde=date(2026, 3, 1), hasta=date(2026, 3, 14), db=db))
    assert out["count"] == 2
    # Ordenado por fecha y luego por tipo.
    assert [e["type"] for e in out["events"]] == ["earnings", "filing_deadline"]
    assert out["held_count"] == 1


def test_catalysts_sin_us_no_llama_a_los_conectores(db, monkeypatch):
    _fake_catalyst_common(monkeypatch, {"SAN.MC"}, set(), set(), set())
    monkeypatch.setattr(catalyst_service, "build_catalysts", lambda **kw: [])
    llamadas = []

    async def fake_earnings(start, end):
        llamadas.append("earnings")
        return {"status": "ok", "events": [], "errors": []}

    monkeypatch.setattr(earnings_connector, "fetch_earnings_range", fake_earnings)
    monkeypatch.setattr(earnings_connector, "fetch_dividends_range", fake_earnings)
    out = asyncio.run(catalysts_calendar(desde=date(2026, 3, 1), hasta=date(2026, 3, 14), db=db))
    # Sin posiciones US no se pregunta a NASDAQ/EDGAR.
    assert llamadas == []
    assert out["status"] == "ok"
    assert out["count"] == 0


# --- /ipos ----------------------------------------------------------------


def test_ipos_cubre_mes_actual_y_siguiente(monkeypatch):
    meses = {}

    async def fake(months):
        meses["n"] = len(months)
        return {"status": "ok", "ipos": []}

    monkeypatch.setattr(ipo_connector, "fetch_ipo_calendar", fake)
    out = asyncio.run(ipo_calendar())
    assert out["status"] == "ok"
    assert meses["n"] == ipo_connector.DEFAULT_MONTHS


# --- feed ICS --------------------------------------------------------------


def test_feed_state_sin_suscripcion():
    assert _feed_state(None) == {
        "active": False,
        "scope": None,
        "created_at": None,
        "last_used_at": None,
    }


def test_feed_status_delega_en_el_servicio(db, monkeypatch):
    import app.services.calendar_feed_service as cfs

    row = SimpleNamespace(
        scope="watchlist",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_used_at=None,
    )
    monkeypatch.setattr(cfs, "active_token", lambda db_: row)
    out = calendar_feed_status(db=db)
    assert out["active"] is True
    assert out["scope"] == "watchlist"
    assert "token" not in out  # el estado nunca revela el token


def test_feed_create_scope_invalido_es_422(db):
    with pytest.raises(HTTPException) as exc:
        calendar_feed_create(FeedCreate(scope="todo"), db=db)
    assert exc.value.status_code == 422


def test_feed_create_devuelve_el_token_una_vez(db, monkeypatch):
    import app.services.calendar_feed_service as cfs

    row = SimpleNamespace(
        scope="followed",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_used_at=None,
    )
    monkeypatch.setattr(cfs, "create_token", lambda db_, scope: ("gfc_secreto", row))
    out = calendar_feed_create(FeedCreate(scope="followed"), db=db)
    assert out["token"] == "gfc_secreto"
    assert out["path"] == "/api/calendar/feed/gfc_secreto.ics"
    assert out["active"] is True


def test_feed_revoke_devuelve_cuantos(db, monkeypatch):
    import app.services.calendar_feed_service as cfs

    monkeypatch.setattr(cfs, "revoke_tokens", lambda db_: 2)
    assert calendar_feed_revoke(db=db) == {"revoked": 2}


def test_feed_publico_nombre_mal_formado_es_404():
    with pytest.raises(HTTPException) as exc:
        calendar_feed_public("sin-prefijo.ics")
    assert exc.value.status_code == 404


def test_feed_publico_token_desconocido_es_404(monkeypatch):
    import app.services.calendar_feed_service as cfs

    monkeypatch.setattr(cfs, "feed_for_token", lambda db_, token: None)
    with pytest.raises(HTTPException) as exc:
        calendar_feed_public("gfc_desconocido.ics")
    assert exc.value.status_code == 404


def test_feed_publico_devuelve_ics_con_cabeceras(monkeypatch):
    import app.services.calendar_feed_service as cfs

    monkeypatch.setattr(cfs, "feed_for_token", lambda db_, token: "BEGIN:VCALENDAR\nEND:VCALENDAR")
    resp = calendar_feed_public("gfc_valido.ics")
    assert resp.media_type == "text/calendar; charset=utf-8"
    assert resp.headers["X-Robots-Tag"] == "noindex"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
