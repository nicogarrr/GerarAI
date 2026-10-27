"""Diario de decisiones enlazado a operaciones reales (IBKR).

Una entrada del diario puede apuntar a la operacion (Transaction) que la
ejecuto: transaction_id opcional. Al listarla se ve la operacion y el valor
justo que habia ESE dia (point-in-time: solo tesis/valoraciones creadas hasta
la fecha de la operacion), con el margen frente al precio de ejecucion.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Company,
    DecisionJournalEntry,
    ThesisVersion,
    Transaction,
    ValuationModel,
    ValuationOutput,
)
from app.services.fundamental_review_service import DecisionJournalService
from app.services.journal_trade_link import fair_value_on, journal_entry_payload, journal_trades


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "UBER") -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NYSE",
        currency="USD",
        sector="Tech",
        industry="Tech",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _trade(
    db: Session,
    company: Company,
    *,
    day: date,
    action: str = "buy",
    price: str = "70",
    qty: str = "10",
    currency: str = "USD",
) -> Transaction:
    tx = Transaction(
        company_id=company.id,
        trade_date=day,
        action=action,
        quantity=Decimal(qty),
        price=Decimal(price),
        fees=Decimal("1"),
        currency=currency,
        external_id=f"ibkr-{company.ticker}-{day}-{action}-{price}",
    )
    db.add(tx)
    db.commit()
    return tx


def _thesis(
    db: Session,
    company: Company,
    *,
    version: int,
    created: datetime,
    expected: str,
    status: str = "published",
) -> None:
    db.add(
        ThesisVersion(
            company_id=company.id,
            version=version,
            status=status,
            thesis_markdown="# T",
            executive_summary="R",
            rating="watch",
            expected_value=Decimal(expected),
            created_at=created,
            updated_at=created,
        )
    )
    db.commit()


def _engine(
    db: Session, company: Company, *, version: int, created: datetime, expected: float, status: str = "final"
) -> None:
    model = ValuationModel(
        company_id=company.id,
        model_type="standard_dcf",
        version=version,
        status=status,
        calculation_trace={},
        created_at=created,
        updated_at=created,
    )
    db.add(model)
    db.flush()
    db.add(
        ValuationOutput(
            valuation_model_id=model.id,
            scenario="base",
            value_per_share=Decimal("1"),
            output_payload={"expected_value": expected},
        )
    )
    db.commit()


def test_create_with_trade_takes_date_and_execution_price(db):
    company = _company(db)
    tx = _trade(db, company, day=date(2026, 3, 12), price="70.50")
    entry = DecisionJournalService().create(
        db,
        company,
        decision="buy",
        rationale="Cae a 3X DCA con tesis intacta",
        what_must_be_true=[],
        transaction_id=tx.id,
    )
    assert entry.transaction_id == tx.id
    assert entry.decision_date == date(2026, 3, 12)
    assert entry.price == Decimal("70.50")


def test_create_rejects_trade_of_another_company(db):
    uber, pool = _company(db, "UBER"), _company(db, "POOL")
    tx = _trade(db, pool, day=date(2026, 3, 12))
    with pytest.raises(ValueError, match="no es de UBER"):
        DecisionJournalService().create(
            db, uber, decision="buy", rationale="xxxxx", what_must_be_true=[], transaction_id=tx.id
        )


def test_create_rejects_non_trade_rows(db):
    company = _company(db)
    tx = _trade(db, company, day=date(2026, 3, 12), action="dividend")
    with pytest.raises(ValueError, match="compra o venta"):
        DecisionJournalService().create(
            db, company, decision="buy", rationale="xxxxx", what_must_be_true=[], transaction_id=tx.id
        )


def test_without_trade_nothing_changes(db):
    company = _company(db)
    entry = DecisionJournalService().create(
        db, company, decision="watch", rationale="Vigilar", what_must_be_true=[]
    )
    assert entry.transaction_id is None
    payload = journal_entry_payload(db, entry)
    assert payload["transaction"] is None
    assert payload["fair_value_on_day"] is None


def test_fair_value_is_point_in_time_and_prefers_recent_published_thesis(db):
    company = _company(db)
    _thesis(db, company, version=1, created=datetime(2026, 1, 10, tzinfo=UTC), expected="90")
    _engine(db, company, version=1, created=datetime(2026, 2, 1, tzinfo=UTC), expected=80.0)
    # Posterior a la operacion: no puede verse ese dia.
    _thesis(db, company, version=2, created=datetime(2026, 4, 1, tzinfo=UTC), expected="200")
    reading = fair_value_on(db, company, date(2026, 3, 12), price=Decimal("72"), currency="USD")
    assert reading is not None
    assert reading["value"] == 90.0
    assert reading["source"] == "tesis"
    assert reading["version"] == 1
    # 90 / 72 - 1 = +25 %
    assert reading["margin_vs_trade_price"] == pytest.approx(0.25)


def test_old_thesis_loses_to_publishable_engine(db):
    company = _company(db)
    _thesis(db, company, version=1, created=datetime(2025, 1, 10, tzinfo=UTC), expected="90")
    _engine(db, company, version=3, created=datetime(2026, 3, 1, tzinfo=UTC), expected=80.0)
    reading = fair_value_on(db, company, date(2026, 3, 12), price=Decimal("64"), currency="USD")
    assert reading is not None
    assert reading["source"] == "motor"
    assert reading["margin_vs_trade_price"] == pytest.approx(0.25)


def test_currency_mismatch_shows_value_without_margin(db):
    company = _company(db)
    _engine(db, company, version=1, created=datetime(2026, 3, 1, tzinfo=UTC), expected=80.0)
    reading = fair_value_on(db, company, date(2026, 3, 12), price=Decimal("60"), currency="EUR")
    assert reading is not None
    assert reading["margin_vs_trade_price"] is None
    assert "divisa" in reading["note"]


def test_no_valuation_before_the_trade_is_none(db):
    company = _company(db)
    _engine(db, company, version=1, created=datetime(2026, 5, 1, tzinfo=UTC), expected=80.0)
    assert fair_value_on(db, company, date(2026, 3, 12), price=Decimal("60"), currency="USD") is None


def test_payload_and_trade_list(db):
    company = _company(db)
    _thesis(db, company, version=1, created=datetime(2026, 1, 10, tzinfo=UTC), expected="90")
    buy = _trade(db, company, day=date(2026, 3, 12), price="72")
    _trade(db, company, day=date(2026, 3, 20), action="dividend", price="0.5")
    sell = _trade(db, company, day=date(2026, 6, 1), action="sell", price="95")
    entry = DecisionJournalService().create(
        db, company, decision="buy", rationale="Entrada 3X", what_must_be_true=[], transaction_id=buy.id
    )
    payload = journal_entry_payload(db, entry)
    assert payload["transaction"]["action"] == "buy"
    assert payload["transaction"]["trade_date"] == "2026-03-12"
    assert payload["fair_value_on_day"]["value"] == 90.0

    trades = journal_trades(db, company)
    assert [t["id"] for t in trades] == [sell.id, buy.id]  # sin dividendos, mas reciente primero
    assert trades[1]["linked_entry_ids"] == [entry.id]
    assert trades[0]["linked_entry_ids"] == []


def test_link_and_unlink_existing_entry(db):
    company = _company(db)
    tx = _trade(db, company, day=date(2026, 3, 12))
    service = DecisionJournalService()
    entry = service.create(db, company, decision="buy", rationale="Antes de comprar", what_must_be_true=[])
    original_date = entry.decision_date
    service.link_transaction(db, company, entry.id, tx.id)
    db.refresh(entry)
    assert entry.transaction_id == tx.id
    assert entry.decision_date == original_date  # enlazar no reescribe la fecha de la decision
    service.link_transaction(db, company, entry.id, None)
    db.refresh(entry)
    assert entry.transaction_id is None
    with pytest.raises(LookupError):
        service.link_transaction(db, company, 9999, tx.id)


def test_deleting_the_trade_keeps_the_entry(db):
    company = _company(db)
    tx = _trade(db, company, day=date(2026, 3, 12))
    entry = DecisionJournalService().create(
        db, company, decision="buy", rationale="xxxxx", what_must_be_true=[], transaction_id=tx.id
    )
    column = DecisionJournalEntry.__table__.c.transaction_id
    fk = next(iter(column.foreign_keys))
    assert fk.ondelete == "SET NULL"
    assert entry.id is not None


def test_routes_validate_and_link(db):
    from fastapi import HTTPException

    from app.api.routes.companies import (
        DecisionJournalCreate,
        DecisionJournalTradeLink,
        create_decision_journal_entry,
        decision_journal,
        decision_journal_trades,
        link_decision_journal_trade,
    )

    uber, pool = _company(db, "UBER"), _company(db, "POOL")
    mine = _trade(db, uber, day=date(2026, 3, 12))
    other = _trade(db, pool, day=date(2026, 3, 12))
    created = create_decision_journal_entry(
        "UBER", DecisionJournalCreate(decision="buy", rationale="Entrada 3X", transaction_id=mine.id), db
    )
    assert created["transaction"]["id"] == mine.id
    with pytest.raises(HTTPException) as exc:
        create_decision_journal_entry(
            "UBER", DecisionJournalCreate(decision="buy", rationale="xxxxx", transaction_id=other.id), db
        )
    assert exc.value.status_code == 422
    assert [row["id"] for row in decision_journal_trades("UBER", db)] == [mine.id]
    unlinked = link_decision_journal_trade(
        "UBER", created["id"], DecisionJournalTradeLink(transaction_id=None), db
    )
    assert unlinked["transaction"] is None
    assert decision_journal("UBER", db)[0]["transaction_id"] is None
