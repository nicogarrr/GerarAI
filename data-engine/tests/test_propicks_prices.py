"""F2: ingesta de precios ProPicks + momentum (yahoo symbol, upsert, metricas)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Company,
    MarketPrice,
    ProPickCandidate,
    ProPickRun,
    Tenant,
)
from app.services.propicks_price_service import (
    PriceBar,
    momentum_from_series,
    refresh_propicks_prices,
    upsert_prices,
    yahoo_symbol,
)


def _company(ticker: str, currency: str = "USD") -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="NASDAQ",
        currency=currency,
        sector="Industrials",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="prices-test", name="Prices test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def _series(days: int, start: str = "100") -> list[tuple[date, Decimal]]:
    base = date(2026, 9, 25) - timedelta(days=days)
    price = Decimal(start)
    out = []
    for i in range(days + 1):
        out.append((base + timedelta(days=i), price))
        price = price + Decimal("1")
    return out


def _fake_fetcher(symbols, *, period="1y"):
    bars = {}
    for symbol in symbols:
        bars[symbol] = [
            PriceBar(day=d, close=p, adj_close=p, volume=1000) for d, p in _series(400)
        ]
    return bars


def test_yahoo_symbol_mapea_bolsa_o_devuelve_none_honesto():
    # Bolsa mapeada: sufijo del listado real.
    assert yahoo_symbol(_company("TEF", currency="EUR")) is None  # NASDAQ+EUR: incoherente, sin símbolo
    assert yahoo_symbol(_company("AAPL", currency="USD")) == "AAPL"


def test_momentum_6m_and_12m():
    series = _series(400)
    mom6 = momentum_from_series(series, 182)
    mom12 = momentum_from_series(series, 365)
    assert mom6 is not None and mom6 > 0
    assert mom12 is not None and mom12 > mom6  # serie creciente: 12m > 6m
    # Esperado 6m: ultimo 500, hace 182 dias 318
    expected = (Decimal(500) - Decimal(318)) / Decimal(318)
    assert abs(mom6 - expected) < Decimal("0.001")


def test_momentum_honest_without_data():
    assert momentum_from_series([], 126) is None
    assert momentum_from_series(_series(30), 126) is None  # punto pasado demasiado lejos


def test_upsert_idempotent():
    with _db() as db:
        company = _company("IDEM")
        db.add(company)
        db.flush()
        bars = [PriceBar(day=date(2026, 9, 24), close=Decimal("10"), adj_close=Decimal("9.5"), volume=100)]
        assert upsert_prices(db, company, bars) == 1
        bars2 = [PriceBar(day=date(2026, 9, 24), close=Decimal("11"), adj_close=Decimal("10.5"), volume=200)]
        assert upsert_prices(db, company, bars2) == 1
        db.commit()
        rows = db.scalars(select(MarketPrice).where(MarketPrice.company_id == company.id)).all()
        assert len(rows) == 1
        assert rows[0].close == Decimal("11")
        assert rows[0].source == "yfinance"


def test_refresh_writes_metrics_only_with_coverage():
    with _db() as db:
        from datetime import UTC, datetime
        run = ProPickRun(as_of=datetime.now(UTC), status="completed", funnel_version="test",
                         universe_size=1, passed_count=1, top_n=5, duration_ms=1, params={})
        db.add(run)
        company = _company("MOMCO")
        db.add(company)
        db.flush()
        db.add(ProPickCandidate(run_id=run.id, company_id=company.id, passed=True,
                                rank=1, score=90.0, failed_gates=[], metrics={}, coverage={}))
        db.commit()

        result = refresh_propicks_prices(db, top_n=5, fetcher=_fake_fetcher,
                                         as_of=date(2026, 9, 25))
        assert result["status"] == "ok"
        assert result["covered"] == 1
        assert result["bars_written"] == 401
        metrics = db.scalars(
            select(CalculatedMetric).where(CalculatedMetric.company_id == company.id)
        ).all()
        assert {m.metric for m in metrics} == {"momentum_6m", "momentum_12m"}
        assert all(m.value is not None and m.value > 0 for m in metrics)
        assert all("yfinance" in m.formula for m in metrics)


def test_refresh_skips_without_run():
    with _db() as db:
        result = refresh_propicks_prices(db, fetcher=_fake_fetcher)
        assert result["status"] == "skipped"


def test_refresh_cubre_todas_las_aprobadas_no_solo_el_top():
    """Las joyas viven fuera del top rankeado: sin precio fresco de todas las
    aprobadas, find_gems nunca las ve (regresion: pestana de joyas vacia)."""
    with _db() as db:
        from datetime import UTC, datetime

        run = ProPickRun(
            as_of=datetime.now(UTC), status="completed", funnel_version="test",
            universe_size=3, passed_count=3, top_n=1, duration_ms=1, params={},
        )
        db.add(run)
        companies = [_company("RANK1"), _company("GEM1"), _company("GEM2")]
        for company in companies:
            db.add(company)
        db.flush()
        db.add_all(
            [
                ProPickCandidate(run_id=run.id, company_id=companies[0].id, passed=True,
                                 rank=1, score=95.0, failed_gates=[], metrics={}, coverage={}),
                ProPickCandidate(run_id=run.id, company_id=companies[1].id, passed=True,
                                 rank=None, score=70.0, failed_gates=[], metrics={}, coverage={}),
                ProPickCandidate(run_id=run.id, company_id=companies[2].id, passed=True,
                                 rank=None, score=60.0, failed_gates=[], metrics={}, coverage={}),
            ]
        )
        db.commit()

        result = refresh_propicks_prices(
            db, top_n=1, fetcher=_fake_fetcher, as_of=date(2026, 9, 25)
        )
        assert result["status"] == "ok"
        assert result["companies"] == 3
        assert result["covered"] == 3
        assert result["bars_written"] == 3 * 401
        metrics = db.scalars(select(CalculatedMetric)).all()
        assert {m.company_id for m in metrics} == {c.id for c in companies}


def test_fetch_history_descarta_barras_nan(monkeypatch):
    import sys
    import types

    import pandas as pd

    from app.services.propicks_price_service import fetch_history_yfinance

    idx = pd.to_datetime(["2026-10-14", "2026-10-15", "2026-10-16"])
    frame = pd.DataFrame(
        {
            "Close": [10.0, float("nan"), 11.0],
            "Adj Close": [10.0, float("nan"), 11.0],
            "Volume": [100, 0, 200],
        },
        index=idx,
    )
    fake = types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(history=lambda **k: frame))
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    out = fetch_history_yfinance(["AAA"], period="1y")
    assert [b.day.isoformat() for b in out["AAA"]] == ["2026-10-14", "2026-10-16"]


def test_upsert_descarta_la_barra_de_hoy_con_sesion_abierta():
    """La foto intradia de hoy no es un cierre: no se escribe a media sesión."""
    company_bar = PriceBar(day=date(2026, 10, 19), close=Decimal("10"), adj_close=Decimal("9.5"), volume=100)
    old_bar = PriceBar(day=date(2026, 10, 16), close=Decimal("9"), adj_close=Decimal("8.5"), volume=100)
    # Lunes 19 oct 2026, 11:00 ET = sesión abierta.
    during = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
    # Lunes 19 oct 2026, 17:00 ET = sesión cerrada (>16:30 ET).
    after = datetime(2026, 10, 19, 21, 0, tzinfo=UTC)
    with _db() as db:
        company = _company("INTR")
        db.add(company)
        db.flush()
        assert upsert_prices(db, company, [company_bar, old_bar], now=during) == 1
        db.commit()
        rows = db.scalars(select(MarketPrice).where(MarketPrice.company_id == company.id)).all()
        assert [row.date for row in rows] == [date(2026, 10, 16)]
        # Con la sesión cerrada, la barra del día sí es el cierre oficial.
        assert upsert_prices(db, company, [company_bar], now=after) == 1
        db.commit()
        days = {row.date for row in db.scalars(select(MarketPrice).where(MarketPrice.company_id == company.id)).all()}
        assert days == {date(2026, 10, 16), date(2026, 10, 19)}


def test_upsert_nan_volume_does_not_overwrite_real_volume():
    """Un re-sync con Volume=NaN (yfinance: LSE, indices, sesiones parciales)
    NO pisa a 0 el volumen real ya guardado: 0 es ausencia fabricada."""
    db = _db()
    company = _company("VOL1")
    db.add(company)
    db.commit()
    day = date(2026, 10, 28)
    db.add(MarketPrice(company_id=company.id, date=day, open=100, high=100,
                       low=100, close=100, adj_close=100, volume=5_000_000,
                       quote_currency="USD", source="yfinance"))
    db.commit()
    bar = PriceBar(day=day, close=Decimal("101"), adj_close=Decimal("101"),
                   volume=0, quote_currency="USD")
    written = upsert_prices(db, company, [bar], now=datetime(2026, 10, 30, tzinfo=UTC))
    db.commit()
    row = db.scalar(select(MarketPrice).where(MarketPrice.company_id == company.id))
    assert written == 1
    assert row.close == Decimal("101")
    assert row.volume == 5_000_000


def test_upsert_absent_volume_inserts_null_not_zero():
    """En insercion, volumen ausente se guarda NULL (contrato del modelo:
    NULL = la fuente no da el dato), nunca un 0 fabricado."""
    db = _db()
    company = _company("VOL2")
    db.add(company)
    db.commit()
    bar = PriceBar(day=date(2026, 10, 28), close=Decimal("50"),
                   adj_close=Decimal("50"), volume=0, quote_currency="USD")
    upsert_prices(db, company, [bar], now=datetime(2026, 10, 30, tzinfo=UTC))
    db.commit()
    row = db.scalar(select(MarketPrice).where(MarketPrice.company_id == company.id))
    assert row.volume is None
