"""Eventos guardados para el gráfico de precio de la ficha («Precio y eventos»).

Solo lee tablas propias: cada evento sale con fecha y fuente, y la ruta no
llama a ningún proveedor (sin red en el test: un fetch fallaría).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.models.entities import (
    Base,
    Company,
    DividendRecord,
    EarningsDate,
    InsiderFiling,
    InsiderTransaction,
    NewsEvent,
    Portfolio,
    Position,
    Transaction,
)
from app.services.company_events_service import stored_holding, stored_timeline_events
from tests.auth_helpers import auth_settings, signed_request

SECRET = "company-timeline-events-test-sec"


def _company(db: Session, ticker: str) -> Company:
    company = Company(ticker=ticker, name="Timeline Co", exchange="NASDAQ", currency="USD", sector="T",
                      industry="T", company_type="stock", valuation_model="dcf", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.flush()
    return company


def _seed(db: Session, ticker: str) -> Company:
    company = _company(db, ticker)
    db.add(EarningsDate(ticker=ticker, event_date=date(2026, 7, 30), fiscal_label="T2 2026", confirmed=True,
                        source="nasdaq", source_label="NASDAQ", source_url="https://www.nasdaq.com/x"))
    db.add(DividendRecord(company_id=company.id, ex_date=date(2026, 8, 10), amount=Decimal("0.25"),
                          currency="USD", source="fmp"))
    db.add(NewsEvent(company_id=company.id, date=datetime(2026, 9, 1, 14, tzinfo=UTC), title="8-K: nuevo CFO",
                     source="SEC EDGAR", url="https://www.sec.gov/a", event_type="new_filing",
                     sec_filing_identity=f"0000-{uuid4().hex[:6]}"))
    db.add(NewsEvent(company_id=company.id, date=datetime(2026, 9, 5, 9, tzinfo=UTC), title="Gran contrato",
                     source="Reuters", url="https://reuters.com/b", event_type="general_news", materiality_score=7))
    db.add(NewsEvent(company_id=company.id, date=datetime(2026, 9, 6, 9, tzinfo=UTC), title="Ruido",
                     source="Blog", url=None, event_type="general_news", materiality_score=2))
    filing = InsiderFiling(accession_number=f"acc-{uuid4().hex[:8]}", form="4", issuer_cik="1", issuer_ticker=ticker,
                           parser_version="1")
    db.add(filing)
    db.flush()
    for i, (code, value) in enumerate((("P", 250_000.0), ("S", 5_000.0), ("A", 900_000.0))):
        db.add(InsiderTransaction(fingerprint=f"fp-{uuid4().hex[:8]}-{i}", filing_id=filing.id,
                                  accession_number=filing.accession_number, form="4", issuer_ticker=ticker,
                                  insider="Ana CEO", code=code, value=value, tx_date="2026-09-10",
                                  source_url="https://www.sec.gov/c"))
    db.add(EarningsDate(ticker=ticker, event_date=date(2025, 1, 30), source="nasdaq", source_label="NASDAQ"))
    return company


def _memory_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = None
    return db


def test_stored_events_have_date_source_and_respect_range_and_thresholds():
    with _memory_db() as db:
        company = _seed(db, "TLN")
        db.commit()
        events = stored_timeline_events(db, company, date(2026, 6, 1), date(2026, 10, 31))
    kinds = [e["kind"] for e in events]
    assert kinds == ["insider", "news", "filing", "ex_dividend", "results"]  # más recientes primero
    assert all(e["date"] and e["source"] for e in events)
    insider = events[0]
    assert insider["title"] == "Ana CEO compra acciones" and "250.000" in insider["detail"]
    assert events[1]["title"] == "Gran contrato"  # la noticia de materialidad 2 no entra
    assert events[3]["detail"] == "0.25 USD por acción"
    assert events[4]["title"] == "Resultados T2 2026" and events[4]["source_url"] == "https://www.nasdaq.com/x"


def test_holding_average_cost_and_first_buy():
    with _memory_db() as db:
        company = _company(db, "HLD")
        assert stored_holding(db, company) is None
        db.add(Portfolio(name="Main", base_currency="USD", is_default=True))
        db.flush()
        for qty, cost in (("10", "100"), ("30", "120")):
            db.add(Position(company_id=company.id, quantity=Decimal(qty), average_cost=Decimal(cost), currency="USD",
                            base_currency="USD", source="probe"))
        db.add(Transaction(portfolio_id=1, company_id=company.id, trade_date=date(2024, 3, 4), action="BUY",
                           quantity=Decimal("10"), price=Decimal("100")))
        db.commit()
        holding = stored_holding(db, company)
    assert holding == {"average_cost": 115.0, "first_buy_date": "2024-03-04"}


def test_timeline_route_reads_only_stored_data(monkeypatch):
    monkeypatch.setattr(auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET))

    def _no_network(*_a, **_k):
        raise AssertionError("la ruta no debe llamar a proveedores")

    monkeypatch.setattr("app.services.company_events_service.FinnhubClient", _no_network)
    monkeypatch.setattr("app.services.company_events_service.SECClient", _no_network)
    init_db()
    tenant_ext = f"timeline-{uuid4().hex[:8]}"
    ticker = f"TL{uuid4().hex[:4].upper()}"
    db = SessionLocal()
    tenant = Tenant(external_id=tenant_ext, name="Timeline test")
    db.add(tenant)
    db.commit()
    db.info["tenant_id"] = tenant.id
    _seed(db, ticker)
    db.commit()
    db.close()
    client = TestClient(main.app)
    res = signed_request(client, SECRET, tenant_ext, "timeline-user", "GET", f"/api/companies/{ticker}/events/timeline",
                         params={"desde": "2026-06-01", "hasta": "2026-10-31"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ticker"] == ticker and body["desde"] == "2026-06-01"
    assert [e["kind"] for e in body["events"]] == ["insider", "news", "filing", "ex_dividend", "results"]
    assert body["holding"] is None
    bad = signed_request(client, SECRET, tenant_ext, "timeline-user", "GET", f"/api/companies/{ticker}/events/timeline",
                         params={"desde": "2026-10-31", "hasta": "2026-06-01"})
    assert bad.status_code == 400


def test_timeline_reads_fail_closed_without_tenant_when_auth_required(monkeypatch):
    """Segunda capa de tenant (app/core/tenancy.py): sin tenant y con auth obligatoria, no se lee nada."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.core.tenancy.get_settings",
        lambda: SimpleNamespace(research_auth_required=True, is_production=False),
    )
    with _memory_db() as db:
        company = _seed(db, "TFC")
        db.commit()
        for read in (
            lambda: stored_holding(db, company),
            lambda: stored_timeline_events(db, company, date(2026, 6, 1), date(2026, 10, 31)),
        ):
            try:
                read()
            except RuntimeError as exc:
                assert "Tenant context is required" in str(exc)
            else:
                raise AssertionError("debía fallar cerrado sin contexto de tenant")
