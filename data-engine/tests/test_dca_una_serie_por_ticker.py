"""Rendimiento: la evaluacion DCA calcula la serie mensual UNA vez por ticker.

Veredicto actual, tabla de aciertos y visitas a la zona de compra salen de
la misma ``evaluate_series`` (mismas barras, parametros y fecha); antes se
recalculaba tres veces. Se fija el numero de llamadas y que el resultado
guardado es el mismo que con el calculo por separado.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.entities import DcaSignalState
from app.services import dca_signal_engine as engine
from app.services import dca_signal_service as svc
from tests.test_dca_signal_service import (  # noqa: F401  (fixture db)
    PARAMS,
    FakeFetcher,
    _company,
    _run,
    _watch,
    db,
    series,
)


def test_evaluate_series_una_vez_por_ticker_y_mismo_resultado(db, monkeypatch):
    _company(db, "UBER")
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    rows = series(60.0, months=40)
    fetcher.set("UBER", rows)

    calls: list[int] = []
    real = engine.evaluate_series

    def _counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "evaluate_series", _counting)
    monkeypatch.setattr(svc, "evaluate_series", _counting)
    _run(db, fetcher)

    assert len(calls) == 1
    state = db.scalar(select(DcaSignalState).where(DcaSignalState.symbol == "UBER"))
    assert state is not None
    bars, _factor = svc.build_bars(rows)
    today = date(2026, 10, 27)
    expected = engine.hit_rates(bars, params=PARAMS, today=today)
    expected["zone_visits"] = engine.zone_visits(bars, params=PARAMS, today=today)
    assert state.hit_rates == expected
    verdict = engine.current_verdict(bars, params=PARAMS, today=today)
    assert verdict is not None
    assert (state.level, state.period, state.status) == (verdict.level, verdict.period, verdict.status)
