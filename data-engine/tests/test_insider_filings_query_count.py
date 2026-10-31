"""N+1 en /api/insider/filings: las transacciones se cargan en lote.

Una pagina de N filings no puede costar N+1 consultas; el numero de
sentencias SQL queda acotado sea cual sea el tamano de pagina. La forma de la
respuesta (cap de 50 transacciones por filing, orden por id) no cambia.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import insider as insider_module
from app.core.database import get_db
from app.models.entities import Base, InsiderFiling, InsiderTransaction, Tenant


def _client(filing_count: int, txs_per_filing: int = 2):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    for i in range(filing_count):
        filing = InsiderFiling(
            tenant_id=1,
            accession_number=f"0001234567-24-{i:06d}",
            form="4",
            issuer_cik="1234567",
            issuer_ticker="ACME",
            filing_date=f"2024-03-{(i % 28) + 1:02d}",
            parser_version="1.1",
        )
        db.add(filing)
        db.flush()
        for j in range(txs_per_filing):
            db.add(
                InsiderTransaction(
                    tenant_id=1,
                    fingerprint=f"{i}-{j}",
                    filing_id=filing.id,
                    accession_number=filing.accession_number,
                    form="4",
                    issuer_ticker="ACME",
                    insider=f"Insider {j}",
                    code="P",
                )
            )
    db.commit()
    app = FastAPI()
    app.include_router(insider_module.router, prefix="/api/insider")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app), engine


def _count_statements(engine, fn):
    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    return result, statements


def test_filings_page_loads_transactions_in_constant_queries():
    client, engine = _client(filing_count=12)
    response, statements = _count_statements(
        engine,
        lambda: client.get("/api/insider/filings", params={"ticker": "ACME", "limit": 12}),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 12
    assert all(f["transaction_count"] == 2 for f in payload["filings"])
    # Filings + total + lote de transacciones + FPI = 4; nunca 1 por filing.
    assert len(statements) <= 4, f"{len(statements)} sentencias para 12 filings"


def test_filings_transactions_keep_order_and_cap_per_filing():
    client, engine = _client(filing_count=3, txs_per_filing=55)
    response, statements = _count_statements(
        engine, lambda: client.get("/api/insider/filings", params={"ticker": "ACME", "limit": 3})
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3
    for filing in payload["filings"]:
        assert filing["transaction_count"] == 50
        assert len(filing["transactions"]) == 50
    assert len(statements) <= 4, f"{len(statements)} sentencias para 3 filings x 55 txs"
