"""MarketRefreshService contracts: batched price lookups + staged honesty.

refresh() must not scale its market_prices query count with the number of
companies/positions (stage 1 upserts and stage 3 latest-price lookups are
batched), and every stage reports its honest status instead of hiding gaps.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import Base, Company, MarketPrice, Portfolio, Position
from app.services.connectors.ecb import ECBRates
from app.services.market_refresh_service import (
    MarketRefreshService,
    PriceObservation,
    PublicPriceProvider,
)


@pytest.fixture
def db():
    # Production SessionLocal uses expire_on_commit=False; mirror it so
    # expired-attribute reloads do not appear as phantom per-row queries.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


class _FakePriceProvider:
    async def fetch(self, companies, *, as_of):
        observations = {
            company.ticker: PriceObservation(
                ticker=company.ticker,
                price=Decimal("100"),
                price_date=as_of,
                source="fake",
            )
            for company in companies
        }
        return observations, []


class _FakeFXProvider:
    async def fetch(self, *, base_currency, quote_currencies):
        return ECBRates(
            rate_date=date(2026, 9, 22),
            rates={currency: Decimal("1.1") for currency in quote_currencies},
        )


def _seed(db: Session, n: int) -> None:
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    for i in range(n):
        company = Company(
            ticker=f"T{i:02d}",
            name=f"T{i:02d}",
            exchange="NASDAQ",
            currency="USD",
            sector="S",
            industry="I",
            company_type="holding",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        db.add(
            Position(
                company_id=company.id,
                quantity=Decimal("10"),
                currency="USD",
                market_price=Decimal("90"),
                market_value=Decimal("900"),
            )
        )
        # Pre-existing older price row: exercises the stage-1 upsert hit path.
        db.add(
            MarketPrice(
                company_id=company.id,
                date=date(2026, 9, 20),
                close=Decimal("95"),
                adj_close=Decimal("95"),
                source="seed",
            )
        )
    db.commit()


def _refresh_and_count(db: Session) -> tuple[dict, int]:
    statements = []

    def listener(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        service = MarketRefreshService(price_provider=_FakePriceProvider(), fx_provider=_FakeFXProvider())
        result = asyncio.run(service.refresh(db, as_of=date(2026, 9, 22)))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    counts = {}
    for table in ("market_prices", "positions", "fx_rates"):
        counts[table] = len([s for s in statements if s.lstrip().upper().startswith("SELECT") and table in s])
    return result, counts


def test_refresh_query_count_is_constant_in_company_count(db):
    _seed(db, 3)
    _, count_small = _refresh_and_count(db)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db2:
        db2.info["tenant_id"] = "tenant-test"
        _seed(db2, 8)
        _, count_large = _refresh_and_count(db2)

    # Stage-1 upsert lookups, stage-3 latest-price/position/FX lookups are
    # batched: no count may grow with the number of companies/positions.
    assert count_small == count_large


def test_refresh_writes_prices_and_reports_stages(db):
    _seed(db, 4)
    result, _ = _refresh_and_count(db)

    assert [stage["name"] for stage in result["stages"]] == [
        "update_prices",
        "update_fx",
        "revalue_positions",
        "update_risk",
        "evaluate_alerts",
    ]
    assert result["stages"][0]["status"] == "ok"
    assert result["stages"][0]["updated"] == 4
    assert result["stages"][1]["status"] == "ok"
    assert result["stages"][2]["updated"] == 4

    prices = db.scalars(select(MarketPrice).where(MarketPrice.date == date(2026, 9, 22))).all()
    assert len(prices) == 4
    assert all(price.close == Decimal("100") for price in prices)
    # Positions revalued from the refreshed close.
    for position in db.scalars(select(Position)).all():
        assert position.market_price == Decimal("100")
        assert position.market_value == Decimal("1000")
        # FX came from the stage-2 upsert (1.1) through the batched table.
        assert position.fx_rate == Decimal("1.1")
        assert position.market_value_base == Decimal("1100")


def test_finnhub_quote_without_timestamp_is_not_dated_today():
    """Quote de Finnhub sin timestamp: no se publica con la fecha de hoy."""
    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    provider.fmp = SimpleNamespace(configured=lambda: False)

    async def quote(_ticker, **_kwargs):
        return {"c": 210.5, "t": 0}

    provider.finnhub = SimpleNamespace(configured=lambda: True, quote=quote)
    company = SimpleNamespace(ticker="AAPL")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    assert observation is None
    assert error is not None
    assert "quote_missing_timestamp" in error["reason"]


def test_finnhub_quote_uses_provider_timestamp_date():
    """Con timestamp, observed_date es la fecha del proveedor (UTC), no hoy."""
    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    provider.fmp = SimpleNamespace(configured=lambda: False)
    provider_ts = 1_758_220_800  # 2025-09-18, claramente distinto del as_of

    async def quote(_ticker, **_kwargs):
        return {"c": 210.5, "t": provider_ts}

    provider.finnhub = SimpleNamespace(configured=lambda: True, quote=quote)
    company = SimpleNamespace(ticker="AAPL")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    expected = datetime.fromtimestamp(provider_ts, tz=UTC).date()

    assert error is None
    assert observation is not None
    assert observation.price_date == expected
    assert observation.price_date != date(2026, 9, 26)


def test_fmp_quote_without_timestamp_is_not_dated():
    """Quote de FMP sin timestamp: se salta, nunca se fecha con metadatos."""
    provider = PublicPriceProvider.__new__(PublicPriceProvider)

    async def quote(_ticker, **_kwargs):
        return [{"price": 210.5}]

    provider.fmp = SimpleNamespace(configured=lambda: True, quote=quote)
    provider.finnhub = SimpleNamespace(configured=lambda: False)
    company = SimpleNamespace(ticker="AAPL")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    assert observation is None
    assert error is not None
    assert "FMP:quote_missing_timestamp" in error["reason"]


def test_fmp_quote_uses_provider_timestamp_and_real_volume():
    """Un refresh en sabado fechaba la barra EN sabado: ya no.

    La quote del viernes (timestamp del proveedor) se guarda con la fecha del
    viernes y con el volumen real del dia, no un 0 inventado.
    """
    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    friday_ts = int(datetime(2026, 9, 25, 20, 0, tzinfo=UTC).timestamp())

    async def quote(_ticker, **_kwargs):
        return [{"price": 210.5, "timestamp": friday_ts, "volume": 48_123_456}]

    provider.fmp = SimpleNamespace(configured=lambda: True, quote=quote)
    provider.finnhub = SimpleNamespace(configured=lambda: False)
    company = SimpleNamespace(ticker="AAPL")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    assert error is None
    assert observation is not None
    assert observation.price_date == date(2026, 9, 25)
    assert observation.price_date != date(2026, 9, 26)
    assert observation.volume == 48_123_456


def test_fmp_future_quote_date_is_rejected():
    """Un timestamp futuro no puede escribir una barra de manana."""
    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    future_ts = int(datetime(2026, 9, 28, 20, 0, tzinfo=UTC).timestamp())

    async def quote(_ticker, **_kwargs):
        return [{"price": 210.5, "timestamp": future_ts}]

    provider.fmp = SimpleNamespace(configured=lambda: True, quote=quote)
    provider.finnhub = SimpleNamespace(configured=lambda: False)
    company = SimpleNamespace(ticker="AAPL")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    assert observation is None
    assert error is not None
    assert "FMP:quote_date_in_future" in error["reason"]


def test_fmp_profile_is_never_used_for_prices():
    """El profile (fechas de metadatos) ya no es fuente de precios."""

    async def forbidden_profile(_ticker):
        raise AssertionError("company_profile no debe usarse para precios")

    async def quote(_ticker, **_kwargs):
        friday_ts = int(datetime(2026, 9, 25, 20, 0, tzinfo=UTC).timestamp())
        return [{"price": 210.5, "timestamp": friday_ts, "volume": 1000}]

    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    provider.fmp = SimpleNamespace(configured=lambda: True, quote=quote, company_profile=forbidden_profile)
    provider.finnhub = SimpleNamespace(configured=lambda: False)
    company = SimpleNamespace(ticker="AAPL")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    assert error is None
    assert observation is not None
    assert observation.source == "FMP"


def test_non_us_company_never_gets_a_bare_ticker_us_quote():
    """ALM es Almirall (BME, EUR); Finnhub/FMP con el ticker pelado devuelven
    Almonty (ALM en Nasdaq). Ese precio NUNCA puede guardarse bajo Almirall."""
    provider = PublicPriceProvider.__new__(PublicPriceProvider)

    async def fmp_quote(_ticker, **_kwargs):
        return [{"price": 13.72, "timestamp": 1_800_000_000}]

    async def finnhub_quote(_ticker, **_kwargs):
        return {"c": 13.72, "t": 1_800_000_000}

    provider.fmp = SimpleNamespace(configured=lambda: True, quote=fmp_quote)
    provider.finnhub = SimpleNamespace(configured=lambda: True, quote=finnhub_quote)
    company = SimpleNamespace(ticker="ALM", exchange="BME", currency="EUR")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    assert observation is None
    assert error is not None
    assert error["reason"] == "non_us_listing"


def test_adr_is_not_the_amsterdam_listing():
    """ASML cotiza en Euronext Amsterdam en EUR; la quote pelada es el ADR
    Nasdaq en USD. La bolsa contiene «NYSE» pero la divisa manda: fuera."""
    provider = PublicPriceProvider.__new__(PublicPriceProvider)

    async def fmp_quote(_ticker, **_kwargs):
        return [{"price": 1743.94, "timestamp": 1_800_000_000}]

    provider.fmp = SimpleNamespace(configured=lambda: True, quote=fmp_quote)
    provider.finnhub = SimpleNamespace(configured=lambda: False)
    company = SimpleNamespace(ticker="ASML", exchange="NYSE EURONEXT - EURONEXT AMSTERDAM", currency="EUR")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    assert observation is None
    assert error is not None
    assert error["reason"] == "non_us_listing"


def test_us_and_unknown_usd_companies_keep_us_quotes():
    """NASDAQ/USD y UNKNOWN/USD (bulk import US) siguen cotizando en US."""
    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    ts = int(datetime(2026, 9, 25, 20, 0, tzinfo=UTC).timestamp())

    async def fmp_quote(_ticker, **_kwargs):
        return [{"price": 210.5, "timestamp": ts}]

    provider.fmp = SimpleNamespace(configured=lambda: True, quote=fmp_quote)
    provider.finnhub = SimpleNamespace(configured=lambda: False)

    for exchange, currency in (
        ("NASDAQ NMS - GLOBAL MARKET", "USD"),
        ("NEW YORK STOCK EXCHANGE, INC.", "USD"),  # literal de prod: sin «NYSE»
        ("NYSE MKT LLC", "USD"),
        ("UNKNOWN", "USD"),
        ("", ""),
    ):
        company = SimpleNamespace(ticker="AAPL", exchange=exchange, currency=currency)
        _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))
        assert error is None, (exchange, currency)
        assert observation is not None, (exchange, currency)


def test_unknown_exchange_with_eur_is_not_a_us_listing():
    """UNKNOWN+EUR: sin evidencia de listado US, no arriesgar el gemelo."""
    provider = PublicPriceProvider.__new__(PublicPriceProvider)

    async def fmp_quote(_ticker, **_kwargs):
        return [{"price": 10.0, "timestamp": 1_800_000_000}]

    provider.fmp = SimpleNamespace(configured=lambda: True, quote=fmp_quote)
    provider.finnhub = SimpleNamespace(configured=lambda: False)
    company = SimpleNamespace(ticker="XYZ", exchange="UNKNOWN", currency="EUR")

    _, observation, error = asyncio.run(provider._one(company, date(2026, 9, 26)))

    assert observation is None
    assert error is not None
    assert error["reason"] == "non_us_listing"


class _FakeRedis:
    """Mini redis en memoria para el breaker (get/set/incr/expire/delete)."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def incr(self, key):
        self.store[key] = int(self.store.get(key) or 0) + 1
        return self.store[key]

    def expire(self, key, _seconds):
        return True

    def delete(self, key):
        self.store.pop(key, None)


