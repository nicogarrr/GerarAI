"""Calendario unico de catalizadores: formatos REALES de NASDAQ, cartera US y honestidad.

Las filas de NASDAQ usadas aqui replican lo medido en la API real: consenso
negativo entre parentesis ("($0.05)"), franjas "time-pre-market" /
"time-after-hours" / "time-not-supplied" y dividendos devueltos solo el dia de
su fecha ex.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, CorporateAction, Position
from app.services import catalyst_calendar_service as svc
from app.services.connectors import earnings_calendar as connector

D0, D1 = date(2026, 10, 14), date(2026, 10, 28)


@pytest.fixture(autouse=True)
def _no_sec_network(monkeypatch):
    """Hermetico: los plazos 10-Q/10-K consultan EDGAR; por defecto sin red ni datos."""

    async def cik(*_args, **_kwargs):
        return "0000000001"

    async def empty_submissions(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(svc, "_default_sec_fetchers", lambda: (cik, empty_submissions))


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker, qty, *, exchange="NASDAQ", currency="USD"):
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, currency=currency,
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(Position(company_id=company.id, quantity=Decimal(str(qty)), average_cost=1,
                    market_price=1, currency=currency))
    db.commit()
    return company


def test_parse_float_negative_in_parentheses():
    assert connector._parse_float("($0.05)") == pytest.approx(-0.05)
    assert connector._parse_float("$2.95") == pytest.approx(2.95)
    assert connector._parse_float("220,000,000,000") == pytest.approx(2.2e11)
    assert connector._parse_float("N/A") is None


def test_held_tickers_split_all_vs_us_only(db):
    _company(db, "aaa", 5)
    _company(db, "BBB", 0)
    _company(db, "ALM", 3, exchange="BME", currency="EUR")
    todos, solo_us = svc.held_tickers(db)
    assert todos == {"AAA", "ALM"}
    assert solo_us == {"AAA"}


def test_pending_actions_only_unapplied_in_range(db):
    c = _company(db, "AAA", 5)
    for eff, applied in ((date(2026, 10, 20), False), (date(2026, 10, 21), True),
                         (date(2026, 12, 1), False)):
        db.add(CorporateAction(company_id=c.id, action_type="split", effective_date=eff,
                               ratio=Decimal("2"), description="", applied=applied))
    db.commit()
    rows = svc.pending_actions(db, D0, D1)
    assert [r["effective_date"] for r in rows] == ["2026-10-20"]


def test_build_real_nasdaq_formats_and_us_only():
    events = svc.build_catalysts(
        held={"LOOP", "KO", "ALM"},
        held_us={"LOOP", "KO"},
        desde=D0,
        hasta=D1,
        earnings=[
            connector.normalize_earnings_row(
                {"symbol": "LOOP", "time": "time-pre-market", "epsForecast": "($0.05)"},
                date(2026, 10, 22),
            ),
            connector.normalize_earnings_row(
                {"symbol": "ALM", "time": "time-after-hours", "epsForecast": "$1.00"},
                date(2026, 10, 22),
            ),
            connector.normalize_earnings_row(
                {"symbol": "KO", "time": "time-not-supplied", "epsForecast": ""},
                date(2026, 10, 23),
            ),
        ],
        dividends=[
            connector.normalize_dividend_row(
                {"symbol": "KO", "dividend_Ex_Date": "10/16/2026",
                 "payment_Date": "10/30/2026", "dividend_Rate": 0.51},
                date(2026, 10, 16),
            ),
        ],
        actions=[{"ticker": "ALM", "action_type": "split", "effective_date": "2026-10-22",
                  "ratio": 2.0}],
    )
    got = [(e["date"], e["ticker"], e["type"], e["detail"]) for e in events]
    assert got == [
        ("2026-10-16", "KO", "dividend_ex", "0,5100 por acción · pago el 30/10/2026"),
        ("2026-10-22", "LOOP", "earnings", "antes de la apertura, BPA estimado -0,05"),
        ("2026-10-22", "ALM", "corporate_action", "ratio 2"),
        ("2026-10-23", "KO", "earnings", "hora por confirmar"),
    ]
    assert all(e["source"] for e in events)
    assert not any(e["type"] == "dividend_pay" for e in events)
    assert not any("time-" in (e["detail"] or "") for e in events)


def test_no_invented_dates_when_source_has_none():
    events = svc.build_catalysts(
        held={"AAA"}, held_us={"AAA"}, desde=D0, hasta=D1,
        earnings=[{"symbol": "AAA", "date": None}], dividends=[], actions=[],
    )
    assert events == []


def test_combine_status():
    assert svc.combine_status("ok", "ok") == "ok"
    assert svc.combine_status("ok", "partial") == "partial"
    assert svc.combine_status("unavailable", "unavailable") == "unavailable"
    assert svc.combine_status("ok", "unavailable") == "partial"


def _route_client(engine, monkeypatch, *, earnings_rows, dividend_rows):
    import main
    from app.core.database import get_db

    async def fake_json(url, params, client):
        day = params["date"]
        if url == connector.EARNINGS_URL:
            return {"data": {"rows": earnings_rows if day == "2026-10-22" else []}}
        return {"data": {"calendar": {"rows": dividend_rows if day == "2026-10-16" else []}}}

    monkeypatch.setattr(connector, "_get_json", fake_json)

    def override():
        with Session(engine) as session:
            session.info["tenant_id"] = "tenant-test"
            yield session

    main.app.dependency_overrides[get_db] = override
    return TestClient(main.app, raise_server_exceptions=False), main


def test_catalysts_route_end_to_end_with_real_formats(engine, db, monkeypatch):
    _company(db, "LOOP", 10)
    _company(db, "ALM", 3, exchange="BME", currency="EUR")
    client, main = _route_client(
        engine,
        monkeypatch,
        earnings_rows=[
            {"symbol": "LOOP", "name": "Loop", "time": "time-pre-market", "epsForecast": "($0.05)"},
            {"symbol": "ALM", "name": "Otro emisor", "time": "time-after-hours"},
        ],
        dividend_rows=[
            {"symbol": "LOOP", "companyName": "Loop", "dividend_Ex_Date": "10/16/2026",
             "payment_Date": "10/30/2026", "dividend_Rate": 0.25},
        ],
    )
    try:
        res = client.get("/api/calendar/catalysts?desde=2026-10-14&hasta=2026-10-28")
    finally:
        main.app.dependency_overrides.clear()
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["held_count"] == 2
    assert [(e["date"], e["ticker"], e["type"]) for e in body["events"]] == [
        ("2026-10-16", "LOOP", "dividend_ex"),
        ("2026-10-22", "LOOP", "earnings"),
    ]
    assert body["events"][1]["detail"] == "antes de la apertura, BPA estimado -0,05"


# Formato REAL de data.sec.gov/submissions (medido con AAPL, 2026-10): category,
# fiscalYearEnd "MMDD" y filings.recent con form/reportDate en listas paralelas.
def _subs(rows, *, category="Large accelerated filer", fye="0926"):
    return {
        "category": category,
        "fiscalYearEnd": fye,
        "filings": {"recent": {"form": [f for f, _ in rows], "reportDate": [r for _, r in rows]}},
    }


NOISE = [("4", "2026-10-06"), ("8-K", "2026-07-30"), ("144", "")]
APPLE = _subs([
    *NOISE,
    ("10-Q", "2026-06-27"), ("10-Q", "2026-03-28"), ("10-Q", "2025-12-27"),
    ("10-K", "2025-09-27"), ("10-Q", "2025-06-28"),
])


def _ev(data, ticker):
    event = svc.filing_deadline_event(data, ticker)
    assert event is not None
    return event


def test_filing_deadline_10k_after_third_quarter_52_53_weeks():
    event = _ev(APPLE, "aapl")
    # Q3 FY26 (27-jun) -> el ejercicio anterior: 28-jun-25 seguido de 27-sep-25 (+364 d = 26-sep-26).
    # Es el 10-K (fin de ejercicio 0926), 60 dias -> miercoles 25-nov (plazo real de Apple 2026).
    assert event["type"] == "filing_deadline" and event["ticker"] == "AAPL"
    assert event["date"] == "2026-11-25"
    assert event["title"] == "Plazo para presentar el 10-K"
    assert "60 días" in event["detail"] and "emisor acelerado grande" in event["detail"]
    assert "52/53 semanas" in event["detail"]
    assert event["source"] == svc.SOURCE_SEC_RULE


def test_filing_deadline_52_53_week_issuers_get_the_right_form():
    # Casos que el calendario +3 meses etiquetaba mal (10-K mostrado como 10-Q).
    # Cierres representativos de ejercicios 52/53 semanas: AAPL 2023 y ADBE 2023.
    aapl_2023 = _subs([("10-Q", "2023-07-01"), ("10-Q", "2023-04-01"), ("10-Q", "2022-12-31"),
                       ("10-K", "2022-09-24"), ("10-Q", "2022-07-02")])
    assert _ev(aapl_2023, "AAPL")["title"].startswith("Plazo para presentar el 10-K")
    adbe = _subs([("10-Q", "2023-09-01"), ("10-Q", "2023-06-02"), ("10-Q", "2023-03-03"),
                  ("10-K", "2022-12-02"), ("10-Q", "2022-09-02")], fye="1201")
    assert _ev(adbe, "ADBE")["title"].startswith("Plazo para presentar el 10-K")
    assert _ev(adbe, "ADBE")["date"] == "2024-01-30"  # 1-dic-23 + 60 d


def test_filing_deadline_quarters_of_unequal_length_use_prior_year_not_13_weeks():
    # Trimestres 16/12/12/12 semanas (tipo CAVA): tras el Q2 (12-jul-26) el Q3 cierra el
    # 4-oct (84 dias), no el 11-oct (91 dias): +91 daba un plazo 7 dias tarde.
    cava = _subs([("10-Q", "2026-07-12"), ("10-Q", "2026-04-19"), ("10-K", "2025-12-28"),
                  ("10-Q", "2025-10-05"), ("10-Q", "2025-07-13"), ("10-Q", "2025-04-20")], fye="1228")
    event = _ev(cava, "CAVA")
    assert event["title"] == "Plazo para presentar el 10-Q"
    assert event["date"] == "2026-11-13"  # 4-oct-26 + 40 d (large accelerated)


def test_filing_deadline_month_end_issuer_and_category_variants():
    q = _subs([("10-Q", "2025-09-30"), ("10-Q", "2025-06-30"), ("10-Q", "2025-03-31"), ("10-K", "2024-12-31")],
              fye="1231")
    assert _ev(q, "X")["title"].startswith("Plazo para presentar el 10-K")  # 31-dic-25 es fin de ejercicio
    assert _ev(q, "X")["date"] == "2026-03-02"  # 31-dic + 60 d = sab 28-feb -> lunes 2-mar
    accel = {**q, "category": "Accelerated filer"}
    assert _ev(accel, "X")["date"] == "2026-03-16"  # 75 d = 16-mar
    small = {**q, "category": "Non-accelerated filer"}
    assert _ev(small, "X")["date"] == "2026-03-31"  # 90 d
    mid = _subs([("10-Q", "2025-06-30"), ("10-Q", "2025-03-31"), ("10-K", "2024-12-31")], fye="1231")
    assert _ev(mid, "X")["title"].startswith("Plazo para presentar el 10-Q")
    assert _ev(mid, "X")["date"] == "2025-11-10"  # 30-sep + 40 d = 9-nov (dom) -> lunes 10


def test_filing_deadline_unknown_category_uses_max_and_says_so():
    event = _ev({**APPLE, "category": ""}, "AAPL")
    assert event["date"] == "2026-12-25"  # 26-sep + 90 d (viernes; la Navidad no se modela)
    assert "plazo máximo" in event["detail"]


def test_filing_deadline_no_data_means_none_not_invented():
    assert svc.filing_deadline_event({}, "X") is None
    assert svc.filing_deadline_event({**APPLE, "fiscalYearEnd": None}, "X") is None
    only_form4 = _subs([("4", "2026-10-06")])
    assert svc.filing_deadline_event(only_form4, "X") is None
    foreign = _subs([("20-F", "2026-06-30")])
    assert svc.filing_deadline_event(foreign, "X") is None
    # 52/53 semanas sin el informe del ejercicio anterior: no se adivina la longitud del trimestre.
    young = _subs([("10-Q", "2026-06-27"), ("10-Q", "2026-03-28")])
    assert svc.filing_deadline_event(young, "X") is None


def test_add_months_end_of_month():
    assert svc._add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert svc._add_months(date(2026, 12, 31), 3) == date(2027, 3, 31)
    assert svc._add_months(date(2026, 6, 27), 3) == date(2026, 9, 27)


def test_fetch_filing_deadlines_filters_range_and_reports_failures():
    async def cik(ticker):
        return None if ticker == "NOCIK" else "0000000001"

    async def subs(cik_):
        return APPLE

    out = asyncio.run(svc.fetch_filing_deadlines(
        {"AAPL", "NOCIK"}, date(2026, 11, 1), date(2026, 11, 30),
        cik_fetcher=cik, submissions_fetcher=subs,
    ))
    assert [e["ticker"] for e in out["events"]] == ["AAPL"]
    assert out["status"] == "partial"
    assert out["errors"] == ["Plazos 10-Q/10-K: EDGAR no disponible para NOCIK"]
    outside = asyncio.run(svc.fetch_filing_deadlines(
        {"AAPL"}, date(2026, 10, 14), date(2026, 10, 28), cik_fetcher=cik, submissions_fetcher=subs,
    ))
    assert outside == {"status": "ok", "events": [], "errors": []}


def test_fetch_filing_deadlines_exceptions_degrade_to_unavailable():
    async def boom(_):
        raise RuntimeError("secret-url-or-key")

    out = asyncio.run(svc.fetch_filing_deadlines(
        {"AAPL"}, D0, D1, cik_fetcher=boom, submissions_fetcher=boom,
    ))
    assert out["status"] == "unavailable" and out["events"] == []
    assert "secret" not in str(out)


def test_route_includes_filing_deadlines_sorted_and_status(engine, db, monkeypatch):
    _company(db, "AAPL", 5)

    async def cik(_ticker):
        return "0000320193"

    async def subs(_cik):
        return APPLE

    monkeypatch.setattr(svc, "_default_sec_fetchers", lambda: (cik, subs))
    client, main = _route_client(engine, monkeypatch, earnings_rows=[], dividend_rows=[])
    try:
        res = client.get("/api/calendar/catalysts?desde=2026-11-20&hasta=2026-11-30")
    finally:
        main.app.dependency_overrides.clear()
    body = res.json()
    assert res.status_code == 200 and body["status"] == "ok"
    assert [(e["date"], e["type"]) for e in body["events"]] == [("2026-11-25", "filing_deadline")]


def test_calendar_corporate_action_source_uses_current_visible_brand():
    assert svc.SOURCE_GERARAI == 'Acción corporativa registrada en GerarAI'


def test_watchlist_us_tickers_excludes_held_and_non_us(db):
    from app.models.entities import WatchItem

    held = _company(db, "HELDX", 5)
    watch_us = _company(db, "WUS", 0)
    _company(db, "WEU", 0, exchange="BME", currency="EUR")
    for sym in ("HELDX", "WUS", "WEU"):
        db.add(WatchItem(symbol=sym))
    db.commit()
    result = svc.watchlist_us_tickers(db, {"HELDX"})
    assert result == {"WUS"}
    assert held.ticker == "HELDX" and watch_us.ticker == "WUS"


def test_build_catalysts_tags_watchlist_origin_on_earnings():
    events = svc.build_catalysts(
        held={"KO"},
        held_us={"KO"},
        desde=D0,
        hasta=D1,
        earnings=[
            connector.normalize_earnings_row(
                {"symbol": "KO", "time": "time-pre-market", "epsForecast": "$0.60"},
                date(2026, 10, 22),
            ),
            connector.normalize_earnings_row(
                {"symbol": "WUS", "time": "time-after-hours", "epsForecast": "$1.00"},
                date(2026, 10, 22),
            ),
            connector.normalize_earnings_row(
                {"symbol": "FUERA", "time": "time-pre-market", "epsForecast": "$1.00"},
                date(2026, 10, 22),
            ),
        ],
        dividends=[],
        actions=[],
        watchlist_us={"WUS"},
    )
    by_ticker = {e["ticker"]: e for e in events}
    assert set(by_ticker) == {"KO", "WUS"}
    assert by_ticker["KO"]["origin"] == "cartera"
    assert by_ticker["WUS"]["origin"] == "watchlist"



def test_nasdaq_dividends_extend_to_watchlist_with_origin():
    events = svc.build_catalysts(
        held={"KO"}, held_us={"KO"}, desde=D0, hasta=D1,
        earnings=[],
        dividends=[
            connector.normalize_dividend_row(
                {"symbol": "WUS", "dividend_Ex_Date": "10/20/2026",
                 "payment_Date": "11/05/2026", "dividend_Rate": 0.25},
                date(2026, 10, 20),
            ),
            connector.normalize_dividend_row(
                {"symbol": "FUERA", "dividend_Ex_Date": "10/20/2026",
                 "dividend_Rate": 0.25},
                date(2026, 10, 20),
            ),
        ],
        actions=[],
        watchlist_us={"WUS"},
    )
    assert len(events) == 1
    event = events[0]
    assert event["ticker"] == "WUS" and event["type"] == "dividend_ex"
    assert event["origin"] == "watchlist"
    assert event["detail"] == "0,2500 por acción · pago el 5/11/2026"


def test_dividend_records_add_payments_any_market_and_non_us_ex(db):
    from app.models import DividendRecord

    us = _company(db, "KO", 5)  # US: su ex ya lo cubre NASDAQ en vivo
    eu = _company(db, "SAN", 5, exchange="BME", currency="EUR")
    watch = _company(db, "IBE", 0, exchange="BME", currency="EUR")
    from app.models import WatchItem
    db.add(WatchItem(symbol="IBE"))
    for company, ex, pay, source in (
        (us, date(2026, 10, 15), date(2026, 11, 2), "fmp"),
        (eu, date(2026, 10, 30), date(2026, 11, 3), "yahoo_finance"),
        (watch, date(2026, 11, 2), None, "yahoo_finance"),
    ):
        db.add(DividendRecord(company_id=company.id, ex_date=ex, pay_date=pay,
                              amount=Decimal("0.5"), currency="EUR", source=source))
    db.commit()
    held, held_us = svc.held_tickers(db)
    watch_us = svc.watchlist_us_tickers(db, held_us)
    watch_all = svc.watchlist_tickers(db, held)
    records = svc.upcoming_dividend_records(db, held | watch_all, D0, D1 + timedelta(days=10))
    events = svc.build_catalysts(
        held=held, held_us=held_us, desde=D0, hasta=D1 + timedelta(days=10),
        earnings=[], dividends=[], actions=[],
        watchlist_us=watch_us, watchlist=watch_all, records=records,
    )
    got = {(e["date"], e["ticker"], e["type"]): e for e in events}
    # Pago de KO (US) desde el registro ingerido, con etiqueta FMP
    pago_ko = got[("2026-11-02", "KO", "dividend_payment")]
    assert pago_ko["source"] == svc.record_source_label("fmp")
    assert pago_ko["origin"] == "cartera"
    assert "EUR" in pago_ko["detail"]
    # SAN (no-US): ex y pago desde el historial ingerido
    assert ("2026-10-30", "SAN", "dividend_ex") in got
    assert ("2026-11-03", "SAN", "dividend_payment") in got
    assert got[("2026-10-30", "SAN", "dividend_ex")]["source"] == svc.record_source_label("yahoo_finance")
    # IBE (watchlist, no-US): ex con origen watchlist; sin pay_date NO hay pago (nada inventado)
    ex_ibe = got[("2026-11-02", "IBE", "dividend_ex")]
    assert ex_ibe["origin"] == "watchlist"
    assert not any(e["type"] == "dividend_payment" and e["ticker"] == "IBE" for e in events)
    # KO (US) NO genera ex desde el registro: lo cubre NASDAQ en vivo
    assert not any(e["type"] == "dividend_ex" and e["ticker"] == "KO" for e in events)


def test_dividend_records_respect_range_and_followed(db):
    from app.models import DividendRecord

    c = _company(db, "SAN", 5, exchange="BME", currency="EUR")
    db.add(DividendRecord(company_id=c.id, ex_date=date(2026, 12, 25),
                          pay_date=date(2027, 1, 10), amount=Decimal("0.5"),
                          currency="EUR", source="fmp"))
    db.commit()
    assert svc.upcoming_dividend_records(db, {"SAN"}, D0, D1) == []
    assert svc.upcoming_dividend_records(db, set(), D0, D1) == []
    rows = svc.upcoming_dividend_records(db, {"SAN"}, date(2026, 12, 1), date(2027, 1, 31))
    assert len(rows) == 1 and rows[0]["pay_date"] == "2027-01-10"


def test_record_source_label_fallback():
    assert svc.record_source_label("fmp") == "Historial de dividendos ingerido de FMP"
    assert svc.record_source_label("otro") == "Historial de dividendos ingerido (otro)"
