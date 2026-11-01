"""PUT /portfolio/transactions/{id} must not turn a buy/sell into cash.

``PortfolioTransactionInput`` is shared by the buy/sell and the cash verbs.
The handler validated that the STORED action was buy/sell but then wrote
``transaction.action = payload.action`` from a Literal that also allows
dividend/interest/fee/cash_misc. ``rebuild_position`` replays buy/sell only,
so the leg stopped counting, the position was deleted, and the request still
answered 200 - the buy the user was editing silently destroyed. There is no DB
CHECK constraint on ``Transaction.action``, so the guard is in the handler.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Portfolio, Position, Tenant, Transaction
from app.seed import seed
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-tx-update-secret-at-least-32-chars"


@pytest.fixture
def required_auth(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )


@pytest.fixture
def book(required_auth):
    """A signed tenant with one buy leg, torn down afterwards."""
    init_db()
    seed()
    suffix = uuid4().hex[:8]
    tenant = f"tx-update-{suffix}"
    ticker = f"U{suffix[:6]}".upper()
    client = TestClient(main.app)
    created = signed_request(
        client, SECRET, tenant, f"user-{suffix}", "POST",
        "/api/portfolio/transactions",
        json_body={
            "ticker": ticker,
            "action": "buy",
            "quantity": 4,
            "price": 25,
            "trade_date": "2026-01-02",
            "notes": "canonical buy leg",
        },
    )
    assert created.status_code == 201, created.text
    yield {
        "client": client,
        "tenant": tenant,
        "user": f"user-{suffix}",
        "ticker": ticker,
        "transaction_id": created.json()["id"],
    }
    db = SessionLocal()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is not None:
        db.execute(delete(Transaction).where(Transaction.company_id == company.id))
        db.execute(delete(Position).where(Position.company_id == company.id))
        db.execute(delete(Company).where(Company.id == company.id))
    tenant_row = db.scalar(select(Tenant).where(Tenant.external_id == tenant))
    if tenant_row is not None:
        db.execute(
            delete(Portfolio).where(Portfolio.tenant_id == tenant_row.id)
        )
        db.execute(delete(Tenant).where(Tenant.id == tenant_row.id))
    db.commit()
    db.close()


def _positions(payload: dict) -> list[dict]:
    response = signed_request(
        payload["client"], SECRET, payload["tenant"], payload["user"],
        "GET", "/api/portfolio/positions",
    )
    assert response.status_code == 200, response.text
    # /positions devuelve sobre paginado {"items": [...], "page_info": {...}}.
    return [row for row in response.json()["items"] if row["ticker"] == payload["ticker"]]


def test_update_with_cash_action_is_rejected_and_position_survives(book):
    response = signed_request(
        book["client"], SECRET, book["tenant"], book["user"], "PUT",
        f"/api/portfolio/transactions/{book['transaction_id']}",
        json_body={
            "ticker": book["ticker"],
            "action": "dividend",
            "quantity": 1,
            "price": 25,
            "trade_date": "2026-01-02",
        },
    )
    assert response.status_code == 400
    assert "cash transaction" in response.json()["detail"]

    # The leg is still a buy and the position it feeds is untouched.
    stored = signed_request(
        book["client"], SECRET, book["tenant"], book["user"],
        "GET", "/api/portfolio/transactions",
    )
    assert stored.status_code == 200
    # /transactions tambien devuelve sobre paginado {"items": [...]}.
    rows = [row for row in stored.json()["items"] if row["id"] == book["transaction_id"]]
    assert len(rows) == 1
    assert rows[0]["action"] == "buy"
    assert rows[0]["quantity"] == 4.0

    positions = _positions(book)
    assert len(positions) == 1
    assert positions[0]["quantity"] == 4.0
    assert positions[0]["market_value"] == 100.0


@pytest.mark.parametrize("action", ["dividend", "interest", "fee", "cash_misc"])
def test_every_cash_verb_is_rejected(book, action):
    response = signed_request(
        book["client"], SECRET, book["tenant"], book["user"], "PUT",
        f"/api/portfolio/transactions/{book['transaction_id']}",
        json_body={
            "ticker": book["ticker"],
            "action": action,
            "quantity": 0,
            "price": 25,
            "trade_date": "2026-01-02",
        },
    )
    assert response.status_code == 400
    assert len(_positions(book)) == 1


def test_buy_to_buy_update_still_works(book):
    response = signed_request(
        book["client"], SECRET, book["tenant"], book["user"], "PUT",
        f"/api/portfolio/transactions/{book['transaction_id']}",
        json_body={
            "ticker": book["ticker"],
            "action": "buy",
            "quantity": 5,
            "price": 30,
            "trade_date": "2026-02-02",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "buy"
    assert response.json()["quantity"] == 5.0
    positions = _positions(book)
    assert positions[0]["quantity"] == 5.0
    assert positions[0]["cost_basis"] == 150.0


def test_create_rejects_an_ambiguous_cash_row(book):
    """The same convention on creation: a dividend's amount lives in price,
    so 100 x 0.25 is ambiguous and is refused instead of being declared."""
    response = signed_request(
        book["client"], SECRET, book["tenant"], book["user"], "POST",
        "/api/portfolio/transactions",
        json_body={
            "ticker": book["ticker"],
            "action": "dividend",
            "quantity": 100,
            "price": "0.25",
            "trade_date": "2026-03-02",
        },
    )
    assert response.status_code == 400
    assert "ambiguous" in response.json()["detail"]

    accepted = signed_request(
        book["client"], SECRET, book["tenant"], book["user"], "POST",
        "/api/portfolio/transactions",
        json_body={
            "ticker": book["ticker"],
            "action": "dividend",
            "quantity": 0,
            "price": "25.00",
            "trade_date": "2026-03-02",
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["quantity"] == 0.0
    assert accepted.json()["price"] == 25.0
    # The position is built from the buy leg only: cash never moves quantity.
    assert _positions(book)[0]["quantity"] == 4.0


def test_cash_action_update_on_a_cash_row_is_still_not_found(book):
    """A stored cash leg is not editable through the buy/sell endpoint."""
    created = signed_request(
        book["client"], SECRET, book["tenant"], book["user"], "POST",
        "/api/portfolio/transactions",
        json_body={
            "ticker": book["ticker"],
            "action": "fee",
            "quantity": 1,
            "price": "9.95",
            "trade_date": "2026-03-02",
        },
    )
    assert created.status_code == 201
    response = signed_request(
        book["client"], SECRET, book["tenant"], book["user"], "PUT",
        f"/api/portfolio/transactions/{created.json()['id']}",
        json_body={
            "ticker": book["ticker"],
            "action": "fee",
            "quantity": 1,
            "price": "9.95",
            "trade_date": "2026-03-02",
        },
    )
    assert response.status_code == 404


def test_handwritten_cash_row_is_not_replayable_by_the_ledger():
    """Unit-level invariant behind the guard: rebuild_position only replays
    buy/sell, which is exactly why a cash action must never be written onto
    a buy/sell leg. The DB has no CHECK constraint to stop it."""
    from datetime import date as _date

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base as _Base
    from app.services.portfolio_ledger_service import PortfolioLedgerService

    engine = create_engine("sqlite:///:memory:")
    _Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        row = Transaction(
            trade_date=_date(2026, 1, 2), action="dividend",
            quantity=Decimal("1"), price=Decimal("25"), fees=Decimal("0"),
            currency="USD", external_id="manual-cash",
        )
        session.add(row)
        session.commit()
        company = PortfolioLedgerService().ensure_company(session, "CASHX")
        session.flush()
        row.company_id = company.id
        session.commit()
        # No buy/sell leg: nothing to rebuild, so nothing would keep the
        # position alive if this row had replaced a buy.
        assert PortfolioLedgerService().rebuild_position(session, company.id) is None