def test_first_finnhub_429_marks_provider_down_for_the_run():
    """Primer 429 de Finnhub: null honesto provider_unavailable, y el ticker
    siguiente ya NO llama a Finnhub (la cuota no se sigue quemando)."""
    from app.services.connectors.base import UpstreamRateLimited

    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    provider.fmp = SimpleNamespace(configured=lambda: False)
    calls = {"finnhub": 0}

    async def quote(_ticker, **_kwargs):
        calls["finnhub"] += 1
        raise UpstreamRateLimited("429")

    provider.finnhub = SimpleNamespace(configured=lambda: True, quote=quote)
    provider._provider_down = set()
    provider._breaker_client = _FakeRedis()

    _, obs1, err1 = asyncio.run(provider._one(SimpleNamespace(ticker="AAPL"), date(2026, 9, 26)))
    _, obs2, err2 = asyncio.run(provider._one(SimpleNamespace(ticker="MSFT"), date(2026, 9, 26)))

    assert obs1 is None and "Finnhub:provider_unavailable" in err1["reason"]
    assert obs2 is None and "Finnhub:provider_unavailable" in err2["reason"]
    assert calls["finnhub"] == 1  # el segundo ticker ni siquiera intenta


def test_fmp_429_marks_only_fmp_down_finnhub_still_serves():
    """Un 429 de FMP apaga FMP en la corrida pero Finnhub sigue sirviendo."""
    from app.services.connectors.base import UpstreamRateLimited

    provider = PublicPriceProvider.__new__(PublicPriceProvider)

    async def fmp_quote(_ticker, **_kwargs):
        raise UpstreamRateLimited("429")

    async def finnhub_quote(_ticker, **_kwargs):
        return {"c": 210.5, "t": 1_758_220_800}

    provider.fmp = SimpleNamespace(configured=lambda: True, quote=fmp_quote)
    provider.finnhub = SimpleNamespace(configured=lambda: True, quote=finnhub_quote)
    provider._provider_down = set()
    provider._breaker_client = _FakeRedis()

    _, obs, err = asyncio.run(provider._one(SimpleNamespace(ticker="AAPL"), date(2026, 9, 26)))

    assert err is None
    assert obs is not None and obs.source == "Finnhub"
    assert "fmp" in provider._provider_down and "finnhub" not in provider._provider_down


