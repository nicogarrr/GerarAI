"""Regla «per-antiguedad-v1»: el PER de la watchlist no se calcula con un ejercicio cerrado hace más de 18 meses.

ERF.PA (Eurofins) en nov-2026: la base solo tiene el ESEF de FY2024 y la watchlist enseñaba un PER 42,4 sobre ese
ejercicio como si fuera el actual. ASTS citaba FY2021. Con «hoy» fijo (los tests no dependen del reloj).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.api.routes import watchlist as wl
from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact, MarketPrice

TODAY = date(2026, 11, 11)


def _seed(eps: float, *, end: date, fy: int, price_day: date) -> str:
    init_db()
    ticker = f"ST{uuid4().hex[:6].upper()}"
    db = SessionLocal()
    company = Company(ticker=ticker, name=ticker, exchange="EPA", currency="EUR",
                      company_type="operating", valuation_model="unassigned")
    db.add(company)
    db.commit()
    db.add(MarketPrice(company_id=company.id, date=price_day, open=50, high=50, low=50, close=Decimal("50"),
                       volume=1000, quote_currency="EUR", source="test"))
    db.add(FinancialFact(company_id=company.id, metric="eps_diluted", value=Decimal(str(eps)), unit="EUR/share",
                         period=f"{end.isoformat()}:FY", fiscal_year=fy, fiscal_quarter="FY",
                         source_type="ESEF", is_reported=True))
    db.commit()
    db.close()
    return ticker


def _metrics(ticker: str) -> dict:
    db = SessionLocal()
    try:
        return wl.watchlist_metrics(ticker, db)
    finally:
        db.close()


def test_ejercicio_de_hace_mas_de_18_meses_da_per_nd_con_motivo(monkeypatch):
    monkeypatch.setattr(wl, "_today", lambda: TODAY)
    ticker = _seed(1.18, end=date(2024, 12, 31), fy=2024, price_day=date(2026, 11, 10))

    payload = _metrics(ticker)

    assert payload["per"] is None
    reason = next(s for s in payload["sources"] if s.startswith("PER: N/D"))
    assert "FY2024" in reason and "2024-12-31" in reason and "más de 18" in reason, reason


def test_ejercicio_dentro_de_18_meses_mantiene_el_per(monkeypatch):
    # 2024-12-31 → 2026-06-21: 537 días (< 548): todavía es el último ejercicio razonable.
    monkeypatch.setattr(wl, "_today", lambda: date(2026, 6, 21))
    ticker = _seed(1.25, end=date(2024, 12, 31), fy=2024, price_day=date(2026, 6, 19))

    payload = _metrics(ticker)

    assert payload["per"] == pytest.approx(50 / 1.25)
    assert any("FY2024" in s for s in payload["sources"])


def test_perdidas_viejas_citan_la_antiguedad_y_no_el_signo(monkeypatch):
    # ASTS: el último BPA anual de la base es FY2021 (−0,37); «sin beneficio» sobre 2021 no describe hoy.
    monkeypatch.setattr(wl, "_today", lambda: TODAY)
    ticker = _seed(-0.37, end=date(2021, 12, 31), fy=2021, price_day=date(2026, 11, 10))

    payload = _metrics(ticker)

    assert payload["per"] is None
    reasons = [s for s in payload["sources"] if s.startswith("PER: N/D")]
    assert len(reasons) == 1 and "FY2021" in reasons[0] and "más de 18" in reasons[0]
    assert "sin beneficio" not in reasons[0]


def test_stale_reason_frontera_exacta():
    # «per-antiguedad-v2»: 18 meses de calendario completos (2024-12-31 → 2026-06-30, último día de junio).
    row = FinancialFact(metric="eps_diluted", period="2024-12-31:FY", fiscal_year=2024)
    assert wl._stale_annual_reason(row, date(2026, 6, 30)) is None
    assert wl._stale_annual_reason(row, date(2026, 7, 1)) is not None
    assert wl._stale_annual_reason(FinancialFact(metric="eps_diluted", period="FY2024"), TODAY) is None
