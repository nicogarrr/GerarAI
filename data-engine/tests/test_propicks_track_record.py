"""Track record ProPicks ("Ganadores anteriores") desde propick_snapshots."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.models import MarketPrice
from app.models.benchmark_price import BenchmarkPrice
from app.models.propick_snapshot import PropickSnapshot
from app.services.propicks_track_record_service import (
    build_track_record,
    ingest_spy_prices,
)
from tests.test_propicks_funnel import _company, _db

TODAY = date(2026, 10, 19)


def _snapshot(db, month: str, as_of: datetime, picks: list[dict]) -> PropickSnapshot:
    row = PropickSnapshot(
        month=month,
        as_of=as_of,
        funnel_version="test-v1",
        universe_size=10,
        passed_count=len(picks),
        payload={"params": {}, "picks": picks},
    )
    db.add(row)
    db.flush()
    return row


def _price(db, company, day: date, close: str) -> None:
    db.add(
        MarketPrice(
            company_id=company.id,
            date=day,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            adj_close=Decimal(close),
            volume=100,
            source="yfinance",
        )
    )


def _spy(db, day: date, close: str) -> None:
    db.add(
        BenchmarkPrice(
            symbol="SPY", date=day, close=Decimal(close), adj_close=Decimal(close), source="yfinance"
        )
    )


def _seed_two_months(db):
    win = _company("WIN")
    out = _company("OUT")
    db.add_all([win, out])
    db.flush()
    # Precio de entrada congelado en el snapshot de septiembre (fecha 2026-09-30).
    _snapshot(
        db,
        "2026-09",
        datetime(2026, 10, 1, tzinfo=UTC),
        [
            {"ticker": "WIN", "name": "WIN Co", "currency": "USD", "score": 80, "price": 100.0, "price_date": "2026-09-30"},
            {"ticker": "OUT", "name": "OUT Co", "currency": "USD", "score": 70, "price": 50.0, "price_date": "2026-09-30"},
        ],
    )
    # En octubre OUT sale del snapshot; WIN se mantiene.
    _snapshot(
        db,
        "2026-10",
        datetime(2026, 10, 19, tzinfo=UTC),
        [
            {"ticker": "WIN", "name": "WIN Co", "currency": "USD", "score": 82, "price": 110.0, "price_date": "2026-10-16"},
        ],
    )
    _price(db, win, date(2026, 10, 16), "120")
    _price(db, out, date(2026, 10, 16), "60")
    _price(db, out, date(2026, 10, 18), "55")
    for d, c in [(date(2026, 9, 30), "500"), (date(2026, 10, 16), "510"), (date(2026, 10, 18), "520")]:
        _spy(db, d, c)
    db.commit()
    return win, out


def test_empty_when_no_snapshots():
    with _db() as db:
        out = build_track_record(db, today=TODAY)
        assert out["snapshots_count"] == 0
        assert out["picks"] == []
        assert out["spy"]["available"] is False
        assert "sin snapshots" in out["history_label"]


def test_active_pick_tracks_entry_current_and_spy():
    with _db() as db:
        _seed_two_months(db)
        out = build_track_record(db, today=TODAY)
        assert out["snapshots_count"] == 2
        assert out["history_label"] == "2 meses de historial"
        win = next(p for p in out["picks"] if p["ticker"] == "WIN" and p["entry_month"] == "2026-09")
        assert win["status"] == "activo"
        assert win["entry_price"] == 100.0 and win["entry_price_date"] == "2026-09-30"
        assert win["current_price"] == 120.0 and win["current_price_date"] == "2026-10-16"
        assert win["current_stale"] is False
        assert abs(win["pct_since_entry"] - 0.20) < 1e-9
        # SPY 500 -> 510 en la misma ventana (+2%).
        assert abs(win["spy_pct_since_entry"] - 0.02) < 1e-9
        # Horizonte 90 dias aun no cumplido: columna vacia honesta.
        assert win["pct_90d"] is None and win["horizon_date"] == "2026-12-29"
        # El pick del segundo snapshot aun no tiene retorno medible propio.
        win_oct = next(p for p in out["picks"] if p["ticker"] == "WIN" and p["entry_month"] == "2026-10")
        assert win_oct["entry_price"] == 110.0
        assert abs(win_oct["pct_since_entry"] - (120 / 110 - 1)) < 1e-9


def test_exit_when_pick_drops_out_of_next_snapshot():
    with _db() as db:
        _seed_two_months(db)
        out = build_track_record(db, today=TODAY)
        out_row = next(p for p in out["picks"] if p["ticker"] == "OUT")
        assert out_row["status"] == "salio"
        assert out_row["exit_month"] == "2026-10"
        # Precio de salida = ultimo cierre a fecha del as_of del snapshot de salida.
        assert out_row["exit_price"] == 55.0 and out_row["exit_price_date"] == "2026-10-18"
        assert abs(out_row["exit_pct"] - 0.10) < 1e-9
        assert abs(out_row["spy_pct_exit"] - 0.04) < 1e-9
        # Un pick salido no compara contra el precio de hoy.
        assert out_row["pct_since_entry"] is None and out_row["current_price"] is None


def test_stale_price_is_reported_as_no_current_data():
    with _db() as db:
        win, _out = _seed_two_months(db)
        # El ultimo cierre de WIN envejece mas alla del umbral de 7 dias.
        for row in db.query(MarketPrice).filter_by(company_id=win.id).all():
            row.date = date(2026, 10, 1)
        db.commit()
        out = build_track_record(db, today=TODAY)
        win_row = next(p for p in out["picks"] if p["ticker"] == "WIN" and p["entry_month"] == "2026-09")
        assert win_row["current_stale"] is True
        assert win_row["current_price"] is None
        assert win_row["current_price_date"] == "2026-10-01"
        assert win_row["pct_since_entry"] is None


def test_horizon_90d_uses_price_at_fixed_date():
    with _db() as db:
        old = _company("OLD")
        db.add(old)
        db.flush()
        _snapshot(
            db,
            "2026-06",
            datetime(2026, 6, 30, tzinfo=UTC),
            [{"ticker": "OLD", "name": "OLD Co", "currency": "USD", "score": 75, "price": 80.0, "price_date": "2026-06-29"}],
        )
        _price(db, old, date(2026, 9, 26), "88")  # cierre en la ventana del dia 90 (2026-09-27)
        _price(db, old, date(2026, 10, 16), "96")
        _spy(db, date(2026, 6, 29), "500")
        _spy(db, date(2026, 9, 26), "550")
        db.commit()
        out = build_track_record(db, today=TODAY)
        (row,) = out["picks"]
        assert row["horizon_date"] == "2026-09-27"
        assert abs(row["pct_90d"] - 0.10) < 1e-9
        assert abs(row["spy_pct_90d"] - 0.10) < 1e-9


def test_ingest_spy_prices_upserts_bars():
    from app.services.propicks_price_service import PriceBar

    bars = [
        PriceBar(day=date(2026, 10, 16), close=Decimal("510"), adj_close=Decimal("509"), volume=1),
        PriceBar(day=date(2026, 10, 17), close=Decimal("512"), adj_close=Decimal("511"), volume=1),
    ]
    with _db() as db:
        result = ingest_spy_prices(db, fetcher=lambda symbols, period="1y": {"SPY": bars})
        assert result["status"] == "ok" and result["bars_written"] == 2
        assert result["latest_date"] == "2026-10-17"
        # Reingesta idempotente: mismas fechas, filas actualizadas, no duplicadas.
        bars2 = [PriceBar(day=date(2026, 10, 17), close=Decimal("513"), adj_close=Decimal("513"), volume=1)]
        ingest_spy_prices(db, fetcher=lambda symbols, period="1y": {"SPY": bars2})
        stored = db.query(BenchmarkPrice).filter_by(symbol="SPY", date=date(2026, 10, 17)).all()
        assert len(stored) == 1 and float(stored[0].close) == 513.0


def test_split_between_entry_and_now_is_not_a_crash():
    """Split 4:1 tras la entrada: el cierre sin ajustar cae de 400 a 110.

    Entrada congelada 400 (2026-09-30); tras el split Yahoo reescribe el
    adj_close de esa fecha a 100. Hoy cierra 110 (adj 110). Rentabilidad real
    = 110/100 - 1 = +10 %; con cierres sin ajustar salia 110/400 - 1 = -72,5 %.
    """
    with _db() as db:
        split = _company("SPLT")
        db.add(split)
        db.flush()
        _snapshot(
            db,
            "2026-10",
            datetime(2026, 10, 1, tzinfo=UTC),
            [{"ticker": "SPLT", "name": "Split Co", "currency": "USD", "score": 75, "price": 400.0, "price_date": "2026-09-30"}],
        )
        for day, close, adj in [(date(2026, 9, 30), "400", "100"), (date(2026, 10, 16), "110", "110")]:
            db.add(
                MarketPrice(
                    company_id=split.id, date=day, open=Decimal(close), high=Decimal(close),
                    low=Decimal(close), close=Decimal(close), adj_close=Decimal(adj),
                    volume=100, source="yfinance",
                )
            )
        for d, c in [(date(2026, 9, 30), "500"), (date(2026, 10, 16), "510")]:
            _spy(db, d, c)
        db.commit()
        out = build_track_record(db, today=TODAY)
        pick = next(p for p in out["picks"] if p["ticker"] == "SPLT")
        assert pick["status"] == "activo"
        assert pick["current_price"] == 110.0
        assert abs(pick["pct_since_entry"] - 0.10) < 1e-9
        assert abs(pick["spy_pct_since_entry"] - 0.02) < 1e-9


def test_track_record_batches_market_price_reads():
    """Perf: build_track_record hacia hasta ~5 SELECTs a market_prices por pick
    (salida/actual/horizonte/entrada). Medido en el barrido 2026-10-31: 855 ms
    el endpoint. La precarga por lotes deja los SELECTs a market_prices en 1
    (constante, no crece con picks x meses)."""
    from sqlalchemy import event

    with _db() as db:
        _seed_two_months(db)
        engine = db.get_bind()
        statements: list[str] = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if "market_prices" in statement:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = build_track_record(db, today=TODAY)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        assert result["picks"], "fixture vacio"
        assert len(statements) <= 2, (
            f"N+1: {len(statements)} SELECTs a market_prices "
            f"(esperado <= 2 con precarga por lotes)"
        )