def test_breaker_opens_after_streak_and_skips_next_run():
    """Racha de 429s abre el breaker en Redis; la corrida siguiente salta el
    proveedor entero sin llamarlo (breaker cross-run compartido)."""
    from app.services.connectors.base import UpstreamRateLimited
    from app.services.market_refresh_service import _MARKETDATA_BREAKER_STREAK_LIMIT

    redis_fake = _FakeRedis()
    calls = {"finnhub": 0}

    async def quote(_ticker, **_kwargs):
        calls["finnhub"] += 1
        raise UpstreamRateLimited("429")

    # STREAK_LIMIT corridas seguidas con 429 del proveedor abren el breaker
    # (dentro de una corrida solo el primer 429 cuenta: el proveedor se apaga)
    for i in range(_MARKETDATA_BREAKER_STREAK_LIMIT):
        provider = PublicPriceProvider.__new__(PublicPriceProvider)
        provider.fmp = SimpleNamespace(configured=lambda: False)
        provider.finnhub = SimpleNamespace(configured=lambda: True, quote=quote)
        provider._provider_down = set()
        provider._breaker_client = redis_fake
        asyncio.run(provider._one(SimpleNamespace(ticker=f"T{i}"), date(2026, 9, 26)))
    assert redis_fake.get("marketdata_breaker:finnhub:open") == "1"

    # Corrida 2 (breaker abierto): fetch() no llama al proveedor ni una vez
    before = calls["finnhub"]
    provider2 = PublicPriceProvider.__new__(PublicPriceProvider)
    provider2.fmp = SimpleNamespace(configured=lambda: False)
    provider2.finnhub = SimpleNamespace(configured=lambda: True, quote=quote)
    provider2._provider_down = set()
    provider2._breaker_client = redis_fake
    observations, errors = asyncio.run(
        provider2.fetch([SimpleNamespace(ticker="AAPL")], as_of=date(2026, 9, 26))
    )
    assert calls["finnhub"] == before
    assert observations == {}
    assert "Finnhub:provider_unavailable" in errors[0]["reason"]


