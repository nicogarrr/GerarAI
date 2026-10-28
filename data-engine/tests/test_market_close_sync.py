"""market_close_sync: barras oficiales, sin la sesion en curso."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, MarketPrice
from app.services.market_close_sync import sync_official_closes
from app.services.propicks_price_service import PriceBar


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _bars():
    return {
        "AAPL": [
            PriceBar(date(2026, 10, 15), Decimal("342.00"), Decimal("342.00"), 10),
            PriceBar(date(2026, 10, 16), Decimal("343.46"), Decimal("343.46"), 11),
        ]
    }


def _company(db):
    db.add(
        Company(
            ticker="AAPL", name="AAPL", exchange="NASDAQ", currency="USD", sector="S",
            industry="I", company_type="holding", valuation_model="unassigned",
            special_sources=[], special_risks=[], factor_tags=[],
        )
    )
    db.flush()


def test_writes_official_bars_after_close(db):
    _company(db)
    now = datetime(2026, 10, 16, 22, 30, tzinfo=UTC)  # 18:30 Nueva York
    out = sync_official_closes(db, fetcher=lambda symbols, period: _bars(), now=now)
    rows = db.scalars(select(MarketPrice).order_by(MarketPrice.date)).all()
    assert out["bars_written"] == 2 and out["partial_session_skipped"] is False
    assert [r.source for r in rows] == ["yfinance", "yfinance"]


def test_skips_session_in_progress(db):
    _company(db)
    now = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)  # 11:00 Nueva York, sesion abierta
    out = sync_official_closes(db, fetcher=lambda symbols, period: _bars(), now=now)
    rows = db.scalars(select(MarketPrice)).all()
    assert out["partial_session_skipped"] is True
    assert [r.date for r in rows] == [date(2026, 10, 15)]


def test_backfill_writes_history_when_company_has_no_past(db):
    from app.services.market_close_sync import backfill_company_history

    _company(db)
    company = db.scalars(select(Company)).one()
    out = backfill_company_history(
        db, company, fetcher=lambda symbols, period: _bars(), today=date(2026, 10, 16)
    )
    assert out["status"] == "ok" and out["bars_written"] == 2
    rows = db.scalars(select(MarketPrice)).all()
    assert len(rows) == 2


def test_backfill_skips_when_history_is_sufficient(db):
    from app.services.market_close_sync import backfill_company_history

    _company(db)
    company = db.scalars(select(Company)).one()
    db.add(
        MarketPrice(
            company_id=company.id, date=date(2025, 1, 6), open=Decimal("1"),
            high=Decimal("1"), low=Decimal("1"), close=Decimal("1"),
            adj_close=Decimal("1"), source="yfinance",
        )
    )
    db.commit()
    calls = []
    out = backfill_company_history(
        db, company,
        fetcher=lambda symbols, period: calls.append(symbols) or _bars(),
        today=date(2026, 10, 16),
    )
    assert out == {"status": "skipped", "reason": "historico suficiente"}
    assert calls == []  # sin llamada a la fuente cuando no hace falta


def test_backfill_skips_when_source_has_no_bars(db):
    from app.services.market_close_sync import backfill_company_history

    _company(db)
    company = db.scalars(select(Company)).one()
    out = backfill_company_history(
        db, company, fetcher=lambda symbols, period: {}, today=date(2026, 10, 16)
    )
    assert out == {"status": "skipped", "reason": "fuente sin barras"}
    assert db.scalars(select(MarketPrice)).all() == []


def test_companies_needing_history_backfill_one_grouped_query(db):
    from app.services.market_close_sync import companies_needing_history_backfill

    _company(db)
    company = db.scalars(select(Company)).one()
    today = date(2026, 10, 16)
    assert companies_needing_history_backfill(db, [company.id], today=today) == [company.id]
    db.add(
        MarketPrice(
            company_id=company.id, date=date(2025, 1, 6), open=Decimal("1"),
            high=Decimal("1"), low=Decimal("1"), close=Decimal("1"),
            adj_close=Decimal("1"), source="yfinance",
        )
    )
    db.commit()
    assert companies_needing_history_backfill(db, [company.id], today=today) == []
    # Historia reciente pero superficial (solo la ultima semana del sync
    # diario) sigue necesitando backfill.
    db.query(MarketPrice).delete()
    db.add(
        MarketPrice(
            company_id=company.id, date=date(2026, 10, 10), open=Decimal("1"),
            high=Decimal("1"), low=Decimal("1"), close=Decimal("1"),
            adj_close=Decimal("1"), source="yfinance",
        )
    )
    db.commit()
    assert companies_needing_history_backfill(db, [company.id], today=today) == [company.id]


def test_enqueue_price_backfills_staggers_sends_and_skips_covered(db):
    """Una importacion con N companias nuevas no puede disparar N llamadas
    simultaneas contra Yahoo: delays incrementales y solo para las que no
    tienen historial profundo."""
    from app.services.market_close_sync import enqueue_price_backfills

    for ticker in ("AAA", "BBB", "CCC", "DDD"):
        db.add(
            Company(
                ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                sector="S", industry="I", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[],
                factor_tags=[],
            )
        )
    db.flush()
    ids = {
        c.ticker: c.id
        for c in db.scalars(select(Company).where(Company.ticker.in_(["AAA", "BBB", "CCC", "DDD"])))
    }
    # DDD ya tiene historial profundo: no se encola.
    db.add(
        MarketPrice(
            company_id=ids["DDD"], date=date(2025, 1, 6), open=Decimal("1"),
            high=Decimal("1"), low=Decimal("1"), close=Decimal("1"),
            adj_close=Decimal("1"), source="yfinance",
        )
    )
    db.commit()

    sent = []
    n = enqueue_price_backfills(
        db,
        list(ids.values()),
        stagger_ms=60_000,
        sender=lambda cid, tenant, user, delay: sent.append((cid, tenant, user, delay)),
        today=date(2026, 10, 16),
        tenant_id=7,
        user_id="u1",
    )
    assert n == 3
    assert [delay for *_ , delay in sent] == [0, 60_000, 120_000]
    assert {cid for cid, *_ in sent} == {ids["AAA"], ids["BBB"], ids["CCC"]}
    assert all(tenant == 7 and user == "u1" for _, tenant, user, _ in sent)


def test_un_lote_caido_no_deja_sin_cierre_a_los_demas(db):
    for ticker in ("AAPL", "MSFT"):
        db.add(
            Company(
                ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD", sector="S",
                industry="I", company_type="holding", valuation_model="unassigned",
                special_sources=[], special_risks=[], factor_tags=[],
            )
        )
    db.flush()
    bar = PriceBar(date(2026, 10, 15), Decimal("10"), Decimal("10"), 1)

    def fetcher(symbols, period):
        if symbols == ["AAPL"]:
            raise TimeoutError("yahoo timeout")
        return {s: [bar] for s in symbols}

    now = datetime(2026, 10, 16, 22, 30, tzinfo=UTC)
    out = sync_official_closes(db, fetcher=fetcher, now=now, chunk=1)
    assert out["status"] == "partial"
    assert out["failed_symbols"] == ["AAPL"]
    assert out["covered"] == 1


def test_todos_los_lotes_caidos_propaga_el_error(db):
    _company(db)

    def fetcher(symbols, period):
        raise TimeoutError("yahoo timeout")

    with pytest.raises(TimeoutError):
        sync_official_closes(db, fetcher=fetcher, now=datetime(2026, 10, 16, 22, 30, tzinfo=UTC))


def test_target_date_coverage_not_historical_coverage(db):
    _company(db)
    for ticker in ['MSFT','NVDA','META']:
        db.add(Company(ticker=ticker,name=ticker,exchange='NASDAQ',currency='USD',sector='S',industry='I',company_type='holding',valuation_model='unassigned',special_sources=[],special_risks=[],factor_tags=[]))
    db.flush()
    old=PriceBar(date(2026,10,26),Decimal('10'),Decimal('10'),10)
    fresh=PriceBar(date(2026,10,27),Decimal('11'),Decimal('11'),11)
    history={t:[old] for t in ['AAPL','MSFT','NVDA','META']}
    history['AAPL']=[old,fresh]
    out=sync_official_closes(db,fetcher=lambda symbols,period:history,now=datetime(2026,10,28,3,tzinfo=UTC))
    assert out['covered']==4
    assert out['target_date']=='2026-10-27'
    assert out['target_covered']==1 and out['target_coverage']==.25
    assert out['status']=='partial'


def test_fully_covered_target_date_is_success(db):
    _company(db)
    bar=PriceBar(date(2026,10,27),Decimal('11'),Decimal('11'),11)
    out=sync_official_closes(db,fetcher=lambda symbols,period:{'AAPL':[bar]},now=datetime(2026,10,28,3,tzinfo=UTC))
    assert out['target_coverage']==1.0 and out['status']=='ok'
