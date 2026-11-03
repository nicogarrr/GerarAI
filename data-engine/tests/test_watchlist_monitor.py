from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, EarningsDate, FundamentalModelVersion, MarketPrice, Tenant, ThesisVersion


def _seed_monitor_fixtures() -> int:
    init_db()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        company = db.query(Company).filter(Company.ticker == "MONTEST").first()
        if company is None:
            company = Company(ticker="MONTEST", name="Monitor Test Co",
                              exchange="NASDAQ", currency="USD",
                              company_type="listed", valuation_model="dcf")
            db.add(company)
            db.flush()
        today = date.today()
        db.query(MarketPrice).filter(MarketPrice.company_id == company.id).delete()
        for i in range(0, 300, 7):
            day = today - timedelta(days=i)
            db.merge(MarketPrice(
                company_id=company.id, date=day,
                open=100, high=105, low=95,
                close=80.0 if i == 210 else 100.0 + i / 10,
                adj_close=None))
        thesis = db.query(ThesisVersion).filter(
            ThesisVersion.company_id == company.id,
            ThesisVersion.version == 3).first()
        if thesis is None:
            db.add(ThesisVersion(
                tenant_id=tenant.id if tenant else 1,
                company_id=company.id, version=3, status="published",
                thesis_markdown="t", executive_summary="s",
                expected_value=150.0))
        model = db.query(FundamentalModelVersion).filter(
            FundamentalModelVersion.company_id == company.id,
            FundamentalModelVersion.version == 1).first()
        if model is None:
            db.add(FundamentalModelVersion(
                tenant_id=tenant.id if tenant else 1,
                company_id=company.id, version=1, engine_version="test", algorithm_version="test",
                framework_key="dcf", horizon_years=10, status="ok", publishable=True,
                input_fingerprint="input", forecast_fingerprint="forecast",
                market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
            ))
        db.commit()
        return company.id
    finally:
        db.close()


def _set_earnings_rows(rows: list[EarningsDate]) -> None:
    db = SessionLocal()
    try:
        db.query(EarningsDate).filter(EarningsDate.ticker == "MONTEST").delete()
        for row in rows:
            db.add(row)
        db.commit()
    finally:
        db.close()


def test_watchlist_monitor_returns_own_data():
    _seed_monitor_fixtures()
    # La fecha viene SOLO de la tabla refrescada por el job (con su fuente y
    # confirmacion); la ruta ya no consulta NASDAQ en vivo.
    _set_earnings_rows([EarningsDate(
        ticker="MONTEST", event_date=date.today() + timedelta(days=9),
        confirmed=True, source="nasdaq+yahoo",
        source_label="Calendario público de NASDAQ + Yahoo Finance (calendarEvents)",
        fetched_at=datetime.now(UTC))])
    client = TestClient(main.app)
    res = client.get("/api/watchlist/monitor", params={"tickers": "montest,NOEXISTE"})
    assert res.status_code == 200
    body = res.json()
    row = body["items"]["MONTEST"]
    assert row["low_52w"] == 80.0
    assert row["low_52w_sessions"] > 30
    assert row["last_close"] is not None
    assert row["fair_value"] == 150.0
    assert row["valuation_side"] == "infravalorada"
    assert row["next_earnings_date"] == (date.today() + timedelta(days=9)).isoformat()
    assert row["next_earnings_source"] == "Calendario público de NASDAQ + Yahoo Finance (calendarEvents)"
    assert row["next_earnings_confirmed"] is True
    assert body["earnings_status"] == "stored"
    assert "NOEXISTE" not in body["items"]


def test_watchlist_monitor_stale_stored_date_is_hidden():
    # Una fila automatica sin renovar en mas de STALE_AFTER no se muestra: el
    # ticker aparece "sin fecha" en lugar de exhibir un dato posiblemente movido.
    _seed_monitor_fixtures()
    _set_earnings_rows([EarningsDate(
        ticker="MONTEST", event_date=date.today() + timedelta(days=9),
        confirmed=True, source="nasdaq",
        source_label="Calendario público de NASDAQ",
        fetched_at=datetime.now(UTC) - timedelta(days=5))])
    client = TestClient(main.app)
    res = client.get("/api/watchlist/monitor", params={"tickers": "MONTEST"})
    assert res.status_code == 200
    row = res.json()["items"]["MONTEST"]
    assert row["next_earnings_date"] is None
    assert row["next_earnings_source"] is None
    assert res.json()["earnings_status"] == "stored"


def test_watchlist_monitor_without_stored_date():
    # Sin fila guardada: hueco honesto a None; nunca una fecha inventada ni una
    # espera de red en la peticion.
    _seed_monitor_fixtures()
    _set_earnings_rows([])
    client = TestClient(main.app)
    res = client.get("/api/watchlist/monitor", params={"tickers": "MONTEST"})
    assert res.status_code == 200
    row = res.json()["items"]["MONTEST"]
    assert row["next_earnings_date"] is None
    assert res.json()["earnings_status"] == "stored"
