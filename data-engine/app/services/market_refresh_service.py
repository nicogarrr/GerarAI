"""Ordered market refresh: prices -> FX -> positions -> risk -> alerts."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import Company, FinancialFact, MarketPrice, Position, SavedScreen
from app.services.alert_rule_service import AlertRuleService
from app.services.connectors.base import UpstreamRateLimited
from app.services.connectors.ecb import ECBClient, ECBRates
from app.services.connectors.finnhub import FinnhubClient
from app.services.connectors.fmp import FMPClient
from app.services.portfolio_fx_service import TAX_CURRENCY, PortfolioFXService
from app.services.portfolio_ledger_service import PortfolioLedgerService
from app.services.price_freshness import close_is_stale, market_price_is_stale
from app.services.price_units import price_in_currency
from app.services.propicks_price_service import yahoo_symbol
from app.services.risk_service import RiskService
from app.services.screener_service import ScreenerService
from app.valuation.currency import normalize_currency, reporting_currencies

_US_EXCHANGE_TOKENS = ("NYSE", "NEW YORK", "NASDAQ", "AMEX", "OTC", "BATS", "ARCA")

# Circuit breaker por proveedor de mercado (FMP/Finnhub), mismo patron que el
# sec_breaker de F359: una racha de 429s dentro de la ventana abre el breaker
# durante el cooldown; abierto, el proveedor se salta entero en cada corrida.
# El estado vive en Redis (compartido por worker, worker-kpis y backend), no
# en memoria del proceso. Fail-open si Redis no responde: el broker de
# dramatiq es el propio Redis, asi que sin Redis no hay consumo de mensajes
# de todas formas, y el reintento queda acotado por max_retries del actor.
_MARKETDATA_BREAKER_WINDOW_S = 600.0
_MARKETDATA_BREAKER_STREAK_LIMIT = 3
_MARKETDATA_BREAKER_COOLDOWN_S = 900.0


def _marketdata_breaker_client():
    """Cliente redis corto para el breaker; None si no hay URL o falla."""
    try:
        import redis as _redis

        from app.core.redis_retry import no_retry

        url = get_settings().redis_url
        if not url:
            return None
        return _redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, retry=no_retry())
    except Exception:
        return None


def _marketdata_breaker_open(client, provider: str) -> bool:
    """True si el breaker del proveedor esta abierto (saltar toda la corrida)."""
    if client is None:
        return False
    try:
        return bool(client.get(f"marketdata_breaker:{provider}:open"))
    except Exception:
        return False


def _marketdata_breaker_record_429(client, provider: str) -> None:
    """Cuenta un 429 del proveedor; a la racha limite abre el breaker."""
    if client is None:
        return
    try:
        streak_key = f"marketdata_breaker:{provider}:429_streak"
        streak = client.incr(streak_key)
        if streak == 1:
            client.expire(streak_key, int(_MARKETDATA_BREAKER_WINDOW_S))
        if streak >= _MARKETDATA_BREAKER_STREAK_LIMIT:
            client.set(
                f"marketdata_breaker:{provider}:open",
                "1",
                ex=int(_MARKETDATA_BREAKER_COOLDOWN_S),
            )
            client.delete(streak_key)
    except Exception:
        return


logger = logging.getLogger(__name__)


def _us_listed(company: Company) -> bool:
    """Solo los listados US pueden cotizar via FMP/Finnhub con el ticker
    pelado: ambos resuelven el simbolo en bolsas americanas y para un emisor
    no-US devuelven el gemelo equivocado - otro emisor (ALM->Almonty) o el
    ADR en USD del mismo emisor (ASML) - y el precio se guarda bajo la
    identidad y divisa del master. Divisa no-USD => fuera. Bolsa US conocida
    => dentro. UNKNOWN con USD (o sin datos) => dentro, el caso mayoritario
    del universo US importado en bulk."""
    exchange = str(getattr(company, "exchange", "") or "").upper()
    currency = str(getattr(company, "currency", "") or "").upper()
    if currency and currency != "USD":
        return False
    if any(token in exchange for token in _US_EXCHANGE_TOKENS):
        return True
    return exchange in ("", "UNKNOWN")


@dataclass(frozen=True)
class PriceObservation:
    ticker: str
    price: Decimal
    price_date: date
    source: str
    # Volumen del dia SOLO si el proveedor lo da: None es honesto, un 0
    # inventado corona al ticker como "menos activo" con un dato falso.
    volume: int | None = None
    quote_currency: str | None = None


class PriceProvider(Protocol):
    async def fetch(
        self, companies: list[Company], *, as_of: date
    ) -> tuple[dict[str, PriceObservation], list[dict]]: ...


class FXProvider(Protocol):
    async def fetch(self, *, base_currency: str, quote_currencies: set[str]) -> ECBRates: ...


class PublicPriceProvider:
    """FMP first, Finnhub fallback, with per-ticker failure isolation.

    Bounded concurrency (semaphore of 6 in flight) plus a per-ticker
    timeout: un proveedor lento nunca bloquea el refresh completo ni
    agota las conexiones.
    """

    MAX_IN_FLIGHT = 6
    PER_TICKER_TIMEOUT_SECONDS = 20.0

    def __init__(self, breaker_client=None) -> None:
        self.fmp = FMPClient()
        self.finnhub = FinnhubClient()
        # Proveedores marcados caidos en ESTA corrida (primer 429 de cada
        # uno): el resto de tickers no los llama - null honesto por ticker
        # con reason provider_unavailable en vez de otro intento a la cuota.
        self._provider_down: set[str] = set()
        self._breaker_client = breaker_client if breaker_client is not None else _marketdata_breaker_client()

    async def fetch(
        self, companies: list[Company], *, as_of: date
    ) -> tuple[dict[str, PriceObservation], list[dict]]:
        down = getattr(self, "_provider_down", None)
        if down is None:
            down = self._provider_down = set()
        client = getattr(self, "_breaker_client", None)
        for provider_name in ("fmp", "finnhub"):
            if _marketdata_breaker_open(client, provider_name):
                down.add(provider_name)
        semaphore = asyncio.Semaphore(self.MAX_IN_FLIGHT)
        rows = await asyncio.gather(*(self._bounded(company, as_of, semaphore) for company in companies))
        observations: dict[str, PriceObservation] = {}
        errors: list[dict] = []
        for company, observation, error in rows:
            if observation:
                observations[company.ticker] = observation
            if error:
                errors.append(error)
        return observations, errors

    async def _bounded(
        self, company: Company, as_of: date, semaphore: asyncio.Semaphore
    ) -> tuple[Company, PriceObservation | None, dict | None]:
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    self._one(company, as_of),
                    timeout=self.PER_TICKER_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                return (
                    company,
                    None,
                    {
                        "ticker": company.ticker,
                        "reason": "per_ticker_timeout",
                    },
                )

    async def _one(
        self, company: Company, as_of: date
    ) -> tuple[Company, PriceObservation | None, dict | None]:
        if not _us_listed(company):
            # Sin precio antes que el precio del gemelo americano: la ruta
            # Yahoo (simbolo con sufijo de bolsa) cubre los mercados no-US.
            return (
                company,
                None,
                {
                    "ticker": company.ticker,
                    "reason": "non_us_listing",
                },
            )
        errors = []
        down = getattr(self, "_provider_down", None)
        if down is None:
            down = self._provider_down = set()
        client = getattr(self, "_breaker_client", None)
        if "fmp" in down:
            errors.append("FMP:provider_unavailable")
        elif self.fmp.configured():
            try:
                # Ruta bulk: sin reintentos inline (un 429 aqui es cuota
                # agotada; el siguiente ciclo del scheduler lo cubre).
                payload = await self.fmp.quote(company.ticker, max_retries=0)
                item = payload[0] if isinstance(payload, list) and payload else None
                value = Decimal(str(item.get("price"))) if isinstance(item, dict) else None
                timestamp = int(item.get("timestamp") or 0) if isinstance(item, dict) else 0
                if value and value > 0:
                    if timestamp <= 0:
                        # Igual que Finnhub: sin timestamp del proveedor no hay
                        # fecha de quote honesta. Antes se fechaba con campos
                        # del profile (metadatos tipo ipoDate/lastUpdated) y un
                        # refresh en fin de semana escribia una barra del
                        # sabado/domingo con el cierre del viernes: movers
                        # planos al 0.00% y cabecera "Datos del" de un dia
                        # sin mercado.
                        errors.append("FMP:quote_missing_timestamp")
                    else:
                        quote_date = datetime.fromtimestamp(timestamp, tz=UTC).date()
                        if quote_date > as_of:
                            errors.append("FMP:quote_date_in_future")
                        else:
                            raw_volume = item.get("volume")
                            volume = int(raw_volume) if raw_volume is not None else None
                            return (
                                company,
                                PriceObservation(company.ticker, value, quote_date, "FMP", volume=volume, quote_currency="USD"),
                                None,
                            )
            except UpstreamRateLimited:
                # Primer 429 del proveedor en la corrida: se marca caido y
                # el resto de tickers no gasta ni una llamada mas en el. La
                # racha del breaker cuenta UNA vez por corrida (guard de
                # transicion): los 429 concurrentes ya en vuelo no inflan
                # el contador - el breaker abre tras N corridas, no N respuestas.
                if "fmp" not in down:
                    down.add("fmp")
                    _marketdata_breaker_record_429(client, "fmp")
                errors.append("FMP:provider_unavailable")
            except Exception as exc:
                errors.append(f"FMP:{type(exc).__name__}")
        if "finnhub" in down:
            errors.append("Finnhub:provider_unavailable")
        elif self.finnhub.configured():
            try:
                payload = await self.finnhub.quote(company.ticker, max_retries=0)
                value = Decimal(str(payload.get("c") or 0))
                timestamp = int(payload.get("t") or 0)
                if value > 0:
                    if timestamp <= 0:
                        # Sin timestamp no podemos fechar la quote con honestidad:
                        # publicarla como de hoy fabricaria el observed_date.
                        errors.append("Finnhub:quote_missing_timestamp")
                    else:
                        observed_date = datetime.fromtimestamp(timestamp, tz=UTC).date()
                        return (
                            company,
                            PriceObservation(company.ticker, value, observed_date, "Finnhub", quote_currency="USD"),
                            None,
                        )
            except UpstreamRateLimited:
                if "finnhub" not in down:
                    down.add("finnhub")
                    _marketdata_breaker_record_429(client, "finnhub")
                errors.append("Finnhub:provider_unavailable")
            except Exception as exc:
                errors.append(f"Finnhub:{type(exc).__name__}")
        reason = ",".join(errors) if errors else "no_price_provider_configured"
        return company, None, {"ticker": company.ticker, "reason": reason}


YahooIntradayFetcher = Callable[[list[str]], dict[str, tuple[Decimal, date] | tuple[Decimal, date, str | None]]]


# Divisa del listado por simbolo (metadato de Yahoo, no cambia): el refresco
# intradia corre cada 15 min en sesion y pedia ``fast_info`` (una peticion
# HTTP en serie) por cada simbolo en CADA pasada. Se recuerda 24 h por
# proceso; un fallo (None) no se recuerda. La entrada guarda el modulo que la
# produjo para que un doble de yfinance en tests nunca reciba datos de otro.
_LISTING_CURRENCY_TTL_S = 24 * 3600.0
_listing_currency_lock = threading.Lock()
_listing_currency_cache: dict[str, tuple[float, object, str]] = {}


def _listing_currency(yf: object, symbol: str) -> str | None:
    now = time.monotonic()
    with _listing_currency_lock:
        hit = _listing_currency_cache.get(symbol)
        if hit is not None and hit[1] is yf and now - hit[0] < _LISTING_CURRENCY_TTL_S:
            return hit[2]
    try:
        unit = yf.Ticker(symbol).fast_info["currency"]  # type: ignore[attr-defined]
    except Exception:
        return None
    if isinstance(unit, str) and unit:
        with _listing_currency_lock:
            _listing_currency_cache[symbol] = (now, yf, unit)
    return unit


def fetch_intraday_yahoo(symbols: list[str]) -> dict[str, tuple[Decimal, date] | tuple[Decimal, date, str | None]]:
    """Ultimo precio intradia (velas de 15 min) via yfinance. Aislado para tests."""
    import yfinance as yf
    from pandas import Timestamp

    if not symbols:
        return {}
    frame = yf.download(
        " ".join(symbols),
        period="1d",
        interval="15m",
        group_by="ticker",
        threads=True,
        progress=False,
        auto_adjust=False,
    )
    if frame is None or frame.empty:
        return {}
    latest: dict[str, tuple[Decimal, date] | tuple[Decimal, date, str | None]] = {}
    for symbol in symbols:
        try:
            try:
                closes = frame[(symbol, "Close")]
            except KeyError:
                closes = frame["Close"]
            closes = closes.dropna()
            if closes.empty:
                continue
            value = Decimal(str(round(float(closes.iloc[-1]), 4)))
            day = Timestamp(closes.index[-1]).date()
            if value > 0:
                # fast_info is provider metadata for this actual symbol. A
                # suffix cannot establish that the raw value is in pence.
                latest[symbol] = (value, day, _listing_currency(yf, symbol))
        except (KeyError, IndexError):
            continue
    return latest


class YahooIntradayPriceProvider:
    """Precios intradia (retardo ~15 min) via Yahoo Finance: gratis, sin key.

    Una sola descarga por lote (yfinance agrupa los tickers), asi el coste
    no crece con el numero de posiciones. Pensado para el refresco de 15
    minutos de la cartera durante la sesion US (F17).
    """

    def __init__(self, fetcher: YahooIntradayFetcher | None = None) -> None:
        self.fetcher = fetcher or fetch_intraday_yahoo

    async def fetch(
        self, companies: list[Company], *, as_of: date
    ) -> tuple[dict[str, PriceObservation], list[dict]]:
        yahoo_by_ticker = {
            company.ticker: symbol for company in companies if (symbol := yahoo_symbol(company)) is not None
        }
        ticker_by_yahoo = {symbol: ticker for ticker, symbol in yahoo_by_ticker.items()}
        try:
            latest = await asyncio.to_thread(self.fetcher, sorted(ticker_by_yahoo))
        except Exception as exc:
            return {}, [{"provider": "yahoo", "reason": redact_secrets(f"{type(exc).__name__}:{exc}")}]
        observations: dict[str, PriceObservation] = {}
        for symbol, observation in latest.items():
            value, day = observation[:2]
            unit = observation[2] if len(observation) > 2 else None
            ticker = ticker_by_yahoo.get(symbol)
            if ticker is None:
                continue
            observations[ticker] = PriceObservation(
                ticker=ticker, price=value, price_date=day, source="yahoo_finance_intraday",
                quote_currency=unit
            )
        errors = [
            {"ticker": company.ticker, "reason": "yahoo_sin_precio_intradia"}
            for company in companies
            if company.ticker not in observations
        ]
        return observations, errors


class ECBFXProvider:
    async def fetch(self, *, base_currency: str, quote_currencies: set[str]) -> ECBRates:
        return await ECBClient().conversion_rates(
            base_currency=base_currency,
            quote_currencies=quote_currencies,
        )


class MarketRefreshService:
    def __init__(
        self,
        price_provider: PriceProvider | None = None,
        fx_provider: FXProvider | None = None,
    ) -> None:
        self.price_provider = price_provider or PublicPriceProvider()
        self.fx_provider = fx_provider or ECBFXProvider()
        self.settings = get_settings()

    async def refresh(
        self,
        db: Session,
        *,
        as_of: date | None = None,
        companies: list[Company] | None = None,
    ) -> dict:
        if db.info.get("tenant_id") is None:
            raise ValueError("Tenant context is required for market refresh")
        as_of = as_of or date.today()
        started = datetime.now(UTC)
        rows = db.execute(
            select(Position, Company)
            .join(Company, Position.company_id == Company.id)
            .order_by(Company.ticker)
        ).all()
        # Prices feed the screener and company alerts as well as the portfolio,
        # so refresh the complete tenant company universe. FX and revaluation
        # remain position-specific in the following stages.
        if companies is None:
            companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
        stages: list[dict] = []

        observations, price_errors = await self.price_provider.fetch(companies, as_of=as_of)
        # Batch: one query for every (company, price_date) row we may update.
        observed = [
            (company, observations[company.ticker]) for company in companies if company.ticker in observations
        ]
        existing_prices = {}
        if observed:
            existing_prices = {
                (price.company_id, price.date): price
                for price in db.scalars(
                    select(MarketPrice).where(
                        MarketPrice.company_id.in_([company.id for company, _ in observed]),
                        MarketPrice.date.in_([obs.price_date for _, obs in observed]),
                    )
                ).all()
            }
        for company, observation in observed:
            market = existing_prices.get((company.id, observation.price_date))
            if market is None:
                # A SPOT price is not a daily bar. Writing one overwrote the
                # real open/high/low/close of that session and set
                # `adj_close = close`, which is by definition "unadjusted" and
                # therefore corrupts every total-return, beta and Sharpe
                # computed over a history that includes a split or a dividend.
                # adj_close stays NULL: the provider gave a spot, not a
                # split/dividend-adjusted series. A NULL is honest; a copy of
                # `close` claims an adjustment that was never performed.
                market = MarketPrice(
                    company_id=company.id,
                    date=observation.price_date,
                    open=observation.price,
                    high=observation.price,
                    low=observation.price,
                    close=observation.price,
                    adj_close=None,
                    volume=observation.volume,
                    source=observation.source,
                    quote_currency=observation.quote_currency,
                )
                db.add(market)
            elif market.source == "yfinance" and observation.price_date < as_of:
                # Barra de una sesion YA cerrada con el cierre oficial del
                # OHLCV: un spot tardio del proveedor (0,01 % de deriva) no la
                # pisa ni le cambia la fuente.
                continue
            else:
                # An existing row is a real bar from the OHLCV path: update
                # only the close, never the session's open/high/low.
                close = observation.price
                if market.quote_currency != observation.quote_currency:
                    # Preserve adjusted history in its stored unit. Unknown
                    # legacy units cannot be reconciled from price magnitude.
                    close = (
                        price_in_currency(
                            observation.price, quote_currency=observation.quote_currency,
                            target_currency=market.quote_currency, company=company,
                        ) if market.quote_currency and observation.quote_currency else None
                    )
                    if close is None:
                        price_errors.append({"ticker": company.ticker, "reason": "incompatible_bar_unit"})
                        continue
                market.close = close
                market.source = observation.source
                # OHL and adjusted values keep their original unit.
                # El volumen solo se toca cuando el proveedor trae uno nuevo:
                # un None intradia nunca pisa el volumen real de la barra.
                if observation.volume is not None:
                    market.volume = observation.volume
        db.commit()
        stages.append(
            {
                "step": 1,
                "name": "update_prices",
                "status": "ok" if not price_errors else "partial",
                "updated": len(observations),
                "errors": price_errors,
            }
        )

        fx = PortfolioFXService()
        base_currency = fx.base_currency(db)
        quote_currencies = {position.currency.upper() for position, _ in rows}
        # La valoracion convierte la divisa de REPORTE de los hechos (BABA: CNY)
        # a la del listado: esas divisas tambien necesitan su tipo BCE del dia,
        # aunque ninguna posicion cotice en ellas. Subunidades (GBX) -> GBP.
        held_ids = {company.id for _, company in rows}
        if held_ids:
            fact_units = db.scalars(
                select(FinancialFact.unit)
                .where(FinancialFact.company_id.in_(held_ids), *tenant_filters(db, FinancialFact))
                .distinct()
            ).all()
            quote_currencies |= reporting_currencies(fact_units)
            quote_currencies = {
                normalize_currency(code)[0] or code for code in quote_currencies
            }
        fx_errors: list[dict] = []
        fx_updated = 0
        try:
            snapshot = await self.fx_provider.fetch(
                base_currency=base_currency,
                quote_currencies=quote_currencies,
            )
            for currency in quote_currencies:
                rate = snapshot.rates.get(currency)
                if rate is None:
                    fx_errors.append({"currency": currency, "reason": "rate_not_available"})
                    continue
                fx.upsert_rate(
                    db,
                    base_currency=base_currency,
                    quote_currency=currency,
                    rate=rate,
                    rate_date=snapshot.rate_date,
                    source="ECB",
                )
                fx_updated += 1
            if base_currency.upper() != TAX_CURRENCY:
                # La fiscalidad (IRPF, Modelo 720) va SIEMPRE en euros al tipo
                # BCE: con una divisa base distinta (USD) se guardan tambien
                # los tipos contra EUR, que es como los publica el BCE.
                tax_quotes = (quote_currencies | {base_currency.upper()}) - {TAX_CURRENCY}
                tax_snapshot = await self.fx_provider.fetch(
                    base_currency=TAX_CURRENCY,
                    quote_currencies=tax_quotes,
                )
                for currency in tax_quotes:
                    rate = tax_snapshot.rates.get(currency)
                    if rate is None:
                        continue
                    fx.upsert_rate(
                        db,
                        base_currency=TAX_CURRENCY,
                        quote_currency=currency,
                        rate=rate,
                        rate_date=tax_snapshot.rate_date,
                        source="ECB",
                    )
            db.commit()
        except Exception as exc:
            db.rollback()
            fx_errors.append({"provider": "ECB", "reason": redact_secrets(f"{type(exc).__name__}:{exc}")})
        stages.append(
            {
                "step": 2,
                "name": "update_fx",
                "status": "ok" if not fx_errors else "partial",
                "updated": fx_updated,
                "errors": fx_errors,
            }
        )

        ledger = PortfolioLedgerService()
        revalued = 0
        stale_prices: list[dict] = []
        # Batch: latest price per position company in one bounded query.
        # The previous form (`order_by(company_id, desc(date))` + `setdefault`)
        # had no LIMIT and no date bound, so it materialised EVERY daily bar
        # ever stored for every held company just to read the newest one. A
        # `row_number() = 1` window per company keeps one row per company on
        # both SQLite and Postgres; ordering is (date DESC NULLS LAST, id DESC)
        # which resolves to the same row as before because
        # (company_id, date) is unique.
        position_company_ids = list({company.id for _, company in rows})
        latest_prices: dict[int, MarketPrice] = {}
        if position_company_ids:
            latest = (
                select(
                    MarketPrice.id.label("id"),
                    func.row_number()
                    .over(
                        partition_by=MarketPrice.company_id,
                        order_by=(
                            MarketPrice.date.desc().nullslast(),
                            desc(MarketPrice.id),
                        ),
                    )
                    .label("rn"),
                )
                .where(MarketPrice.company_id.in_(position_company_ids))
                .subquery("latest_market_price")
            )
            for price in db.scalars(
                select(MarketPrice).join(latest, latest.c.id == MarketPrice.id).where(latest.c.rn == 1)
            ).all():
                latest_prices.setdefault(price.company_id, price)
        # One FX table for every revaluation (point-in-time per row, no N+1).
        refresh_dates = [latest_prices[company.id].date for _, company in rows if company.id in latest_prices]
        fx_table = fx.fx_table(
            db,
            currencies={position.currency for position, _ in rows},
            base_currency=base_currency,
            as_of_max=max(refresh_dates, default=as_of),
        )
        for position, company in rows:
            latest = latest_prices.get(company.id)
            if latest is None:
                stale_prices.append({"ticker": company.ticker, "status": "missing_market_price"})
                continue
            age_days = (as_of - latest.date).days
            max_age = self.settings.market_price_max_age_days
            # A8: refresco de hoy = 24 h desde el cierre de la bolsa (antes de la
            # apertura el cierre de ayer sigue vigente); fecha pasada: días naturales.
            stale = (
                close_is_stale(latest.date, company.exchange, max_age)
                if as_of == date.today()
                else market_price_is_stale(age_days, max_age)
            )
            if stale:
                stale_prices.append(
                    {
                        "ticker": company.ticker,
                        "status": "stale_market_price",
                        "price_date": latest.date.isoformat(),
                        "age_days": age_days,
                    }
                )
            if position.valuation_hold_reason:
                # Suspension de valoracion (p. ej. split sin precio post-split
                # verificado): la cache de cierres no la levanta. Se declara.
                stale_prices.append(
                    {
                        "ticker": company.ticker,
                        "status": "valuation_hold",
                        "reason": position.valuation_hold_reason,
                    }
                )
                continue
            price = price_in_currency(
                latest.close, quote_currency=latest.quote_currency,
                target_currency=position.currency, company=company,
            )
            if price is None:
                ledger._blank_valuation(position)
                stale_prices.append({
                    "ticker": company.ticker, "status": "unknown_price_unit",
                    "quote_currency": latest.quote_currency,
                    "position_currency": position.currency,
                })
                continue
            ledger.update_market_price(
                db,
                company_id=company.id,
                price=price,
                as_of=latest.date,
                position=position,
                fx_rate=PortfolioFXService.rate_from_table(
                    fx_table,
                    quote_currency=position.currency,
                    base_currency=position.base_currency or base_currency,
                    as_of=latest.date,
                ),
            )
            revalued += 1
        db.commit()
        from app.services.portfolio_snapshot_service import PortfolioSnapshotService

        snapshot = PortfolioSnapshotService().capture(
            db,
            as_of=as_of,
            source="market_refresh",
        )
        db.commit()
        stages.append(
            {
                "step": 3,
                "name": "revalue_positions",
                "status": "ok" if not stale_prices else "stale_data",
                "updated": revalued,
                "stale_prices": stale_prices,
                "portfolio_snapshot_id": snapshot.id,
                "snapshot_pricing_coverage": float(snapshot.pricing_coverage),
            }
        )

        risk = RiskService().dashboard(db)
        risk["market_data_status"] = "stale" if stale_prices else "fresh"
        risk["stale_prices"] = stale_prices
        stages.append(
            {
                "step": 4,
                "name": "update_risk",
                "status": risk["status"],
                "market_data_status": risk["market_data_status"],
            }
        )

        alert_results = AlertRuleService().evaluate_all(db)
        screen_results = []
        screen_errors: list[dict] = []
        for screen in db.scalars(
            select(SavedScreen).where(SavedScreen.active.is_(True)).order_by(SavedScreen.id)
        ).all():
            # A screen is the LAST stage: prices, FX, revaluation and the
            # snapshot are already committed. An unevaluable formula or a
            # malformed screen used to propagate out of here and turned the
            # whole refresh into a 500 AFTER a partial commit. One bad screen
            # fails soft and is reported; the rest still run.
            try:
                result = ScreenerService().run_saved(db, screen)
            except Exception as exc:  # noqa: BLE001 — isolate one screen, report it
                db.rollback()
                logger.exception("saved screen %s failed during market refresh", screen.id)
                screen_errors.append(
                    {
                        "saved_screen_id": screen.id,
                        "reason": redact_secrets(f"{type(exc).__name__}:{exc}"),
                    }
                )
                continue
            screen_results.append(
                {
                    "saved_screen_id": screen.id,
                    "matches": result["match_count"],
                    "new_match_company_ids": result["new_match_company_ids"],
                }
            )
        stages.append(
            {
                "step": 5,
                "name": "evaluate_alerts",
                "status": "ok" if not screen_errors else "partial",
                "alert_rules": len(alert_results),
                "saved_screens": len(screen_results),
                "errors": screen_errors,
            }
        )
        return {
            "status": (
                "ok"
                if not price_errors and not fx_errors and not stale_prices and not screen_errors
                else "partial"
            ),
            "as_of": as_of,
            "started_at": started,
            "completed_at": datetime.now(UTC),
            "order": [stage["name"] for stage in stages],
            "stages": stages,
            "risk": risk,
            "alert_results": alert_results,
            "screen_results": screen_results,
        }
