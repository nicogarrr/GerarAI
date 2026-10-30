"""A6: un split del Flex queda registrado como acción corporativa pendiente.

Antes solo se avisaba («regístrala en Acciones corporativas») y el usuario tenía
que teclear ratio y fecha a mano. Ahora la importación crea la fila pendiente;
aplicarla sigue siendo un paso explícito que conserva el coste total y deja la
posición en suspensión de valoración hasta tener un cierre post-split.

Valores a mano: 10 NVDA a 1000 USD = 10 000 USD de coste. Split 10 por 1 →
100 acciones, coste total 10 000, medio 100. Contrasplit 1 por 10 → ratio 0,1.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, CorporateAction, Position, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

TRADE = (
    '<Trade symbol="NVDA" isin="US67066G1040" listingExchange="NASDAQ" currency="USD" buySell="BUY" '
    'quantity="10" tradePrice="1000" tradeDate="20240301" tradeID="NV-1"/>'
)
SPLIT = (
    '<CorporateAction symbol="NVDA" isin="US67066G1040" type="FS" reportDate="20240610" '
    'quantity="90" description="NVDA(US67066G1040) SPLIT 10 FOR 1" transactionID="NV-FS-1"/>'
)
REVERSE = (
    '<CorporateAction symbol="NVDA" isin="US67066G1040" type="RS" dateTime="20240901;000000" '
    'quantity="-90" description="NVDA(US67066G1040) SPLIT 1 FOR 10" transactionID="NV-RS-1"/>'
)


def _flex(*rows):
    return "<FlexQueryResponse><FlexStatement>" + "".join(rows) + "</FlexStatement></FlexQueryResponse>"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="flex-split-pending", name="Fixture")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _actions(db):
    return db.query(CorporateAction).order_by(CorporateAction.id).all()


def test_flex_split_is_recorded_pending_and_ledger_untouched(db):
    result = IBKRImportService().import_flex_xml(db, _flex(TRADE, SPLIT))
    [action] = _actions(db)
    assert (action.action_type, action.ratio, action.effective_date) == ("split", Decimal("10"), date(2024, 6, 10))
    assert action.applied is False and action.source == "ibkr_flex"
    notices = [e for e in result["row_errors"] if "FS" in e and "NVDA" in e]
    assert len(notices) == 1 and "registrada como pendiente" in notices[0]
    [buy] = db.query(Transaction).all()
    assert (buy.action, Decimal(buy.quantity)) == ("buy", Decimal("10"))  # el libro no se toca al importar


def test_reimport_does_not_duplicate_the_split(db):
    IBKRImportService().import_flex_xml(db, _flex(TRADE, SPLIT))
    again = IBKRImportService().import_flex_xml(db, _flex(TRADE, SPLIT))
    assert len(_actions(db)) == 1
    assert any("ya estaba pendiente" in e for e in again["row_errors"])


def test_provider_split_a_day_apart_is_the_same_event(db):
    IBKRImportService().import_flex_xml(db, _flex(TRADE))
    company = db.query(Company).filter_by(ticker="NVDA").one()
    db.add(CorporateAction(company_id=company.id, action_type="split", effective_date=date(2024, 6, 11),
                           ratio=Decimal("10"), description="yahoo", applied=False, source="yahoo"))
    db.commit()
    IBKRImportService().import_flex_xml(db, _flex(TRADE, SPLIT))
    assert [a.source for a in _actions(db)] == ["yahoo"]


def test_reverse_split_ratio_is_shares_after_over_before(db):
    IBKRImportService().import_flex_xml(db, _flex(TRADE, REVERSE))
    [action] = _actions(db)
    assert (action.action_type, action.ratio, action.effective_date) == ("reverse_split", Decimal("0.1"), date(2024, 9, 1))


def test_unparseable_or_contradictory_rows_stay_a_notice_only(db):
    bad = SPLIT.replace("SPLIT 10 FOR 1", "SPLIT").replace("NV-FS-1", "NV-FS-2")
    wrong = SPLIT.replace("SPLIT 10 FOR 1", "SPLIT 1 FOR 10").replace("NV-FS-1", "NV-FS-3")
    result = IBKRImportService().import_flex_xml(db, _flex(TRADE, bad, wrong))
    assert _actions(db) == []
    assert any("no se aplica al libro" in e for e in result["row_errors"])


def test_dry_run_records_nothing(db):
    IBKRImportService().import_flex_xml(db, _flex(TRADE, SPLIT), dry_run=True)
    assert _actions(db) == []


def test_applying_the_flex_split_preserves_cost_basis_and_holds_valuation(db):
    from app.services.corporate_actions_service import CorporateActionService
    from app.services.portfolio_ledger_service import PortfolioLedgerService

    IBKRImportService().import_flex_xml(db, _flex(TRADE, SPLIT))
    company = db.query(Company).filter_by(ticker="NVDA").one()
    PortfolioLedgerService().rebuild_position(db, company.id)
    db.commit()
    before = db.query(Position).one()
    assert Decimal(before.quantity) * Decimal(before.average_cost) == Decimal("10000")
    [action] = _actions(db)
    CorporateActionService().apply_action(db, action.id)
    db.expire_all()
    position = db.query(Position).one()
    assert Decimal(position.quantity) == 100
    assert Decimal(position.average_cost) == Decimal("100")
    assert Decimal(position.quantity) * Decimal(position.average_cost) == Decimal("10000")  # coste total intacto
    assert position.valuation_hold_reason
