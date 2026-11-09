"""Precio actual (premercado/sesión/post) en el periodo DCA en formación.

El dato entra SOLO como cierre provisional del periodo en curso, etiquetado
``close_kind="live"``: nunca toca periodos confirmados, hit_rates ni los
umbrales, y si falta o no es fiable la fórmula sigue con cierres y avisa.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.dca_signal_engine import (
    DailyBar,
    current_verdict,
    evaluate_series,
    hit_rates,
)
from app.services.dca_watch_card import (
    MAX_LIVE_DEVIATION,
    build_watch_card,
    usable_current_price,
)
from tests.test_dca_watch_card import RISE_THEN_CRASH, _bars

TODAY = date(2026, 11, 9)  # lunes; la serie de pruebas termina el viernes 6
_LIVE_TS = int(datetime(2026, 11, 9, 13, 30, tzinfo=UTC).timestamp())  # 08:30 ET, premercado


def _series_ending_last_friday() -> list[DailyBar]:
    """Serie realista cuyo último cierre asentado es el viernes anterior a TODAY."""
    bars = _bars(RISE_THEN_CRASH, start=date(2020, 1, 6))
    # Recoloca la serie para que termine el 2026-11-06 conservando la forma.
    shift = (TODAY - timedelta(days=3)) - bars[-1].day
    return [DailyBar(day=b.day + shift, close=b.close, low=b.low) for b in bars]


def test_live_price_substitutes_forming_close_and_is_labelled():
    bars = _series_ending_last_friday()
    settled = current_verdict(bars, today=TODAY)
    live_price = settled.close * 0.90
    live = current_verdict(bars, today=TODAY, current_price=live_price)
    assert settled.close_kind == "close" and settled.signal_date == bars[-1].day
    assert live.close_kind == "live" and live.signal_date == TODAY
    assert live.close == pytest.approx(live_price)
    assert live.status == "forming" and live.period == settled.period
    # El drawdown se profundiza con el precio actual y los umbrales no se mueven.
    assert live.metrics["drawdown"] > settled.metrics["drawdown"]
    assert live.level_prices == settled.level_prices


def test_live_price_never_touches_confirmed_periods_or_hit_rates():
    bars = _series_ending_last_friday()
    settled_series = evaluate_series(bars, today=TODAY)
    live_series = evaluate_series(bars, today=TODAY, current_price=bars[-1].close * 0.80)
    assert len(live_series) == len(settled_series)
    for before, after in zip(settled_series[:-1], live_series[:-1], strict=True):
        assert before == after  # confirmados bit a bit idénticos
    assert hit_rates(bars, today=TODAY, verdicts=live_series) == hit_rates(bars, today=TODAY, verdicts=settled_series)


def test_live_price_opens_new_forming_period_on_period_boundary():
    bars = _series_ending_last_friday()
    next_month = date(2026, 12, 1)  # la historia llega a noviembre; hoy es diciembre
    live_price = bars[-1].close * 0.95
    verdict = current_verdict(bars, today=next_month, current_price=live_price)
    assert verdict.period == "2026-12"
    assert verdict.status == "forming" and verdict.close_kind == "live"
    assert verdict.close == pytest.approx(live_price)
    # Sin precio actual ese día, el último mes queda confirmado con su cierre.
    settled = current_verdict(bars, today=next_month)
    assert settled.period == "2026-11" and settled.status == "confirmed"


@pytest.mark.parametrize("bad", [None, 0.0, -10.0, math.nan, math.inf, True])
def test_invalid_live_price_is_ignored(bad):
    bars = _series_ending_last_friday()
    expected = evaluate_series(bars, today=TODAY)
    assert evaluate_series(bars, today=TODAY, current_price=bad) == expected


def test_live_low_extends_touched_level():
    bars = _series_ending_last_friday()
    settled = current_verdict(bars, today=TODAY)
    live = current_verdict(bars, today=TODAY, current_price=settled.close * 0.5)
    assert live.metrics["drawdown"] > 0.4
    assert live.level >= settled.level


def _quote_kwargs(**overrides):
    base = {
        "status": "available",
        "session": "pre",
        "price_session": "pre",
        "price": 175.75,
        "timestamp": _LIVE_TS,
        "quote_currency": "USD",
        "history_currency": "USD",
        "last_settled_close": 186.64,
        "today": TODAY,
    }
    base.update(overrides)
    return base


def test_usable_current_price_accepts_labelled_live_price():
    price, reason = usable_current_price(**_quote_kwargs())
    assert price == 175.75 and reason is None
    # La sesión la da price_session aunque session diga otra cosa coherente.
    price, reason = usable_current_price(**_quote_kwargs(session="regular"))
    assert price == 175.75 and reason is None


def test_usable_current_price_declines_cleanly():
    assert usable_current_price(**_quote_kwargs(status="unavailable")) == (None, "unavailable")
    assert usable_current_price(**_quote_kwargs(session="cerrado", price_session="regular")) == (None, "closed")
    assert usable_current_price(**_quote_kwargs(price=None)) == (None, "no_price")
    assert usable_current_price(**_quote_kwargs(price=-3.0)) == (None, "no_price")
    friday = int(datetime(2026, 11, 6, 21, 0, tzinfo=UTC).timestamp())
    assert usable_current_price(**_quote_kwargs(timestamp=friday)) == (None, "stale")
    assert usable_current_price(**_quote_kwargs(timestamp=None)) == (None, "stale")
    assert usable_current_price(**_quote_kwargs(quote_currency="EUR")) == (None, "currency_mismatch")
    # Banda de cordura: ±30% frente al último cierre asentado.
    assert usable_current_price(**_quote_kwargs(price=186.64 * (1 - MAX_LIVE_DEVIATION - 0.01))) == (None, "out_of_band")
    price, reason = usable_current_price(**_quote_kwargs(price=186.64 * (1 - MAX_LIVE_DEVIATION + 0.01)))
    assert price is not None and reason is None


def test_usable_current_price_fail_closed_on_missing_currency():
    # Sin divisa declarada en cualquiera de los dos lados no se puede
    # descartar una falsa equivalencia: fail-closed, fallback a cierres.
    assert usable_current_price(**_quote_kwargs(quote_currency=None)) == (None, "currency_mismatch")
    assert usable_current_price(**_quote_kwargs(history_currency=None)) == (None, "currency_mismatch")
    assert usable_current_price(**_quote_kwargs(quote_currency=None, history_currency=None)) == (None, "currency_mismatch")


def test_usable_current_price_respects_price_session():
    # Sesión actual abierta pero el print seleccionado es de fuera de horario:
    # no es un precio actual aunque session diga "pre".
    assert usable_current_price(**_quote_kwargs(price_session="cerrado")) == (None, "closed")
    # price_session desconocido (None) no bloquea: no afirma nada del print.
    price, reason = usable_current_price(**_quote_kwargs(price_session=None))
    assert price == 175.75 and reason is None


def test_usable_current_price_out_of_range_timestamp_falls_back():
    # Epoch fuera de rango no lanza OverflowError: fallback a cierres con aviso.
    assert usable_current_price(**_quote_kwargs(timestamp=10**20)) == (None, "stale")
    assert usable_current_price(**_quote_kwargs(timestamp=-10**20)) == (None, "stale")


def test_usable_current_price_normalizes_subunit_currencies():
    price, reason = usable_current_price(**_quote_kwargs(quote_currency="GBX", history_currency="GBp"))
    assert price == 175.75 and reason is None


def test_card_carries_live_block_and_label():
    bars = _series_ending_last_friday()
    settled_close = bars[-1].close
    live_price = settled_close * 0.9
    live_block = {"used": True, "price": live_price, "session": "pre", "timestamp": _LIVE_TS, "currency": "USD"}
    card = build_watch_card(bars, today=TODAY, current_price=live_price, live=live_block)
    assert card["current"]["close_kind"] == "live"
    assert card["current"]["close"] == pytest.approx(live_price)
    assert card["live"] == live_block
    # Sin precio actual: misma tarjeta con cierres y motivo declarado.
    plain = build_watch_card(bars, today=TODAY, live={"used": False, "reason": "unavailable"})
    assert plain["current"]["close_kind"] == "close"
    assert plain["current"]["close"] == pytest.approx(settled_close)
    assert plain["live"] == {"used": False, "reason": "unavailable"}


def test_route_uses_live_price_when_quote_is_reliable(monkeypatch):
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.api.routes import watchlist as route
    from app.models.entities import Base
    from app.services import dca_signal_service as svc
    from app.services.dca_signal_service import PriceRow
    from app.services.extended_quote_service import ExtendedQuote, extended_quote_service

    now = datetime.now(UTC)
    today_ny = now.astimezone(ZoneInfo("America/New_York")).date()
    bars = _bars(RISE_THEN_CRASH, start=date(2020, 1, 6))
    shift = (today_ny - timedelta(days=3)) - bars[-1].day
    rows = [PriceRow(day=b.day + shift, close=b.close, adj_close=b.close) for b in bars]
    settled_close = rows[-1].close
    live_price = settled_close * 0.9
    monkeypatch.setattr(svc, "fetch_yahoo_history_cached", lambda symbol: SimpleNamespace(rows=rows, currency="USD"))

    async def _quote(ticker):
        return ExtendedQuote(
            ticker=ticker,
            status="available",
            session="pre",
            price_session="pre",
            price=live_price,
            timestamp=int(now.timestamp()),
            currency="USD",
            fetched_at=int(now.timestamp()),
        )

    monkeypatch.setattr(extended_quote_service, "get", _quote)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        out = asyncio.run(route.dca_watch_card("intc", db))
    assert out["live"]["used"] is True and out["live"]["session"] == "pre"
    assert out["live"]["price"] == pytest.approx(live_price)
    assert out["current"]["close_kind"] == "live"
    assert out["current"]["close"] == pytest.approx(live_price)


def test_route_discards_out_of_band_quote_and_warns(monkeypatch):
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.api.routes import watchlist as route
    from app.models.entities import Base
    from app.services import dca_signal_service as svc
    from app.services.dca_signal_service import PriceRow
    from app.services.extended_quote_service import ExtendedQuote, extended_quote_service

    now = datetime.now(UTC)
    today_ny = now.astimezone(ZoneInfo("America/New_York")).date()
    bars = _bars(RISE_THEN_CRASH, start=date(2020, 1, 6))
    shift = (today_ny - timedelta(days=3)) - bars[-1].day
    rows = [PriceRow(day=b.day + shift, close=b.close, adj_close=b.close) for b in bars]
    settled_close = rows[-1].close
    monkeypatch.setattr(svc, "fetch_yahoo_history_cached", lambda symbol: SimpleNamespace(rows=rows, currency="USD"))

    async def _quote(ticker):
        return ExtendedQuote(
            ticker=ticker,
            status="available",
            session="pre",
            price_session="pre",
            price=settled_close * 0.5,  # -50 %: cotización errónea, no crash
            timestamp=int(now.timestamp()),
            currency="USD",
            fetched_at=int(now.timestamp()),
        )

    monkeypatch.setattr(extended_quote_service, "get", _quote)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        out = asyncio.run(route.dca_watch_card("intc", db))
    assert out["live"] == {"used": False, "reason": "out_of_band"}
    assert out["current"]["close_kind"] == "close"
    assert out["current"]["close"] == pytest.approx(settled_close)


# ---------------------------------------------------------------------------
# B2: la senal oficial (job) tambien incorpora el precio actual, etiquetado.
# ---------------------------------------------------------------------------

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.entities import Base, DcaSignalState, Tenant  # noqa: E402
from app.services import dca_signal_service as svc  # noqa: E402
from app.services.dca_signal_service import evaluate_watchlist  # noqa: E402
from tests.test_dca_signal_service import (  # noqa: E402
    NOW,
    PARAMS,
    FakeFetcher,
    _alerts,
    _company,
    _watch,
    series,
)

B2_TODAY = date(2026, 10, 27)
_LIVE_TS_B2 = int(datetime(2026, 10, 27, 13, 30, tzinfo=UTC).timestamp())


def _b2_db(monkeypatch):
    monkeypatch.setenv("DCA_ALERT_MIN_LEVEL", "2")
    monkeypatch.setenv("DCA_ALERT_TRIMS", "false")
    monkeypatch.setenv("DCA_ALERTS_ENABLED", "true")
    monkeypatch.setenv("DCA_ALERT_CHANNELS", "in_app")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Tenant(id=1, external_id="t-dca-live", name="t"))
    session.commit()
    session.info["tenant_id"] = 1
    session.info["user_id"] = "u-1"
    return session


def _quote(status="available", session="pre", price_session="pre", price=74.0, timestamp=_LIVE_TS_B2, currency="USD"):
    return SimpleNamespace(
        status=status, session=session, price_session=price_session,
        price=price, timestamp=timestamp, currency=currency,
    )


def _patch_quotes(monkeypatch, quotes):
    monkeypatch.setattr(svc, "fetch_live_quotes", lambda symbols: quotes)


def _b2_state(db, symbol="AAA"):
    return db.scalar(select(DcaSignalState).where(DcaSignalState.symbol == symbol))


def test_service_persists_live_level_labelled_never_as_close(monkeypatch):
    db = _b2_db(monkeypatch)
    _company(db, "AAA")
    _watch(db, "AAA")
    fetcher = FakeFetcher()
    fetcher.set("AAA", series(85.0))
    _patch_quotes(monkeypatch, {"AAA": _quote(price=74.0)})
    summary = evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=B2_TODAY, params=PARAMS)
    state = _b2_state(db)
    assert state.close_kind == "live"
    assert float(state.live_price) == pytest.approx(74.0)
    assert state.live_session == "pre" and state.live_at is not None
    # Invariante: close y signal_date siguen siendo el cierre asentado.
    assert float(state.close) == pytest.approx(85.0)
    assert state.signal_date == date(2026, 10, 15)
    assert state.level == 3  # dd 26 % con el precio actual; con cierres seria 2X
    assert summary["live_quotes"]["used"] == ["AAA"]
    assert summary["live_quotes"]["missing"] == {}
    db.close()


def test_service_live_alert_discloses_premarket_basis(monkeypatch):
    db = _b2_db(monkeypatch)
    _company(db, "AAA")
    _watch(db, "AAA")
    fetcher = FakeFetcher()
    fetcher.set("AAA", series(85.0))
    # Primera evaluacion con mercado cerrado: siembra el nivel 2X con cierres.
    _patch_quotes(monkeypatch, {"AAA": _quote(session="cerrado", price_session="regular")})
    evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=B2_TODAY, params=PARAMS)
    assert _b2_state(db).level == 2
    # Segunda con premercado: sube a 3X y el aviso declara su base.
    _patch_quotes(monkeypatch, {"AAA": _quote(price=74.0)})
    evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=B2_TODAY, params=PARAMS)
    alerts = _alerts(db)
    assert len(alerts) == 1
    dca = alerts[0].metadata_["dca"]
    assert dca["close_kind"] == "live"
    assert dca["live"]["price"] == pytest.approx(74.0) and dca["live"]["session"] == "pre"
    assert "premercado" in alerts[0].message and "no un cierre" in alerts[0].message
    db.close()


def test_service_clears_live_label_when_market_closes(monkeypatch):
    db = _b2_db(monkeypatch)
    _company(db, "AAA")
    _watch(db, "AAA")
    fetcher = FakeFetcher()
    fetcher.set("AAA", series(85.0))
    _patch_quotes(monkeypatch, {"AAA": _quote(price=84.0)})
    evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=B2_TODAY, params=PARAMS)
    assert _b2_state(db).close_kind == "live"
    _patch_quotes(monkeypatch, {"AAA": _quote(session="cerrado", price_session="regular")})
    summary = evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=B2_TODAY, params=PARAMS)
    state = _b2_state(db)
    assert state.close_kind == "close"
    assert state.live_price is None and state.live_session is None and state.live_at is None
    # Mercado cerrado no es un dato que falte: no se declara missing.
    assert summary["live_quotes"]["missing"] == {}
    db.close()


def test_service_missing_live_price_warns_and_continues_with_closes(monkeypatch):
    db = _b2_db(monkeypatch)
    _company(db, "AAA")
    _watch(db, "AAA")
    fetcher = FakeFetcher()
    fetcher.set("AAA", series(85.0))
    _patch_quotes(monkeypatch, {"AAA": _quote(status="unavailable", session="pre", price=None)})
    summary = evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=B2_TODAY, params=PARAMS)
    state = _b2_state(db)
    assert state is not None and state.close_kind == "close" and state.level == 2
    assert summary["live_quotes"]["missing"] == {"AAA": "unavailable"}
    db.close()


def test_service_out_of_band_live_price_is_discarded_with_warning(monkeypatch):
    db = _b2_db(monkeypatch)
    _company(db, "AAA")
    _watch(db, "AAA")
    fetcher = FakeFetcher()
    fetcher.set("AAA", series(85.0))
    _patch_quotes(monkeypatch, {"AAA": _quote(price=40.0)})  # -53 %: cotizacion erronea
    summary = evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=B2_TODAY, params=PARAMS)
    state = _b2_state(db)
    assert state.close_kind == "close" and float(state.close) == pytest.approx(85.0)
    assert summary["live_quotes"]["missing"] == {"AAA": "out_of_band"}
    db.close()


# fetch_live_quotes REAL: el fixture autouse de conftest dobla el atributo del
# modulo, asi que la referencia se captura en import (antes de cualquier
# monkeypatch) y la capa de red (extended_quote_service.get) es lo doblado.
_REAL_FETCH_LIVE_QUOTES = svc.fetch_live_quotes


def _stub_quote_get(monkeypatch, get_impl):
    from app.services import extended_quote_service as eqs_mod

    monkeypatch.setattr(eqs_mod.extended_quote_service, "get", get_impl)


def test_fetch_live_quotes_returns_quote_per_symbol(monkeypatch):
    from app.services.extended_quote_service import ExtendedQuote

    async def fake_get(ticker):
        return ExtendedQuote(
            ticker=ticker,
            status="available",
            session="pre",
            price_session="pre",
            price=175.75,
            timestamp=_LIVE_TS,
            currency="USD",
            fetched_at=_LIVE_TS,
        )

    _stub_quote_get(monkeypatch, fake_get)
    quotes = _REAL_FETCH_LIVE_QUOTES(["NVDA", "AAPL"])
    assert set(quotes) == {"NVDA", "AAPL"}
    assert quotes["NVDA"].price == 175.75 and quotes["NVDA"].session == "pre"
    assert quotes["AAPL"].ticker == "AAPL"


def test_fetch_live_quotes_maps_unavailable_without_dropping(monkeypatch):
    from app.services.extended_quote_service import ExtendedQuote

    async def fake_get(ticker):
        return ExtendedQuote(ticker=ticker, status="unavailable", fetched_at=_LIVE_TS)

    _stub_quote_get(monkeypatch, fake_get)
    quotes = _REAL_FETCH_LIVE_QUOTES(["NVDA"])
    # El servicio NUNCA lanza: el quote "unavailable" viaja y lo descarta
    # usable_current_price con su motivo, no esta capa.
    assert quotes["NVDA"].status == "unavailable"


def test_fetch_live_quotes_error_falls_back_to_empty(monkeypatch):
    async def fake_get(ticker):
        raise RuntimeError("red caida")

    _stub_quote_get(monkeypatch, fake_get)
    # La pasada entera falla: {} y la evaluacion sigue solo con cierres.
    assert _REAL_FETCH_LIVE_QUOTES(["NVDA"]) == {}


def test_fetch_live_quotes_timeout_falls_back_to_empty(monkeypatch):
    import asyncio

    async def fake_get(ticker):
        await asyncio.sleep(0)
        raise TimeoutError

    _stub_quote_get(monkeypatch, fake_get)
    assert _REAL_FETCH_LIVE_QUOTES(["NVDA", "AAPL"]) == {}


def test_fetch_live_quotes_empty_symbols():
    assert _REAL_FETCH_LIVE_QUOTES([]) == {}


def test_live_time_label_edge_cases():
    from app.services.dca_alert_copy import live_time_label

    # ISO naive: se asume UTC y se muestra en ET.
    assert live_time_label("2026-11-09T13:30:00") == "08:30 ET"
    # datetime con tz aware.
    assert live_time_label(datetime(2026, 11, 9, 12, 30, tzinfo=UTC)) == "07:30 ET"
    # Entrada invalida: cadena vacia, nunca lanza.
    assert live_time_label("no-es-una-fecha") == ""
    assert live_time_label(None) == ""