def test_concurrent_429s_count_once_per_run_and_breaker_opens_after_3_runs():
    """Carrera real: 8 tickers, semaforo de 6, proveedor lento que siempre
    429. En UNA corrida la racha crece exactamente 1 (guard de transicion),
    no 6/8; el breaker abre solo tras 3 corridas reales, no tras 3 respuestas."""
    from app.services.connectors.base import UpstreamRateLimited
    from app.services.market_refresh_service import _MARKETDATA_BREAKER_STREAK_LIMIT

    redis_fake = _FakeRedis()
    calls = {"finnhub": 0}

    async def quote(_ticker, **_kwargs):
        calls["finnhub"] += 1
        await asyncio.sleep(0.015)  # solapa las 6 primeras en vuelo (raza real)
        raise UpstreamRateLimited("429")

    def fresh_provider():
        provider = PublicPriceProvider.__new__(PublicPriceProvider)
        provider.fmp = SimpleNamespace(configured=lambda: False)
        provider.finnhub = SimpleNamespace(configured=lambda: True, quote=quote)
        provider._provider_down = set()
        provider._breaker_client = redis_fake
        return provider

    companies = [SimpleNamespace(ticker=f"T{i}") for i in range(8)]

    # Corrida 1: varios 429 concurrentes, racha = 1, breaker CERRADO
    asyncio.run(fresh_provider().fetch(companies, as_of=date(2026, 9, 26)))
    assert redis_fake.store.get("marketdata_breaker:finnhub:429_streak") == 1
    assert redis_fake.get("marketdata_breaker:finnhub:open") is None

    # Corridas 2 y 3: la tercera abre el breaker
    for _ in range(_MARKETDATA_BREAKER_STREAK_LIMIT - 1):
        asyncio.run(fresh_provider().fetch(companies, as_of=date(2026, 9, 26)))
    assert redis_fake.get("marketdata_breaker:finnhub:open") == "1"

    # Corrida 4 con breaker abierto: ni una llamada
    before = calls["finnhub"]
    observations, errors = asyncio.run(fresh_provider().fetch(companies, as_of=date(2026, 9, 26)))
    assert calls["finnhub"] == before
    assert observations == {}
    assert len(errors) == 8
    assert all("Finnhub:provider_unavailable" in e["reason"] for e in errors)


