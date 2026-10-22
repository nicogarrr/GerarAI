"""Repro de fallos de ingesta del refresco de fechas de resultados (22 oct 2026).

Sintoma en prod: /calendar/resultados con casi todos los tickers "sin fecha"
aunque hay fechas anunciadas. Estas pruebas reproducen dos caminos de codigo
por los que el refresco deja de escribir filas para TODOS los tickers.
"""
from datetime import UTC, date, datetime

import pytest

from app.core.database import SessionLocal, init_db
from app.models import EarningsDate
from app.services.earnings_dates_service import followed_calendar, refresh_earnings_dates
from tests.test_earnings_dates_service import _tenant_with_watch

TODAY = date(2026, 10, 19)
YESTERDAY = date(2026, 10, 18)
FUTURE = date(2026, 11, 20)


def test_repro_past_candidate_duplicates_existing_row_and_kills_run():
    """Yahoo aun da la fecha ya pasada: el refresco inserta un duplicado
    (ticker, event_date, source) y el commit revienta -> no se escribe NADA,
    ni siquiera las fechas futuras de otros tickers."""
    init_db()
    db = SessionLocal()
    try:
        n = _tenant_with_watch(db, ["ZPA", "ZPB"])
        db.add(EarningsDate(ticker=n["ZPA"], event_date=YESTERDAY, source="yahoo",
                            source_label="Yahoo", confirmed=True,
                            fetched_at=datetime(2026, 10, 17, 12, tzinfo=UTC)))
        db.commit()
        yahoo = {
            n["ZPA"]: {"date": YESTERDAY, "estimate": False},  # proveedor aun sin actualizar
            n["ZPB"]: {"date": FUTURE, "estimate": False},
        }
        refresh_earnings_dates(db, today=TODAY,
                               yahoo_fetcher=lambda syms: yahoo,
                               nasdaq_fetcher=lambda t, today: {})
        # El refresco completo NO debe fallar: ZPB debe quedar escrito.
        rows = db.query(EarningsDate).filter(EarningsDate.ticker == n["ZPB"]).all()
        assert len(rows) == 1 and rows[0].event_date == FUTURE
    finally:
        db.rollback()
        db.close()


def test_repro_past_candidate_destroys_existing_future_row():
    """Si el proveedor devuelve una fecha pasada para un ticker que tiene una
    futura ya guardada, el delete(>= hoy) borra la futura y la fecha buena se pierde."""
    init_db()
    db = SessionLocal()
    try:
        n = _tenant_with_watch(db, ["ZPC"])
        db.add(EarningsDate(ticker=n["ZPC"], event_date=FUTURE, source="yahoo",
                            source_label="Yahoo", confirmed=False,
                            fetched_at=datetime(2026, 10, 17, 12, tzinfo=UTC)))
        db.commit()
        refresh_earnings_dates(
            db, today=TODAY,
            yahoo_fetcher=lambda syms: {n["ZPC"]: {"date": YESTERDAY, "estimate": False}},
            nasdaq_fetcher=lambda t, today: {},
        )
        cal = followed_calendar(db, TODAY, date(2026, 12, 31),
                                now=datetime(2026, 10, 19, 12, tzinfo=UTC))
        upcoming = [e["date"] for d in cal["days"] for e in d["events"]
                    if e["ticker"] == n["ZPC"] and e["date"] >= TODAY.isoformat()]
        assert upcoming == [FUTURE.isoformat()], "la fecha futura vigente no debe perderse"
    finally:
        db.rollback()
        db.close()


def test_repro_nasdaq_outage_discards_yahoo_results():
    """Un fallo que ESCAPA del fetcher de NASDAQ (p.ej. asyncio.run) tumba el
    refresco entero y tira los resultados que Yahoo si devolvio."""
    init_db()
    db = SessionLocal()
    try:
        n = _tenant_with_watch(db, ["ZPD"])
        def boom(tickers, today):
            raise RuntimeError("nasdaq client construction failed")
        refresh_earnings_dates(
            db, today=TODAY,
            yahoo_fetcher=lambda syms: {n["ZPD"]: {"date": FUTURE, "estimate": False}},
            nasdaq_fetcher=boom,
        )
        rows = db.query(EarningsDate).filter(EarningsDate.ticker == n["ZPD"]).all()
        assert len(rows) == 1 and rows[0].event_date == FUTURE
    finally:
        db.rollback()
        db.close()
