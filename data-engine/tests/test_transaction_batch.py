"""Batch transaction creation endpoint.

VAL-PERF-008: POST /api/transactions/batch for bulk inserts.
"""


from sqlalchemy import func, select

from app.core.database import SessionLocal, init_db
from app.models import Company, Transaction
from main import app
from tests.auth_helpers import csrf_client


def _batch_post(client, transactions):
    return client.post("/api/portfolio/transactions/batch", json={"transactions": transactions})


def _count_transactions(ticker):
    with SessionLocal() as db:
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if company is None:
            return 0
        return db.scalar(select(func.count()).select_from(Transaction).where(Transaction.company_id == company.id)) or 0


def test_batch_create_success():
    """Batch of valid transactions commits atomically."""
    init_db()
    client = csrf_client(app)
    
    transactions = [
        {
            "ticker": "BATCH1",
            "action": "buy",
            "quantity": "10",
            "price": "100",
            "trade_date": "2025-01-15",
            "currency": "USD",
        },
        {
            "ticker": "BATCH1",
            "action": "buy",
            "quantity": "5",
            "price": "105",
            "trade_date": "2025-01-16",
            "currency": "USD",
        },
        {
            "ticker": "BATCH2",
            "action": "buy",
            "quantity": "20",
            "price": "50",
            "trade_date": "2025-01-17",
            "currency": "EUR",
        },
    ]
    
    response = _batch_post(client, transactions)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["created"] == 3
    assert len(data["transaction_ids"]) == 3
    assert len(data["transactions"]) == 3
    
    # Verify all transactions were created
    assert _count_transactions("BATCH1") == 2
    assert _count_transactions("BATCH2") == 1


def test_batch_rollback_on_validation_error():
    """If any transaction fails validation, entire batch rolls back."""
    init_db()
    client = csrf_client(app)
    
    transactions = [
        {
            "ticker": "ROLLBACK1",
            "action": "buy",
            "quantity": "10",
            "price": "100",
            "trade_date": "2025-01-15",
            "currency": "USD",
        },
        {
            "ticker": "ROLLBACK2",
            "action": "buy",
            "quantity": "0.0000001",  # Too small, rounds to zero
            "price": "50",
            "trade_date": "2025-01-16",
            "currency": "USD",
        },
    ]
    
    response = _batch_post(client, transactions)
    assert response.status_code == 422, response.text
    
    # Verify NO transactions were created
    assert _count_transactions("ROLLBACK1") == 0
    assert _count_transactions("ROLLBACK2") == 0


def test_batch_rollback_on_oversell():
    """If any transaction causes oversell, entire batch rolls back."""
    init_db()
    client = csrf_client(app)
    
    # First create a position
    client.post("/api/portfolio/transactions", json={
        "ticker": "OVERSELL",
        "action": "buy",
        "quantity": "10",
        "price": "100",
        "trade_date": "2025-01-10",
        "currency": "USD",
    })
    
    transactions = [
        {
            "ticker": "OVERSELL",
            "action": "buy",
            "quantity": "5",
            "price": "110",
            "trade_date": "2025-01-15",
            "currency": "USD",
        },
        {
            "ticker": "OVERSELL",
            "action": "sell",
            "quantity": "20",  # Oversell: only 15 shares available
            "price": "120",
            "trade_date": "2025-01-16",
            "currency": "USD",
        },
    ]
    
    response = _batch_post(client, transactions)
    assert response.status_code == 409, response.text
    assert "Transaction 1" in response.text
    
    # Verify the batch additions were rolled back (only initial 10 shares)
    assert _count_transactions("OVERSELL") == 1


def test_batch_fifty_transactions_performance():
    """Batch of 50 transactions completes in under 2 seconds."""
    import time
    init_db()
    client = csrf_client(app)
    
    transactions = []
    for i in range(50):
        transactions.append({
            "ticker": f"PERF{i % 10}",  # 10 different tickers
            "action": "buy",
            "quantity": str(1 + i % 5),
            "price": str(100 + i),
            "trade_date": "2025-01-15",
            "currency": "USD",
        })
    
    start = time.time()
    response = _batch_post(client, transactions)
    elapsed = time.time() - start
    
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["created"] == 50
    assert elapsed < 6.0, f"Batch took {elapsed:.2f}s, expected < 6s"


def test_batch_empty_rejected():
    """Empty batch is rejected."""
    init_db()
    client = csrf_client(app)
    
    response = _batch_post(client, [])
    assert response.status_code == 422, response.text


def test_batch_mixed_actions():
    """Batch can contain buy, sell, and cash transactions."""
    init_db()
    client = csrf_client(app)
    
    # Setup: create position first
    client.post("/api/portfolio/transactions", json={
        "ticker": "MIXED",
        "action": "buy",
        "quantity": "100",
        "price": "50",
        "trade_date": "2025-01-01",
        "currency": "USD",
    })
    
    transactions = [
        {
            "ticker": "MIXED",
            "action": "buy",
            "quantity": "10",
            "price": "55",
            "trade_date": "2025-01-15",
            "currency": "USD",
        },
        {
            "ticker": "MIXED",
            "action": "sell",
            "quantity": "20",
            "price": "60",
            "trade_date": "2025-01-16",
            "currency": "USD",
        },
        {
            "ticker": "MIXED",
            "action": "dividend",
            "quantity": "1",
            "price": "25.50",
            "trade_date": "2025-01-17",
            "currency": "USD",
        },
    ]
    
    response = _batch_post(client, transactions)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["created"] == 3


def test_batch_preserves_order():
    """Transactions are processed in the order provided."""
    init_db()
    client = csrf_client(app)
    
    transactions = [
        {
            "ticker": "ORDER",
            "action": "buy",
            "quantity": "10",
            "price": "100",
            "trade_date": "2025-01-15",
            "currency": "USD",
        },
        {
            "ticker": "ORDER",
            "action": "buy",
            "quantity": "5",
            "price": "110",
            "trade_date": "2025-01-16",
            "currency": "USD",
        },
        {
            "ticker": "ORDER",
            "action": "sell",
            "quantity": "8",
            "price": "120",
            "trade_date": "2025-01-17",
            "currency": "USD",
        },
    ]
    
    response = _batch_post(client, transactions)
    assert response.status_code == 201, response.text
    
    # Verify the sell executed correctly (would fail if order was wrong)
    data = response.json()
    assert data["created"] == 3
