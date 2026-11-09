"""PR-3: monitor programado de watchlist/cartera contra SEC Form 4."""

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.database import SessionLocal, init_db
from app.models.entities import (
    Company,
    ConnectorState,
    InsiderFiling,
    InsiderTransaction,
    Portfolio,
    Position,
    WatchItem,
)
from app.services import insider_monitor
from app.services.connectors import form4 as form4_connector
from tests.test_insider_signals import CEO_BUY_XML

FILING_1 = {
    "form": "4",
    "accession_number": "0001234567-24-000101",
    "filing_date": "2024-03-16",
    "report_date": "2024-03-15",
    "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/f4a.xml",
    "index_url": "https://www.sec.gov/Archives/edgar/data/1234567/",
}
FILING_2 = {
    **FILING_1,
    "accession_number": "0001234567-24-000102",
    "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/f4b.xml",
}


def _db():
    init_db()
    return SessionLocal()


def _cleanup(db):
    db.query(InsiderTransaction).delete()
    db.query(InsiderFiling).delete()
    db.query(ConnectorState).filter(ConnectorState.connector == "insider_monitor").delete()
    db.query(WatchItem).delete()
    db.query(Position).delete()
    db.query(Portfolio).delete()
    db.query(Company).filter(Company.ticker.in_(["ZZT"])).delete()
    db.commit()


def _seed_watchlist(db, *, with_position=False):
    db.add(WatchItem(symbol="ZZT", company="ZZ Test Corp"))
    company = db.scalar(select(Company).where(Company.ticker == "ZZT"))
    if company is None:
        company = Company(
            ticker="ZZT", name="ZZ Test Corp", exchange="NASDAQ",
            company_type="compounders", valuation_model="dcf", cik="0001234567",
        )
        db.add(company)
        db.flush()
    if with_position:
        portfolio = Portfolio(name="Main")
        db.add(portfolio)
        db.flush()
        db.add(Position(portfolio_id=portfolio.id, company_id=company.id, quantity=10))
    db.commit()
    return company


def _patch_filings(monkeypatch, filings_by_cik):
    def fake_recent(cik, *, limit=10, client=None):
        return filings_by_cik.get(cik, [])[:limit]

    monkeypatch.setattr(form4_connector, "recent_form4_filings", fake_recent)


def _fetcher(filing):
    return CEO_BUY_XML


def test_scan_persists_new_filings_and_updates_state(monkeypatch):
    db = _db()
    try:
        _cleanup(db)
        _seed_watchlist(db)
        _patch_filings(monkeypatch, {"0001234567": [FILING_1]})

        stats = insider_monitor.scan(
            db, fetcher=_fetcher, delay_seconds=0, lookback=20,
        )
        assert stats["status"] == "ok"
        assert stats["tickers_scanned"] == 1
        assert stats["filings_new"] == 1
        assert stats["transactions_created"] >= 1

        filing = db.scalar(select(InsiderFiling))
        assert filing.accession_number == FILING_1["accession_number"]

        state = db.scalar(
            select(ConnectorState).where(ConnectorState.connector == "insider_monitor")
        )
        assert state.consecutive_errors == 0
        assert state.last_success_at is not None
        assert state.metadata_["runs"] == 1
        assert state.metadata_["filings_new_total"] == 1
    finally:
        _cleanup(db)
        db.close()


def test_second_scan_is_idempotent(monkeypatch):
    db = _db()
    try:
        _cleanup(db)
        _seed_watchlist(db)
        _patch_filings(monkeypatch, {"0001234567": [FILING_1]})

        first = insider_monitor.scan(db, fetcher=_fetcher, delay_seconds=0)
        second = insider_monitor.scan(db, fetcher=_fetcher, delay_seconds=0)
        assert first["filings_new"] == 1
        assert second["filings_new"] == 0
        assert second["transactions_created"] == 0
        assert len(db.scalars(select(InsiderFiling)).all()) == 1
    finally:
        _cleanup(db)
        db.close()


def test_scan_respects_fetch_budget(monkeypatch):
    db = _db()
    try:
        _cleanup(db)
        _seed_watchlist(db)
        _patch_filings(monkeypatch, {"0001234567": [FILING_1, FILING_2]})

        stats = insider_monitor.scan(
            db, fetcher=_fetcher, delay_seconds=0, max_new_fetches=1,
        )
        assert stats["filings_new"] == 1
        assert len(db.scalars(select(InsiderFiling)).all()) == 1
    finally:
        _cleanup(db)
        db.close()


def test_portfolio_positions_are_scanned(monkeypatch):
    db = _db()
    try:
        _cleanup(db)
        company = _seed_watchlist(db, with_position=True)
        # Sin watch_items: la posicion basta para incluir el emisor.
        db.query(WatchItem).delete()
        db.commit()
        _patch_filings(monkeypatch, {company.cik: [FILING_1]})

        stats = insider_monitor.scan(db, fetcher=_fetcher, delay_seconds=0)
        assert stats["tickers_scanned"] == 1
        assert stats["filings_new"] == 1
    finally:
        _cleanup(db)
        db.close()


def test_broken_filing_degrades_to_partial(monkeypatch):
    db = _db()
    try:
        _cleanup(db)
        _seed_watchlist(db)
        _patch_filings(monkeypatch, {"0001234567": [FILING_1, FILING_2]})

        def flaky_fetcher(filing):
            if filing["accession_number"] == FILING_1["accession_number"]:
                raise ValueError("xml corrupto")
            return CEO_BUY_XML

        stats = insider_monitor.scan(db, fetcher=flaky_fetcher, delay_seconds=0)
        assert stats["status"] == "partial"
        assert stats["filings_new"] == 1
        assert any("xml corrupto" not in e and "ValueError" in e for e in stats["errors"])
        # La corrida se considera exitosa a nivel conector: el error es por filing.
        state = db.scalar(
            select(ConnectorState).where(ConnectorState.connector == "insider_monitor")
        )
        assert state.consecutive_errors == 0
    finally:
        _cleanup(db)
        db.close()


def test_empty_watchlist_skips_cleanly():
    db = _db()
    try:
        _cleanup(db)
        stats = insider_monitor.scan(db, delay_seconds=0)
        assert stats["status"] == "skipped"
        state = db.scalar(
            select(ConnectorState).where(ConnectorState.connector == "insider_monitor")
        )
        assert state.metadata_["runs"] == 1
    finally:
        _cleanup(db)
        db.close()


class _FlakyFirstCommit:
    """Proxy de Session cuyo primer commit lanza (sesion caida al arrancar)."""

    def __init__(self, real):
        self._real = real
        self._failed = False

    def __getattr__(self, name):
        return getattr(self._real, name)

    def commit(self):
        if not self._failed:
            self._failed = True
            raise OperationalError("commit", {}, Exception("db down"))
        return self._real.commit()


def test_scan_first_commit_failure_is_recorded_not_raised():
    """El commit inicial del estado va dentro del try: con la sesion caida al
    arrancar, scan devuelve stats de error y deja last_error en vez de lanzar
    al actor (el docstring promete 'nunca lanza')."""
    db = _db()
    try:
        _cleanup(db)
        stats = insider_monitor.scan(_FlakyFirstCommit(db), delay_seconds=0)
        assert stats["status"] == "error"
        assert any(e.startswith("fatal:") for e in stats["errors"])
        state = db.scalar(
            select(ConnectorState).where(ConnectorState.connector == "insider_monitor")
        )
        assert state is not None
        assert (state.consecutive_errors or 0) >= 1
        assert state.last_error and "OperationalError" in state.last_error
    finally:
        _cleanup(db)
        db.close()
