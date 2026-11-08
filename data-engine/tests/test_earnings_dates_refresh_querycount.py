"""Conteo de sentencias SQL del refresco de fechas de resultados.

Medicion con contadores (regla del repo: nunca wall-clock). El refresco
recorre los tickers seguidos (cartera + watchlist); antes del arreglo cada
ticker costaba 1 SELECT extra (fila manual), 1 DELETE propio y hasta 2 SELECT
mas en la rama de fecha pasada: el coste crecia ~3 sentencias por ticker.

Contrato fijado aqui: al pasar de 3 a 24 tickers seguidos, el numero de
sentencias solo crece por los INSERT nuevos (1 por ticker con fecha futura):
los SELECT y DELETE del barrido son O(1) respecto al numero de tickers.
"""

from datetime import date

from sqlalchemy import event, select

from app.core.database import SessionLocal, init_db
from app.models import Company, EarningsDate, Tenant, WatchItem
from app.services.earnings_dates_service import refresh_earnings_dates

TODAY = date(2026, 11, 9)
FUTURE = date(2026, 11, 17)


def _tenant_with_watch(db, count: int, tag: str) -> list[str]:
    from uuid import uuid4

    uid = uuid4().hex[:6].upper()
    tenant = Tenant(external_id=f"qc-{tag}-{uid}", name=f"{tag}{uid}")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    tickers = []
    for i in range(count):
        ticker = f"Q{tag}{uid[:4]}{i:02d}"
        tickers.append(ticker)
        db.add(Company(ticker=ticker, name=f"{ticker} Inc", exchange="NYSE",
                       currency="USD", company_type="research_candidate",
                       valuation_model="unassigned"))
        db.add(WatchItem(symbol=ticker, company=ticker, tenant_id=tenant.id))
    db.commit()
    return tickers


def _count_statements(db, fn) -> int:
    engine = db.get_bind()
    count = 0

    def _before(*_args):
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    return count


def _refresh(db, tickers):
    # followed_companies clavea en mayusculas: el fetcher responde por syms.
    return refresh_earnings_dates(
        db,
        today=TODAY,
        yahoo_fetcher=lambda syms: {t: {"date": FUTURE, "estimate": False} for t in syms},
        nasdaq_fetcher=lambda tickers_, today_: {},
    )


def test_refresh_statement_count_grows_only_with_inserts():
    """3 -> 24 tickers: solo 21 sentencias mas (los INSERT), no ~3 por ticker."""
    init_db()
    db = SessionLocal()
    try:
        small = _tenant_with_watch(db, 3, "s")
        n_small = _count_statements(db, lambda: _refresh(db, small))

        big = _tenant_with_watch(db, 24, "b")
        n_big = _count_statements(db, lambda: _refresh(db, big))

        extra_inserts = len(big) - len(small)
        # Antes del arreglo: cada ticker extra sumaba SELECT manual + DELETE
        # propio + INSERT (3 sentencias): aqui salian ~63. Con el barrido
        # agrupado solo quedan los INSERT: exactamente 21 (+2 de margen).
        assert n_big - n_small <= extra_inserts + 2, (
            f"sentencias small={n_small} big={n_big}: crece mas que los inserts"
        )
        # Y el contrato visible no cambia: una fila futura por ticker.
        assert db.query(EarningsDate).count() >= len(big)
    finally:
        db.rollback()
        db.close()


def test_refresh_counts_disagreements_and_survives_dead_sources():
    """Yahoo y NASDAQ en desacuerdo se contabilizan; una fuente caida no tira la otra."""
    init_db()
    db = SessionLocal()
    try:
        tickers = _tenant_with_watch(db, 2, "d")

        def _dead_yahoo(syms):
            raise ConnectionError("yahoo caido")

        nasdaq_day = date(2026, 11, 18)
        result = refresh_earnings_dates(
            db,
            today=TODAY,
            yahoo_fetcher=_dead_yahoo,
            nasdaq_fetcher=lambda tickers_, today_: {
                t: {"date": nasdaq_day, "session": "pre_market", "fiscal": None}
                for t in tickers_
            },
        )
        assert result["written"] == 2 and result["date_disagreements"] == 0

        # Ahora ambas fuentes vivas con fechas distintas: desacuerdo contado,
        # gana Yahoo (merge_candidate) y la fila escrita es la de Yahoo.
        yahoo_day = date(2026, 11, 24)
        result = refresh_earnings_dates(
            db,
            today=TODAY,
            yahoo_fetcher=lambda syms: {t: {"date": yahoo_day, "estimate": False} for t in syms},
            nasdaq_fetcher=lambda tickers_, today_: {
                t: {"date": nasdaq_day, "session": None, "fiscal": None} for t in tickers_
            },
        )
        assert result["date_disagreements"] == 2 and result["written"] == 2
        sources = {r.ticker: (r.event_date, r.source) for r in db.scalars(
            select(EarningsDate).where(EarningsDate.event_date >= TODAY)
        )}
        for t in (t.upper() for t in tickers):
            assert sources[t] == (yahoo_day, "yahoo")
    finally:
        db.rollback()
        db.close()
