"""Track record Pro Picks: un pick que sigue un mes y sale despues ya no figura como activo."""

from datetime import UTC, date, datetime

from app.services.propicks_track_record_service import build_track_record
from tests.test_propicks_funnel import _company, _db
from tests.test_propicks_track_record import _price, _snapshot, _spy

TODAY = date(2026, 11, 20)


def _pick(price: float, price_date: str) -> dict:
    return {"ticker": "WIN", "name": "WIN Co", "currency": "USD", "score": 80, "price": price, "price_date": price_date}


def test_pick_que_sigue_un_mes_y_sale_despues_figura_como_salido():
    with _db() as db:
        win = _company("WIN")
        other = _company("KEEP")
        db.add_all([win, other])
        db.flush()
        _snapshot(db, "2026-09", datetime(2026, 10, 1, tzinfo=UTC), [_pick(100.0, "2026-09-30")])
        _snapshot(db, "2026-10", datetime(2026, 11, 1, tzinfo=UTC), [_pick(110.0, "2026-10-31")])
        # En noviembre WIN ya no esta: salio con el snapshot de noviembre.
        _snapshot(
            db,
            "2026-11",
            datetime(2026, 11, 18, tzinfo=UTC),
            [{"ticker": "KEEP", "name": "KEEP Co", "currency": "USD", "score": 75, "price": 10.0, "price_date": "2026-11-17"}],
        )
        _price(db, win, date(2026, 11, 17), "130")
        _price(db, win, date(2026, 11, 19), "90")
        for d, c in [(date(2026, 9, 30), "500"), (date(2026, 10, 31), "520"), (date(2026, 11, 17), "550")]:
            _spy(db, d, c)
        db.commit()

        out = build_track_record(db, today=TODAY)
        rows = {p["entry_month"]: p for p in out["picks"] if p["ticker"] == "WIN"}
        assert set(rows) == {"2026-09", "2026-10"}
        for month in ("2026-09", "2026-10"):
            row = rows[month]
            assert row["status"] == "salio", month
            assert row["exit_month"] == "2026-11"
            assert row["exit_price"] == 130.0 and row["exit_price_date"] == "2026-11-17"
            # Un pick salido no se compara con el precio de hoy.
            assert row["current_price"] is None and row["pct_since_entry"] is None
        assert abs(rows["2026-09"]["exit_pct"] - 0.30) < 1e-9
        assert abs(rows["2026-09"]["spy_pct_exit"] - 0.10) < 1e-9


def test_pick_que_sigue_en_todos_los_meses_sigue_activo():
    with _db() as db:
        win = _company("WIN")
        db.add(win)
        db.flush()
        _snapshot(db, "2026-09", datetime(2026, 10, 1, tzinfo=UTC), [_pick(100.0, "2026-09-30")])
        _snapshot(db, "2026-10", datetime(2026, 11, 1, tzinfo=UTC), [_pick(110.0, "2026-10-31")])
        _snapshot(db, "2026-11", datetime(2026, 11, 18, tzinfo=UTC), [_pick(130.0, "2026-11-17")])
        _price(db, win, date(2026, 11, 19), "120")
        db.commit()

        out = build_track_record(db, today=TODAY)
        rows = [p for p in out["picks"] if p["ticker"] == "WIN"]
        assert len(rows) == 3
        assert all(r["status"] == "activo" and r["exit_month"] is None for r in rows)
        sep = next(r for r in rows if r["entry_month"] == "2026-09")
        assert abs(sep["pct_since_entry"] - 0.20) < 1e-9
