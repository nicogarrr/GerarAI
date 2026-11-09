"""Instrument-reference edge contracts using real SQLite where SQL matters."""

from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, InstrumentReference
from app.services import instrument_reference as ref

AS_OF = date(2026, 11, 9)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


@pytest.mark.parametrize("length,accepted", [(40, True), (41, False)])
def test_normalize_ticker_length_boundary(length, accepted):
    result = ref.normalize_row({"symbol": "a" * length}, as_of=AS_OF)
    assert (result is not None) is accepted
    if accepted:
        assert result["ticker_normalized"] == "A" * length


@pytest.mark.parametrize(
    "field,width",
    [("figi", 12), ("composite_figi", 12), ("shareclass_figi", 12), ("isin", 12), ("cusip", 9), ("sedol", 7)],
)
def test_normalize_code_spaces_case_and_length(field, width):
    result = ref.normalize_row(
        {"ticker": " abc ", field: " a " + "b" * (width - 1)}, as_of=AS_OF, source="fixture"
    )
    assert result[field] == "A" + "B" * (width - 1)
    assert result["ticker_normalized"] == "ABC"
    assert result["source"] == "fixture" and result["as_of"] == AS_OF
    assert ref.normalize_row({"symbol": "ABC", field: "x" * (width + 1)}, as_of=AS_OF)[field] is None


def test_names_by_cusip_exact_match_normalization_and_missing_name(db):
    db.add_all(
        [
            InstrumentReference(
                ticker_normalized="ONE", cusip="ABC123456", name="Full issuer", as_of=AS_OF, source="fixture"
            ),
            InstrumentReference(
                ticker_normalized="TWO", cusip="ABC123457", name="Other issuer", as_of=AS_OF, source="fixture"
            ),
            InstrumentReference(
                ticker_normalized="NONAME", cusip="ABC123458", name=None, as_of=AS_OF, source="fixture"
            ),
        ]
    )
    db.flush()
    assert ref.names_by_cusip(db, [" abc123456 ", "ABC123456", "ABC123458", "ABC123", "", None]) == {
        "ABC123456": "Full issuer"
    }
    assert ref.names_by_cusip(db, []) == {}


def test_empty_identity_does_not_query_database():
    db = Mock()
    assert ref.get_by_ticker(db, " ") is None
    assert ref.get_by_figi(db, " ") == []
    assert ref.names_by_cusip(db, ["", " ", None]) == {}
    assert db.mock_calls == []


def test_missing_table_queries_degrade_to_unknown():
    engine = create_engine("sqlite:///:memory:")
    try:
        with Session(engine) as session:
            assert ref.get_by_ticker(session, "ABC") is None
            assert ref.get_by_figi(session, "FIGI") == []
            assert ref.names_by_cusip(session, ["ABC123456"]) == {}
    finally:
        engine.dispose()


def test_sibling_without_figi_returns_only_own_ticker(db):
    db.add(InstrumentReference(ticker_normalized="ABC", as_of=AS_OF, source="fixture"))
    db.flush()
    assert ref.sibling_tickers(db, " abc ") == ["ABC"]


def test_sibling_query_failure_preserves_already_emitted_candidates(monkeypatch):
    row = InstrumentReference(ticker_normalized="OWN", figi="FIGI", composite_figi="COMPOSITE")
    sibling = InstrumentReference(ticker_normalized="RENAMED")
    db = Mock()
    db.scalars.side_effect = [Mock(all=Mock(return_value=[sibling])), RuntimeError("second query failed")]
    monkeypatch.setattr(ref, "get_by_ticker", lambda *args: row)
    assert ref.sibling_tickers(db, "OWN") == ["OWN", "RENAMED"]
    assert db.scalars.call_count == 2


def test_flush_mode_and_skipped_rows_are_rollbackable(db):
    row = ref.normalize_row({"symbol": "ABC", "name": "Issuer"}, as_of=AS_OF)
    assert ref.upsert_rows(db, [{}, {"ticker_normalized": ""}, row], commit=False) == {
        "inserted": 1,
        "updated": 0,
        "skipped": 2,
    }
    assert (
        db.scalar(select(InstrumentReference).where(InstrumentReference.ticker_normalized == "ABC")).name
        == "Issuer"
    )
    db.rollback()
    assert ref.get_by_ticker(db, "ABC") is None


@pytest.mark.parametrize(
    "figi,composite,expected",
    [("SHARED", None, ["FIGI_MATCH"]), (None, "COMPOSITE", ["COMPOSITE_MATCH"]), (None, None, [])],
)
def test_sibling_generator_uses_only_declared_identity_axes(db, figi, composite, expected):
    db.add_all(
        [
            InstrumentReference(ticker_normalized="FIGI_MATCH", figi="SHARED", as_of=AS_OF, source="fixture"),
            InstrumentReference(
                ticker_normalized="COMPOSITE_MATCH", composite_figi="COMPOSITE", as_of=AS_OF, source="fixture"
            ),
            InstrumentReference(
                ticker_normalized="OTHER", figi="OTHER", composite_figi="OTHER", as_of=AS_OF, source="fixture"
            ),
        ]
    )
    db.flush()
    row = InstrumentReference(ticker_normalized="REQUEST", figi=figi, composite_figi=composite)
    assert list(ref.figi_sibling_tickers(db, row)) == expected
