"""Hermetic Yahoo extended-hours contracts: no database, no invented dates."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.connectors.yahoo import YahooFinanceClient
from app.services.extended_quote_service import ExtendedQuoteService, parse_extended_chart

START = 1791466200  # 2026-10-08 13:30 UTC, regular US open.


def chart():
    return {
        "meta": {
            "currency": "USD", "exchangeTimezoneName": "America/New_York",
            "previousClose": 100, "regularMarketPrice": 102, "regularMarketTime": START + 23340,
            "currentTradingPeriod": {
                "pre": {"start": START - 19800, "end": START},
                "regular": {"start": START, "end": START + 23400},
                "post": {"start": START + 23400, "end": START + 37800},
            },
        },
        "timestamp": [START - 60, START, START + 23340, START + 23400],
        "indicators": {"quote": [{"close": [101, 101, 102, 103], "open": [100, 100, 101, 102],
                                   "high": [102, 102, 104, 104], "low": [99, 99, 100, 101]}]},
    }


@pytest.mark.parametrize(('now', 'session', 'price'), [
    (START - 30, 'pre', 101), (START + 60, 'regular', 101),
    (START + 23430, 'post', 103), (START + 37800, 'cerrado', 103),
])
def test_sessions(now, session, price):
    q = parse_extended_chart('MSFT', chart(), now)
    assert q.session == session and q.price == price
    assert q.timestamp is not None and q.source.startswith('Yahoo Finance (no oficial)')
    assert q.trading_date == '2026-10-08'
    if session == 'cerrado':
        assert q.change is None and q.change_percent is None
    else:
        assert q.change == price - 100
    if session == 'regular':
        assert q.regular_close is None  # Current intraday price is not a close.


def test_stale_boundary_and_future_points():
    node = chart()
    q = parse_extended_chart('MSFT', node, START + 1200)
    assert q.status == 'available' and q.timestamp == START
    q = parse_extended_chart('MSFT', node, START + 1201)
    assert q.status == 'retrasado' and q.timestamp == START
    assert q.price == 101  # Still a dated delayed quote, never promoted to live.


def test_ohlc_regular_only_and_previous_close_without_date():
    q = parse_extended_chart('MSFT', chart(), START + 24000)
    assert (q.open, q.high, q.low) == (100, None, None)  # Sparse fixture is not complete daily OHLC.
    assert q.metrics_session == '2026-10-08' and q.metrics_timestamp == START + 23340
    assert q.previous_close == 100 and q.previous_close_timestamp is None
    assert q.regular_close == 102 and q.regular_close_timestamp == START + 23340
    node = chart()
    node['meta']['previousCloseTime'] = START - 86400
    q = parse_extended_chart('MSFT', node, START + 24000)
    assert q.previous_close_timestamp == START - 86400


def test_no_timestamp_is_unavailable_not_old_meta_price():
    node = chart()
    node['timestamp'] = []
    node['meta'].pop('regularMarketTime')
    q = parse_extended_chart('MSFT', node, START + 40000)
    assert q.status == 'unavailable' and q.price is None and q.timestamp is None
    q = parse_extended_chart('MSFT', node, START + 60)
    assert q.price is None  # No dated minute candle in an open session.


def test_weekend_dated_meta_fallback_and_missing_bounds():
    node = chart()
    node['timestamp'] = []
    q = parse_extended_chart('MSFT', node, START + 172800)
    assert q.session == 'cerrado' and q.price == 102 and q.timestamp == START + 23340
    assert q.change is None and q.trading_date == '2026-10-08'
    node['meta'].pop('currentTradingPeriod')
    assert parse_extended_chart('MSFT', node, START + 172800).price is None


def test_null_nan_and_missing_ohlc_fail_honestly():
    node = chart()
    node['indicators']['quote'][0]['close'] = [None, float('nan'), -1, None]
    assert parse_extended_chart('MSFT', node, START + 60).price is None
    node = chart()
    node['indicators']['quote'][0]['high'][1] = None
    assert parse_extended_chart('MSFT', node, START + 24000).high is None


def test_cache_60_seconds_reclassifies_and_failure_drops_old_price(monkeypatch):
    clock = {'wall': START + 60, 'mono': 100.0}
    monkeypatch.setattr('app.services.extended_quote_service.time.time', lambda: clock['wall'])
    monkeypatch.setattr('app.services.extended_quote_service.time.monotonic', lambda: clock['mono'])
    service = ExtendedQuoteService()
    service.client.recent_daily_chart = AsyncMock(return_value={})
    service.client.extended_chart = AsyncMock(return_value=deepcopy(chart()))
    first = asyncio.run(service.get('msft'))
    clock['wall'] += 1201
    second = asyncio.run(service.get('MSFT'))
    assert service.client.extended_chart.call_count == 1
    assert second.status == 'retrasado' and second.fetched_at == first.fetched_at
    clock['mono'] += 60
    service.client.extended_chart.side_effect = RuntimeError('Yahoo down')
    failed = asyncio.run(service.get('MSFT'))
    assert failed.status == 'unavailable' and failed.price is None
    assert not service.cache


def test_yahoo_query_contract(monkeypatch):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'chart': {'result': [chart()]}})
    client_type = httpx.AsyncClient
    monkeypatch.setattr('app.services.connectors.yahoo.httpx.AsyncClient',
                        lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs))
    asyncio.run(YahooFinanceClient().extended_chart('MSFT'))
    assert dict(seen[0].url.params) == {'includePrePost': 'true', 'interval': '1m', 'range': '1d'}


def test_endpoint_read_only_no_db(monkeypatch):
    from app.api.routes.companies import router
    app = FastAPI()
    app.include_router(router, prefix='/companies')
    fake = AsyncMock(return_value=parse_extended_chart('MSFT', chart(), START + 60))
    monkeypatch.setattr('app.api.routes.companies.extended_quote_service.get', fake)
    response = TestClient(app).get('/companies/MSFT/extended-quote')
    assert response.status_code == 200 and response.json()['session'] == 'regular'
    route = next(r for r in router.routes if r.path == '/{ticker}/extended-quote')
    assert not route.dependant.dependencies


def test_incomplete_open_and_unknown_timezone_never_invented():
    node = chart()
    node['timestamp'][1] += 60
    assert parse_extended_chart('MSFT', node, START + 24000).open is None
    node['meta'].pop('exchangeTimezoneName')
    assert parse_extended_chart('MSFT', node, START + 24000).price is None


def test_weekend_upcoming_bounds_preserve_dated_post_candle():
    node = chart()
    original = deepcopy(node['meta']['currentTradingPeriod'])
    node['meta']['tradingPeriods'] = {k: [[v]] for k, v in original.items()}
    for period in node['meta']['currentTradingPeriod'].values():
        period['start'] += 4 * 86400
        period['end'] += 4 * 86400
    q = parse_extended_chart('MSFT', node, START + 2 * 86400)
    assert q.session == 'cerrado' and q.price_session == 'post'
    assert q.price == 103 and q.trading_date == '2026-10-08'


def test_exact_audit_missing_first_hour_and_internal_gap():
    node = chart()
    node['timestamp'] = [START + 3600, START + 23340]
    node['indicators']['quote'] = [{'close': [102, 102], 'open': [101, 101], 'high': [103, 104], 'low': [100, 101]}]
    q = parse_extended_chart('MSFT', node, START + 24000)
    assert q.open is None and q.high is None and q.low is None
    # Complete timestamp coverage except one internal minute.
    node = full_regular_chart()
    for series in [node['timestamp'], *node['indicators']['quote'][0].values()]:
        series.pop(30)
    q = parse_extended_chart('MSFT', node, START + 24000)
    assert q.open == 100 and q.high is None and q.low is None


def full_regular_chart():
    node = chart()
    node['timestamp'] = list(range(START, START + 23400, 60))
    node['indicators']['quote'] = [{
        'close': [102] * 390, 'open': [100] * 390,
        'high': [104] * 390, 'low': [99] * 390,
    }]
    return node


def test_complete_coverage_publishes_extrema_and_last_minute_close():
    q = parse_extended_chart('MSFT', full_regular_chart(), START + 24000)
    assert (q.open, q.high, q.low) == (100, 104, 99)
    assert q.regular_close == 102 and q.regular_close_timestamp == START + 23340


def test_exact_audit_old_meta_does_not_override_last_closing_candle():
    node = chart()
    node['meta']['regularMarketTime'] = START + 18000
    node['meta']['regularMarketPrice'] = 101.5
    q = parse_extended_chart('MSFT', node, START + 24000)
    assert q.regular_close == 102 and q.regular_close_timestamp == START + 23340
    node['timestamp'] = []
    q = parse_extended_chart('MSFT', node, START + 40000)
    assert q.regular_close is None and q.price is None


def test_exact_audit_closed_post_not_regular_close():
    q = parse_extended_chart('MSFT', chart(), START + 40000)
    assert q.price == 103 and q.price_session == 'post'
    assert q.regular_close == 102 and q.session == 'cerrado'


def test_timestamped_regular_closing_print_not_classified_as_post():
    node = chart()
    node['timestamp'] = []
    node['meta']['regularMarketTime'] = START + 23401
    q = parse_extended_chart('MSFT', node, START + 40000)
    assert q.price == 102 and q.price_session == 'regular'
    assert q.regular_close_timestamp == q.timestamp == START + 23401


def nodes():
    minute = chart()
    minute['meta'].update(symbol='MSFT', regularMarketTime=START+120, regularMarketPrice=102,
                          regularMarketDayHigh=104, regularMarketDayLow=99)
    daily = {
        'meta': {'symbol':'MSFT','currency':'USD','exchangeTimezoneName':'America/New_York',
                 'dataGranularity':'1d','regularMarketTime':START+120,'regularMarketPrice':102},
        'timestamp':[START-86400, START],
        'indicators':{'quote':[{'close':[100,102]}]},
    }
    return minute, daily


def test_sparse_minute_extrema_use_dated_regular_metadata_not_sampled_range():
    minute, daily = nodes()
    q=parse_extended_chart('MSFT',minute,START+200,daily)
    assert (q.open,q.high,q.low)==(100,104,99)
    assert (q.metrics_timestamp,q.metrics_session)==(START+120,'2026-10-08')
    assert q.previous_close_date=='2026-10-07'
    assert q.previous_close_timestamp is None  # Daily bar timestamp is an OPEN, not a close.
    assert (q.regular_close,q.regular_close_date,q.regular_close_timestamp)==(100,'2026-10-07',None)


@pytest.mark.parametrize('mutation', ['future','old','inverted','outside','null'])
def test_invalid_or_undated_metadata_never_establish_extrema(mutation):
    minute,daily=nodes()
    if mutation=='future': minute['meta']['regularMarketTime']=START+500
    if mutation=='old': minute['meta']['regularMarketTime']=START-86400
    if mutation=='inverted': minute['meta']['regularMarketDayHigh']=98
    if mutation=='outside': minute['meta']['regularMarketDayLow']=103
    if mutation=='null': minute['meta']['regularMarketDayHigh']=None
    q=parse_extended_chart('MSFT',minute,START+200,daily)
    assert q.high is None and q.low is None


@pytest.mark.parametrize('mutation', ['symbol','currency','timezone','granularity','mismatch','null-latest'])
def test_previous_close_date_requires_same_listing_and_latest_raw_close(mutation):
    minute,daily=nodes()
    if mutation=='symbol': daily['meta']['symbol']='ALM'
    if mutation=='currency': daily['meta']['currency']='EUR'
    if mutation=='timezone': daily['meta']['exchangeTimezoneName']='Europe/Madrid'
    if mutation=='granularity': daily['meta']['dataGranularity']='1m'
    if mutation=='mismatch': daily['indicators']['quote'][0]['close'][0]=98
    if mutation=='null-latest':
        daily['timestamp'].insert(0,START-2*86400)
        daily['indicators']['quote'][0]['close']=[100,None,102]
    q=parse_extended_chart('MSFT',minute,START+200,daily)
    assert q.previous_close_date is None and q.previous_close_timestamp is None


def test_holiday_weekend_uses_latest_actual_session_no_calendar_subtraction():
    minute,daily=nodes()
    daily['timestamp']=[START-4*86400,START]
    q=parse_extended_chart('MSFT',minute,START+200,daily)
    assert q.previous_close_date=='2026-10-04'  # Synthetic session, no holiday guessing.


def test_daily_closing_auction_overrides_last_minute_only_with_post_end_print():
    minute,daily=nodes()
    minute['meta'].update(regularMarketTime=START+24000,regularMarketPrice=103)
    daily['meta'].update(regularMarketTime=START+24000,regularMarketPrice=103)
    daily['indicators']['quote'][0]['close'][1]=103
    q=parse_extended_chart('MSFT',minute,START+25000,daily)
    assert (q.regular_close,q.regular_close_date,q.regular_close_timestamp)==(103,'2026-10-08',None)
    # Intraday metadata must not be promoted to a final close after the bell.
    daily['meta']['regularMarketTime']=START+18000
    q=parse_extended_chart('MSFT',minute,START+25000,daily)
    assert q.regular_close==102 and q.regular_close_timestamp==START+23340


def test_missing_daily_never_changes_existing_minute_quote():
    minute,_=nodes()
    q=parse_extended_chart('MSFT',minute,START+200)
    assert q.price==101 and q.previous_close_date is None
    assert q.regular_close is None


def test_service_daily_enrichment_failure_preserves_minute_quote():
    service=ExtendedQuoteService()
    service.client.extended_chart=AsyncMock(return_value=chart())
    service.client.recent_daily_chart=AsyncMock(side_effect=RuntimeError('daily down'))
    from unittest.mock import patch
    with patch('app.services.extended_quote_service.time.time', return_value=START+60):
        q=asyncio.run(service.get('MSFT'))
    assert q.price==101 and q.status=='available'
    assert q.previous_close_date is None


def test_closed_no_extended_market_uses_dated_auction_price_not_prior_minute():
    minute,daily=nodes()
    minute['timestamp']=[START,START+23340]
    minute['indicators']['quote'][0]={k:v[:2] for k,v in minute['indicators']['quote'][0].items()}
    minute['meta']['currentTradingPeriod'].pop('post')
    minute['meta'].update(regularMarketTime=START+24000,regularMarketPrice=103)
    daily['meta'].update(regularMarketTime=START+24000,regularMarketPrice=103)
    daily['indicators']['quote'][0]['close'][1]=103
    q=parse_extended_chart('MSFT',minute,START+40000,daily)
    assert q.price==103 and q.timestamp==START+24000 and q.price_session=='regular'
    assert q.regular_close==103 and q.regular_close_timestamp is None


def _bme_weekend_nodes():
    """SAN.MC un domingo: bounds ya en lunes, velas/meta del viernes y
    minutos sin contratacion en null (patron real de BME en Yahoo)."""
    from datetime import datetime, timezone

    def ts(y, m, d, hh, mm):
        return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp())

    fri_start, fri_end = ts(2026, 10, 16, 7, 0), ts(2026, 10, 16, 15, 30)
    mon_start, mon_end = ts(2026, 10, 19, 7, 0), ts(2026, 10, 19, 15, 30)
    minutes = list(range(fri_start, fri_end, 60))
    closes = [12.03] * len(minutes)
    closes[-1] = 12.034
    highs = [12.10] * len(minutes)
    lows = [12.01] * len(minutes)
    opens = [12.03] * len(minutes)
    opens[0] = 12.09
    for i in (100, 250, 400):  # minutos sin contratacion: OHLC en null
        highs[i] = lows[i] = opens[i] = closes[i] = None
    minute = {
        "meta": {
            "symbol": "SAN.MC", "currency": "EUR",
            "exchangeTimezoneName": "Europe/Madrid",
            "previousClose": 11.998,
            "regularMarketPrice": 12.034,
            "regularMarketTime": ts(2026, 10, 16, 15, 42),
            "regularMarketDayHigh": 12.128, "regularMarketDayLow": 12.012,
            "currentTradingPeriod": {
                "pre": {"start": mon_start, "end": mon_start},
                "regular": {"start": mon_start, "end": mon_end},
                "post": {"start": mon_end, "end": mon_end},
            },
            "tradingPeriods": {"regular": [[{"start": fri_start, "end": fri_end}]]},
        },
        "timestamp": minutes,
        "indicators": {"quote": [{"close": closes, "open": opens, "high": highs, "low": lows}]},
    }
    daily = {
        "meta": {"symbol": "SAN.MC", "currency": "EUR",
                 "exchangeTimezoneName": "Europe/Madrid", "dataGranularity": "1d"},
        "timestamp": [ts(2026, 10, 12, 12, 0), ts(2026, 10, 13, 12, 0),
                      ts(2026, 10, 14, 12, 0), ts(2026, 10, 15, 12, 0),
                      ts(2026, 10, 16, 12, 0)],
        "indicators": {"quote": [{"close": [12.264, 12.178, 12.130, 11.998, 12.034]}]},
    }
    sunday_now = ts(2026, 10, 18, 22, 50)
    return minute, daily, sunday_now


def test_bme_weekend_extrema_from_dated_meta_not_null_candles():
    """SAN.MC/TRE.MC: los minutos sin contratacion (null) tumban la auditoria
    de velas; los extremos salen de la meta fechada de Yahoo, fechados en la
    ultima sesion completada aunque los bounds ya sean la proxima."""
    minute, daily, now = _bme_weekend_nodes()
    q = parse_extended_chart("SAN.MC", minute, now, daily)
    assert q.session == "cerrado" and q.price == 12.034
    assert (q.high, q.low) == (12.128, 12.012)
    assert q.metrics_session == "2026-10-16" and q.metrics_timestamp is not None
    assert q.open == 12.09


def test_bme_weekend_previous_close_dated_against_displayed_session():
    """El cierre anterior (jueves) se fecha contra la sesion mostrada
    (viernes), no contra la proxima sesion de los bounds (lunes)."""
    minute, daily, now = _bme_weekend_nodes()
    q = parse_extended_chart("SAN.MC", minute, now, daily)
    assert q.previous_close == 11.998
    assert q.previous_close_date == "2026-10-15"
    assert q.regular_close == 12.034 and q.regular_close_date == "2026-10-16"


def test_daily_listing_guard_accepts_normalized_share_class():
    """BRK.B pedido al backend se convierte a BRK-B en Yahoo: la guarda de
    mismo-listado compara contra el simbolo normalizado, no el literal."""
    minute, daily = nodes()
    for node in (minute, daily):
        node["meta"]["symbol"] = "BRK-B"
    q = parse_extended_chart("BRK.B", minute, START + 200, daily)
    assert q.previous_close_date == "2026-10-07"
    # Y sigue rechazando otro listado real.
    daily["meta"]["symbol"] = "BRK-A"
    q = parse_extended_chart("BRK.B", minute, START + 200, daily)
    assert q.previous_close_date is None