class _LateSpotProvider:
    async def fetch(self, companies, *, as_of):
        return {
            company.ticker: PriceObservation(
                ticker=company.ticker,
                price=Decimal("100.50"),
                price_date=date(2026, 9, 21),
                source="Finnhub",
            )
            for company in companies
        }, []


def test_late_spot_does_not_overwrite_closed_official_bar(db):
    _seed(db, 1)
    company = db.scalars(select(Company)).one()
    db.add(MarketPrice(company_id=company.id, date=date(2026, 9, 21), close=Decimal("100.40"),
                       adj_close=Decimal("100.40"), source="yfinance"))
    db.commit()
    service = MarketRefreshService(price_provider=_LateSpotProvider(), fx_provider=_FakeFXProvider())
    asyncio.run(service.refresh(db, as_of=date(2026, 9, 22)))
    bar = db.scalars(select(MarketPrice).where(MarketPrice.date == date(2026, 9, 21))).one()
    assert bar.close == Decimal("100.40")
    assert bar.source == "yfinance"


@pytest.mark.parametrize("unit,close,expected", [
    ("GBX", "4255", "4255"), ("GBp", "4255", "4255"),
    ("GBP", "42.55", "4255"), (None, "4255", None),
    ("USD", "42.55", None),
])
def test_refresh_london_price_unit_not_guessed(db, unit, close, expected):
    from app.models import FXRate
    from app.services.portfolio_ledger_service import PortfolioLedgerService

    day = date(2026, 10, 26)
    ledger = PortfolioLedgerService()
    ledger.create_transaction(db, ticker="CGEO.L", action="buy", quantity=Decimal("100"),
                              price=Decimal("42.55"), currency="GBP", trade_date=day)
    company = ledger.ensure_company(db, "CGEO.L")
    db.add(FXRate(base_currency="EUR", quote_currency="GBP", rate=Decimal("1.17"), rate_date=day))
    db.commit()

    class Prices:
        async def fetch(self, companies, *, as_of):
            return {"CGEO.L": PriceObservation("CGEO.L", Decimal(close), day, "test", quote_currency=unit)}, []

    class FX:
        async def fetch(self, **kwargs):
            return ECBRates(rate_date=day, rates={"GBP": Decimal("1.17")})

    result = asyncio.run(MarketRefreshService(Prices(), FX()).refresh(db, as_of=day))
    position = db.scalar(select(Position).where(Position.company_id == company.id))
    stored = db.scalar(select(MarketPrice).where(MarketPrice.company_id == company.id))
    assert stored.close == Decimal(close)  # raw provider value is never rewritten
    assert stored.quote_currency == unit
    if expected is None:
        assert position.market_value_base is None
        assert position.market_value_native is None
        # Zero is only a ledger sentinel, never a complete zero-valued snapshot.
        assert result["stages"][2]["snapshot_pricing_coverage"] < 1
        assert result["stages"][2]["stale_prices"][0]["status"] == "unknown_price_unit"
    else:
        assert position.market_value == Decimal(expected)
        assert position.market_value_base == Decimal(expected) * Decimal("1.17")
        assert position.unrealized_pnl == 0


