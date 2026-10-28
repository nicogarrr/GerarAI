"""Versionado de informes fiscales guardados (aviso «Regenerar» verificable).

No se prueba ninguna fórmula fiscal: solo que un informe guardado con un
criterio de cálculo anterior (o sin criterio registrado) se declara
desactualizado, que regenerar lo deja al día y que un informe calculado al vuelo
nunca se marca como viejo. Además fija, de extremo a extremo, que un pago scrip
queda fuera de la casilla 0029 y listado para revisión manual (no calculado).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, TaxReport, Transaction
from app.services.tax_report_service import TaxReportService
from app.services.tax_report_versioning import (
    REASON_MISSING_MARKER,
    REASON_OUTDATED_MARKER,
    SECURITIES_FX_CRITERION,
    report_versioning,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _buy(db: Session, company: Company) -> None:
    db.add(Transaction(
        company_id=company.id, trade_date=date(2025, 3, 10), action="buy",
        quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("0"), currency="EUR",
    ))
    db.commit()


def test_current_criterion_is_not_stale():
    result = report_versioning({"securities_fx_criterion": SECURITIES_FX_CRITERION}, persisted=True)
    assert result == {"persisted": True, "stale": False, "regenerate_recommended": False, "outdated": []}


def test_report_without_marker_is_stale_not_current():
    for summary in (None, {}, {"securities_fx_criterion": None}, {"securities_fx_criterion": ""}):
        result = report_versioning(summary, persisted=True)
        assert result["stale"] is True
        assert result["regenerate_recommended"] is True
        assert result["outdated"] == [{
            "marker": "securities_fx_criterion", "stored": (summary or {}).get("securities_fx_criterion"),
            "current": SECURITIES_FX_CRITERION, "reason": REASON_MISSING_MARKER,
        }]


def test_report_with_old_criterion_is_stale_and_names_both_values():
    result = report_versioning({"securities_fx_criterion": "dos_tramos_v0"}, persisted=True)
    assert result["stale"] is True
    assert result["outdated"][0]["stored"] == "dos_tramos_v0"
    assert result["outdated"][0]["current"] == SECURITIES_FX_CRITERION
    assert result["outdated"][0]["reason"] == REASON_OUTDATED_MARKER


def test_on_the_fly_report_is_never_stale():
    result = report_versioning({}, persisted=False)
    assert result == {"persisted": False, "stale": False, "regenerate_recommended": False, "outdated": []}


def test_get_report_flags_legacy_persisted_report_and_regenerate_clears_it(db):
    company = _company(db, "AAPL")
    _buy(db, company)
    service = TaxReportService()

    fresh = service.regenerate_report(db, 2025)
    assert fresh["versioning"]["stale"] is False
    assert service.get_report(db, 2025)["versioning"]["stale"] is False

    # Informe guardado antes de registrarse el criterio: se reescribe a mano.
    stored = db.scalar(select(TaxReport).where(TaxReport.fiscal_year == 2025))
    legacy_summary = dict(stored.summary)
    legacy_summary.pop("securities_fx_criterion")
    stored.summary = legacy_summary
    db.commit()

    legacy = service.get_report(db, 2025)
    assert legacy["persisted"] is True
    assert legacy["versioning"]["stale"] is True
    assert legacy["versioning"]["outdated"][0]["reason"] == REASON_MISSING_MARKER
    # Leer no reescribe: sigue guardado sin marcador hasta que se regenere.
    assert "securities_fx_criterion" not in db.scalar(select(TaxReport)).summary

    again = service.regenerate_report(db, 2025)
    assert again["versioning"]["stale"] is False
    assert service.get_report(db, 2025)["versioning"]["stale"] is False


def test_get_report_without_persisted_report_is_not_stale(db):
    company = _company(db, "AAPL")
    _buy(db, company)
    data = TaxReportService().get_report(db, 2025)
    assert data["persisted"] is False
    assert data["versioning"]["stale"] is False


def test_scrip_stays_out_of_0029_and_is_listed_for_manual_review_end_to_end(db):
    db.add(Portfolio(name="P", base_currency="EUR"))
    db.commit()
    company = _company(db, "SAN")
    pay = date(2025, 5, 15)
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=pay, rate=Decimal("0.90"), source="test"))
    db.add(Transaction(company_id=company.id, trade_date=pay, action="dividend", quantity=Decimal("0"),
                       price=Decimal("100"), fees=Decimal("0"), currency="USD"))
    db.add(Transaction(company_id=company.id, trade_date=pay, action="dividend", quantity=Decimal("0"),
                       price=Decimal("200"), fees=Decimal("0"), currency="USD",
                       raw_payload={"type": "Scrip Dividend"}))
    db.commit()

    service = TaxReportService()
    service.regenerate_report(db, 2025)
    report = service.get_report(db, 2025)
    dividendos = report["filing"]["casillas"]["dividendos"]
    assert dividendos["0029_ingresos_integros"] == pytest.approx(90.0)
    assert dividendos["special_payment_tickers"] == ["SAN"]


def test_casillas_of_unverified_year_are_unavailable_not_estimated(db):
    """Fail-closed: un ejercicio sin mapeo de casillas verificado no muestra números."""
    db.add(Portfolio(name="P", base_currency="EUR"))
    db.commit()
    service = TaxReportService()
    service.regenerate_report(db, 2019)
    casillas = service.get_report(db, 2019)["filing"]["casillas"]
    assert casillas["available"] is False
    assert "dividendos" not in casillas
