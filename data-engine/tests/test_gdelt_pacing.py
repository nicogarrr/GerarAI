"""GDELT pacing + cola prices: la tormenta de 429 no debe volver a saturar la cola."""

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from app.services.connectors.gdelt import GDELTClient, GDELTConnector, GdeltRateLimited


class _StubClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[float] = []

    async def get(self, url, params=None):
        self.calls.append(time.monotonic())
        return self.responses.pop(0)


def _resp(status: int, payload: dict | None = None, retry_after: str | None = None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(status, json=payload or {"articles": []}, headers=headers, request=httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc"))


@pytest.fixture(autouse=True)
def _reset_gdelt_class_state():
    """El pacing y el cooldown 429 son estado de CLASE: aislar cada test."""
    GDELTClient._next_allowed_at = 0.0
    GDELTClient._blocked_until = 0.0
    yield
    GDELTClient._next_allowed_at = 0.0
    GDELTClient._blocked_until = 0.0


@pytest.fixture()
def fake_clock(monkeypatch):
    """Reloj falso compartido: ``time.monotonic`` y ``asyncio.sleep`` (los
    que usa el conector) avanzan el clock SIN espera real. Las ventanas de
    45/60/3600s se verifican al instante en lugar de añadir ~390s de pacing
    real a la suite (el auditor necesita corridas rapidas y reproducibles)."""
    import app.services.connectors.gdelt as gdelt_mod

    now = [10_000.0]
    monkeypatch.setattr(gdelt_mod, "time", SimpleNamespace(monotonic=lambda: now[0]))

    async def _fake_sleep(seconds: float) -> None:
        now[0] += max(0.0, seconds)

    monkeypatch.setattr(gdelt_mod, "asyncio", SimpleNamespace(sleep=_fake_sleep))
    yield now


def test_fake_clock_is_private_to_gdelt_not_the_event_loop(fake_clock):
    import app.services.connectors.gdelt as gdelt_mod

    assert gdelt_mod.time is not time
    assert gdelt_mod.asyncio is not asyncio
    started = fake_clock[0]
    asyncio.run(asyncio.sleep(0.001))
    assert fake_clock[0] == started
    asyncio.run(gdelt_mod.asyncio.sleep(3))
    assert fake_clock[0] == started + 3


def test_throttle_enforces_min_interval():
    stub = _StubClient([_resp(200), _resp(200), _resp(200)])
    client = GDELTClient(client=stub, min_interval=0.05)
    GDELTClient._next_allowed_at = 0.0  # estado limpio para el test

    async def run():
        for _ in range(3):
            await client.news_search("apple")

    asyncio.run(run())
    gaps = [b - a for a, b in zip(stub.calls, stub.calls[1:])]
    assert all(gap >= 0.045 for gap in gaps), gaps


def test_min_interval_zero_does_not_wait():
    stub = _StubClient([_resp(200), _resp(200)])
    client = GDELTClient(client=stub, min_interval=0)
    GDELTClient._next_allowed_at = 0.0

    async def run():
        for _ in range(2):
            await client.news_search("apple")

    asyncio.run(run())
    assert stub.calls[1] - stub.calls[0] < 0.045


def test_throttle_holds_the_spacing_under_load():
    """Un overrun del evento loop no debe colapsar el intervalo siguiente.

    The reservation used to be claimed BEFORE the sleep, so a call that woke up
    late consumed its slot without waiting and the next call saw an already
    elapsed deadline and went out immediately. The spacing only held when
    nothing was slow, which is the opposite of when GDELT starts returning 429.
    """
    stub = _StubClient([_resp(200), _resp(200), _resp(200)])
    client = GDELTClient(client=stub, min_interval=0.05)
    GDELTClient._next_allowed_at = 0.0
    real_sleep = asyncio.sleep

    async def slow_sleep(delay, *args, **kwargs):
        # Simulate a loaded event loop overshooting the first wait.
        await real_sleep(delay + 0.06 if delay > 0 else 0.0)

    async def run():
        original = asyncio.sleep
        asyncio.sleep = slow_sleep
        try:
            for _ in range(3):
                await client.news_search("apple")
        finally:
            asyncio.sleep = original

    asyncio.run(run())
    gaps = [b - a for a, b in zip(stub.calls, stub.calls[1:])]
    assert all(gap >= 0.045 for gap in gaps), gaps


def test_429_retry_after_then_success(fake_clock):
    stub = _StubClient([_resp(429, retry_after="0"), _resp(200, {"articles": [{"url": "u"}]})])
    client = GDELTClient(client=stub, min_interval=0, max_429_retries=2)
    GDELTClient._next_allowed_at = 0.0
    started = fake_clock[0]
    out = asyncio.run(client.news_search("apple"))
    assert out == {"articles": [{"url": "u"}]}
    assert len(stub.calls) == 2
    # ventana 0 -> el reintento inline espera exactamente el suelo de 60s
    assert fake_clock[0] - started == GDELTClient.RETRY_AFTER_FLOOR


def test_429_retry_after_beyond_max_raises_without_retry():
    stub = _StubClient([_resp(429, retry_after="3600"), _resp(200, {"articles": []})])
    client = GDELTClient(client=stub, min_interval=0, max_429_retries=2)
    with pytest.raises(GdeltRateLimited) as excinfo:
        asyncio.run(client.news_search("q"))
    assert len(stub.calls) == 1  # la ventana prohibida no se reintenta inline
    assert excinfo.value.retry_after == 3600.0  # la ventana real sube al actor


def test_429_exhaustion_raises(fake_clock):
    stub = _StubClient([_resp(429, retry_after="45"), _resp(429, retry_after="45"), _resp(429, retry_after="45")])
    client = GDELTClient(client=stub, min_interval=0, max_429_retries=2)
    GDELTClient._next_allowed_at = 0.0
    started = fake_clock[0]
    with pytest.raises(GdeltRateLimited) as excinfo:
        asyncio.run(client.news_search("apple"))
    assert len(stub.calls) == 3
    assert excinfo.value.retry_after == 45.0  # ventana acotada (min(raw, MAX))
    # dos reintentos inline de 45s exactos: la ventana nunca se pisa ni se infla
    assert fake_clock[0] - started == 90.0


def test_429_exhaustion_con_ventana_cero_paga_el_suelo(fake_clock):
    stub = _StubClient([_resp(429, retry_after="0"), _resp(429, retry_after="0"), _resp(429, retry_after="0")])
    client = GDELTClient(client=stub, min_interval=0, max_429_retries=2)
    GDELTClient._next_allowed_at = 0.0
    started = fake_clock[0]
    with pytest.raises(GdeltRateLimited) as excinfo:
        asyncio.run(client.news_search("apple"))
    assert excinfo.value.retry_after == GDELTClient.RETRY_AFTER_FLOOR  # 0 nunca reintenta al instante
    # dos reintentos inline, cada uno pagando el suelo: 120s de espera exacta
    assert fake_clock[0] - started == 2 * GDELTClient.RETRY_AFTER_FLOOR


def test_retry_after_default_when_header_missing():
    assert GDELTClient._retry_after_seconds(_resp(429)) == GDELTClient.DEFAULT_RETRY_AFTER
    assert GDELTClient._retry_after_seconds(_resp(429, retry_after="999")) == GDELTClient.MAX_RETRY_AFTER
    assert GDELTClient._retry_after_seconds(_resp(429, retry_after="abc")) == GDELTClient.DEFAULT_RETRY_AFTER


def test_price_actors_on_prices_queue():
    from app.workers import dramatiq_app

    assert dramatiq_app.refresh_market_pipeline.queue_name == "prices"
    assert dramatiq_app.refresh_portfolio_prices_intraday.queue_name == "prices"
    # los actores GDELT van en su carril dedicado (pacing por IP, un proceso)
    assert dramatiq_app.refresh_news.queue_name == "gdelt"
    assert dramatiq_app.refresh_macro_news.queue_name == "gdelt"


def test_connector_propagates_rate_limited_instead_of_degrading():
    """Un 429 NO degrada a ConnectorResult.failed: sube tipada al actor."""

    class _Limited:
        async def news_search(self, query, max_records=50):
            raise GdeltRateLimited(45.0)

    connector = GDELTConnector(client=_Limited())
    with pytest.raises(GdeltRateLimited):
        asyncio.run(connector.poll("apple"))


def test_connector_still_degrades_other_errors():
    """El resto de errores siguen degradando a failed (contrato intacto)."""

    class _Boom:
        async def news_search(self, query, max_records=50):
            raise RuntimeError("boom")

    result = asyncio.run(GDELTConnector(client=_Boom()).poll("apple"))
    assert result.status == "error"
    assert result.errors


def test_gdelt_retry_helper_never_retries_before_the_window():
    """Nunca antes de la ventana real; suelo de 60s si viene 0 o ausente."""
    import dramatiq

    from app.workers.dramatiq_app import GDELT_RETRY_FLOOR_SECONDS, _raise_gdelt_retry

    # Ventana normal: se honra exacta.
    with pytest.raises(dramatiq.Retry) as excinfo:
        _raise_gdelt_retry(GdeltRateLimited(45.0))
    assert excinfo.value.delay == 45_000

    # Ventana larga: NO se trunca a ningun cap (truncar = reintentar antes).
    with pytest.raises(dramatiq.Retry) as excinfo:
        _raise_gdelt_retry(GdeltRateLimited(3_600.0))
    assert excinfo.value.delay == 3_600_000

    # Ventana 0 o ausente: suelo de 60s para no buclear contra el 429.
    with pytest.raises(dramatiq.Retry) as excinfo:
        _raise_gdelt_retry(GdeltRateLimited(0.0))
    assert excinfo.value.delay == int(GDELT_RETRY_FLOOR_SECONDS * 1000)

    # Ventana presente aunque sea corta: se honra exacta (el suelo no la pisa).
    with pytest.raises(dramatiq.Retry) as excinfo:
        _raise_gdelt_retry(GdeltRateLimited(30.0))
    assert excinfo.value.delay == 30_000


def test_gdelt_lane_backoff_config():
    """El carril gdelt no quema cuota en 429: backoff amplio + retries acotados."""
    from app.workers import dramatiq_app

    for actor in (dramatiq_app.refresh_news, dramatiq_app.refresh_macro_news):
        assert actor.options["min_backoff"] == 60_000
        assert actor.options["max_backoff"] == 900_000
        assert actor.options["max_retries"] == 6


def test_429_marks_ip_wide_blocked_until_for_the_whole_lane(fake_clock):
    """El cooldown del 429 es POR IP: lo respetan TODOS los clientes del carril."""
    stub = _StubClient([_resp(429, retry_after="3")])
    client = GDELTClient(client=stub, min_interval=0, max_429_retries=0)
    with pytest.raises(GdeltRateLimited):
        asyncio.run(client.news_search("q"))
    assert GDELTClient._blocked_until > fake_clock[0] + 2  # ~3s de ventana
    # otro job (otra instancia) del carril hereda la espera
    other = GDELTClient(client=_StubClient([_resp(200, {"articles": []})]), min_interval=5)
    started = fake_clock[0]
    asyncio.run(other._throttle())
    assert fake_clock[0] - started >= 2  # esperó la ventana, no los 5s de pacing


def test_block_for_only_extends_never_shortens():
    GDELTClient._block_for(100.0)
    first = GDELTClient._blocked_until
    GDELTClient._block_for(1.0)
    assert GDELTClient._blocked_until == first


def test_block_for_suelo_60_en_ventana_cero():
    """Ventana 0/ausente: el cooldown global POR IP paga el suelo de 60s."""
    GDELTClient._block_for(0.0)
    remaining = GDELTClient._blocked_until - time.monotonic()
    assert 55.0 < remaining <= GDELTClient.RETRY_AFTER_FLOOR


def test_throttle_defiere_ventana_ip_mas_larga_que_la_corrida():
    """Un cooldown POR IP > MAX_RETRY_AFTER no puede dormirse en el worker:
    el time_limit del actor lo mataria dentro. Sube tipada con la ventana
    restante para que el mensaje vaya a diferidos."""
    GDELTClient._blocked_until = time.monotonic() + 3600.0
    client = GDELTClient(client=_StubClient([_resp(200, {"articles": []})]))
    started = time.monotonic()
    with pytest.raises(GdeltRateLimited) as excinfo:
        asyncio.run(client.news_search("q"))
    elapsed = time.monotonic() - started
    assert elapsed < 5.0  # no durmio la ventana dentro del worker
    assert excinfo.value.retry_after > 3500.0  # ventana restante, no truncada


def test_raw_retry_after_http_date():
    """Retry-After como HTTP-date: fecha futura = segundos restantes; fecha
    pasada = 0 (cae al suelo en los consumidores)."""
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    future = format_datetime(datetime.now(UTC) + timedelta(seconds=3600))
    past = format_datetime(datetime.now(UTC) - timedelta(seconds=30))
    value = GDELTClient._raw_retry_after(_resp(429, retry_after=future))
    assert value is not None and 3500.0 < value <= 3600.0
    assert GDELTClient._raw_retry_after(_resp(429, retry_after=past)) == 0.0


def test_raw_retry_after_no_finito_cae_al_default():
    """Inf/NaN/enormes no pueden bloquear indefinido ni desbordar el delay."""
    for raw in ("inf", "-inf", "nan", "1e999"):
        assert GDELTClient._raw_retry_after(_resp(429, retry_after=raw)) is None
    assert GDELTClient._retry_after_seconds(_resp(429, retry_after="1e999")) == GDELTClient.DEFAULT_RETRY_AFTER


def test_429_sin_cabecera_usa_suelo_60_en_excepcion_y_cooldown(fake_clock):
    """Sin Retry-After: excepcion e IP-wide cooldown usan la misma ventana
    (el suelo), no un default distinto mas corto."""
    stub = _StubClient([_resp(429), _resp(429), _resp(429)])
    client = GDELTClient(client=stub, max_429_retries=2)
    started = fake_clock[0]
    with pytest.raises(GdeltRateLimited) as excinfo:
        asyncio.run(client.news_search("q"))
    assert excinfo.value.retry_after == GDELTClient.RETRY_AFTER_FLOOR
    # dos reintentos inline de 60s (el pacing de 5s queda absorbido por el suelo)
    assert fake_clock[0] - started == 2 * GDELTClient.RETRY_AFTER_FLOOR
    remaining = GDELTClient._blocked_until - fake_clock[0]
    assert remaining > 50.0