def test_reconstruction_converts_explicit_price_unit(db):
    from app.models import FXRate
    from app.services.portfolio_ledger_service import PortfolioLedgerService
    from app.services.portfolio_reconstruction_service import PortfolioReconstructionService

    day = date(2026, 10, 26)
    ledger = PortfolioLedgerService()
    ledger.create_transaction(db, ticker="CGEO.L", action="buy", quantity=Decimal("100"),
                              price=Decimal("42.55"), currency="GBP", trade_date=day)
    company = ledger.ensure_company(db, "CGEO.L")
    db.add(FXRate(base_currency="EUR", quote_currency="GBP", rate=Decimal("1.17"), rate_date=day))
    db.add(MarketPrice(company_id=company.id, date=day, close=Decimal("4255"),
                       quote_currency="GBX", source="test"))
    db.commit()
    result = PortfolioReconstructionService().build(db)
    assert result.series[-1]["value_base"] == pytest.approx(4978.35)
    assert result.price_check["max_abs_diff_vs_close"] == 0


def test_refresh_preserves_adjusted_series_unit(db):
    from app.services.portfolio_ledger_service import PortfolioLedgerService

    day = date(2026, 10, 26)
    ledger = PortfolioLedgerService()
    ledger.create_transaction(db, ticker="CGEO.L", action="buy", quantity=Decimal("100"),
                              price=Decimal("42.55"), currency="GBP", trade_date=day)
    company = ledger.ensure_company(db, "CGEO.L")
    db.add(MarketPrice(company_id=company.id, date=day, close=Decimal("4250"),
                       adj_close=Decimal("4200"), quote_currency="GBX", source="yfinance"))
    db.commit()

    class Prices:
        async def fetch(self, companies, *, as_of):
            return {"CGEO.L": PriceObservation("CGEO.L", Decimal("42.55"), day, "test", quote_currency="GBP")}, []

    asyncio.run(MarketRefreshService(Prices(), _FakeFXProvider()).refresh(db, as_of=day))
    price = db.scalar(select(MarketPrice).where(MarketPrice.company_id == company.id))
    assert price.close == Decimal("4255")
    assert price.adj_close == Decimal("4200")
    assert price.quote_currency == "GBX"
