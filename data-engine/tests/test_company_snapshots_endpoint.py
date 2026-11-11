"""GET /api/companies/snapshots (batch del indice): 40 tickers, queries acotadas.

La ruta resuelve los tickers en 1-2 queries IN (politica de alias de
resolve_company) y el servicio agrega el resto: con 40 empresas NO puede
haber ~40+ queries (ese era el fan-out que se elimina).
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.companies import MAX_SNAPSHOT_BATCH_TICKERS, company_snapshots_batch
from app.models.entities import Base, Company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_batch_endpoint_40_tickers_bounded_queries(db: Session):
    tickers = [f"T{i:02d}" for i in range(38)]
    for ticker in tickers:
        _company(db, ticker)
    san = _company(db, "SAN")  # alias con sufijo: SAN.MC -> SAN
    # Real Madrid listing, not a synthetic NASDAQ homonym.
    san.exchange, san.currency = "BME", "EUR"
    db.flush()
    requested = tickers + ["SAN.MC", "NOPE"]

    engine = db.get_bind()
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    response = company_snapshots_batch(tickers=",".join(requested), db=db)

    assert set(response.snapshots) == set(tickers) | {"SAN"}
    assert response.missing == ["NOPE"]
    # 1 (IN exactos) + 1 (IN bases de alias) + ~13 del servicio: nunca ~40.
    assert len(statements) <= 18, f"{len(statements)} queries para 40 tickers"


def test_batch_endpoint_rejects_over_the_cap(db: Session):
    tickers = ",".join(f"X{i}" for i in range(MAX_SNAPSHOT_BATCH_TICKERS + 1))
    with pytest.raises(HTTPException) as excinfo:
        company_snapshots_batch(tickers=tickers, db=db)
    assert excinfo.value.status_code == 400
