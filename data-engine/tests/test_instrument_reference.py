"""Referencia de instrumentos: normalizacion honesta + upsert idempotente."""

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, InstrumentReference
from app.services.instrument_reference import (
    get_by_figi,
    get_by_ticker,
    normalize_row,
    normalize_ticker,
    sibling_tickers,
    upsert_rows,
)

AS_OF = date(2026, 10, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


def test_normalize_ticker_upper_and_strip():
    assert normalize_ticker("  san.mc ") == "SAN.MC"
    assert normalize_ticker("brk.b") == "BRK.B"


def test_normalize_row_empty_cells_become_null_not_defaults(db):
    row = normalize_row(
        {"symbol": "MYST", "name": "Mystery", "sector": "", "industry": "Unknown",
         "country": "nan", "currency": "USD", "figi": "", "isin": ""},
        as_of=AS_OF,
    )
    assert row is not None
    assert row["ticker_normalized"] == "MYST"
    # Honestidad: sin dato en la fuente -> NULL, nunca "Unknown" ni "".
    assert row["sector"] is None
    assert row["industry"] is None
    assert row["country"] is None
    assert row["figi"] is None
    assert row["isin"] is None


def test_normalize_row_without_symbol_is_skipped():
    assert normalize_row({"symbol": "  ", "name": "X"}, as_of=AS_OF) is None
    assert normalize_row({"name": "X"}, as_of=AS_OF) is None


def test_upsert_is_idempotent_and_counts(db):
    rows = [
        normalize_row({"symbol": "AAPL", "name": "Apple", "sector": "Technology"}, as_of=AS_OF),
        normalize_row({"symbol": "SAN.MC", "name": "Santander", "sector": "Financials"}, as_of=AS_OF),
    ]
    assert all(r is not None for r in rows)
    first = upsert_rows(db, rows, commit=True)
    assert first == {"inserted": 2, "updated": 0, "skipped": 0}
    second = upsert_rows(db, rows, commit=True)
    assert second == {"inserted": 0, "updated": 0, "skipped": 0}
    # Cambio real -> updated.
    changed = dict(rows[0])
    changed["sector"] = "Tech Changed"
    third = upsert_rows(db, [changed], commit=True)
    assert third == {"inserted": 0, "updated": 1, "skipped": 0}
    assert db.scalar(select(InstrumentReference).where(
        InstrumentReference.ticker_normalized == "AAPL")).sector == "Tech Changed"


def test_unique_ticker_and_figi_index(db):
    upsert_rows(db, [normalize_row(
        {"symbol": "FAKEOLD", "figi": "BBG000RENA01", "composite_figi": "BBG000RENA02"},
        as_of=AS_OF)], commit=True)
    upsert_rows(db, [normalize_row(
        {"symbol": "FAKENEW", "figi": "BBG000RENA01", "composite_figi": "BBG000RENA02"},
        as_of=AS_OF)], commit=True)
    # Mismo FIGI en dos tickers: permitido (renombre por corporate action).
    found = get_by_figi(db, "BBG000RENA01")
    assert {r.ticker_normalized for r in found} == {"FAKEOLD", "FAKENEW"}
    assert get_by_ticker(db, "fak eold".replace(" ", "")) is not None
    assert get_by_ticker(db, "NOEXISTE") is None
    assert set(sibling_tickers(db, "FAKEOLD")) == {"FAKEOLD", "FAKENEW"}
    assert sibling_tickers(db, "NOEXISTE") == []


def test_upsert_update_never_overwrites_known_value_with_none(db):
    """Lista 11.4: una reingesta sin FIGI/ISIN no puede borrar el ya conocido."""
    full = normalize_row(
        {"symbol": "ACME", "name": "Acme", "sector": "Industrials", "isin": "US001",
         "figi": "BBG000ACME1", "currency": "USD"},
        as_of=AS_OF,
    )
    upsert_rows(db, [full], commit=True)

    sparse = normalize_row(
        {"symbol": "ACME", "name": "Acme Corp", "sector": "", "isin": "", "figi": "",
         "currency": "USD"},
        as_of=AS_OF,
    )
    result = upsert_rows(db, [sparse], commit=True)

    row = db.scalar(select(InstrumentReference).where(InstrumentReference.ticker_normalized == "ACME"))
    assert row.figi == "BBG000ACME1", "un None entrante nunca borra un FIGI conocido"
    assert row.isin == "US001", "un None entrante nunca borra un ISIN conocido"
    assert row.sector == "Industrials", "un None entrante nunca borra el sector conocido"
    assert row.name == "Acme Corp", "los valores no nulos si actualizan"
    assert result == {"inserted": 0, "updated": 1, "skipped": 0}


def test_upsert_update_with_only_nulls_counts_no_change(db):
    full = normalize_row(
        {"symbol": "ACME", "name": "Acme", "sector": "Industrials", "isin": "US001",
         "figi": "BBG000ACME1", "currency": "USD"},
        as_of=AS_OF,
    )
    upsert_rows(db, [full], commit=True)
    only_nulls = {"ticker_normalized": "ACME", "sector": None, "figi": None}
    result = upsert_rows(db, [only_nulls], commit=True)
    assert result == {"inserted": 0, "updated": 0, "skipped": 0}
