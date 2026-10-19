"""Contrato directo de app.valuation.period_bounds (ejes periodo y publicacion)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.valuation.period_bounds import (
    AS_OF_SOURCE_EXPLICIT,
    AS_OF_SOURCE_TODAY_DEFAULT,
    AS_OF_SOURCE_TRACE,
    AS_OF_SOURCE_VALUATION,
    PRECISION_EXACT_DATE,
    PRECISION_FISCAL_YEAR,
    PRECISION_UNKNOWN,
    KnowledgeBounds,
    PeriodBounds,
    assert_knowledge_no_lookahead,
    assert_period_no_lookahead,
    assert_publication_no_lookahead,
    knowledge_bounds,
    parse_period_bounds,
    resolve_as_of,
    to_date,
)
from app.valuation.point_in_time import LookaheadError


def test_to_date_coerces_datetime_date_and_iso_strings() -> None:
    assert to_date(datetime(2025, 3, 31, 10, 0)) == date(2025, 3, 31)
    assert to_date(date(2025, 3, 31)) == date(2025, 3, 31)
    assert to_date(" 2025-03-31T12:00:00Z ") == date(2025, 3, 31)


@pytest.mark.parametrize("value", [None, 20250331, "no-es-fecha", "", "2025-13-45"])
def test_to_date_returns_none_instead_of_raising(value: object) -> None:
    assert to_date(value) is None


def test_iso_date_in_period_is_exact_and_keeps_explicit_fiscal_year() -> None:
    bounds = parse_period_bounds(period="2025-09-30:FY", fiscal_year=2026)
    assert bounds.end_date == date(2025, 9, 30)
    assert bounds.precision == PRECISION_EXACT_DATE
    assert bounds.fiscal_year == 2026
    assert not bounds.is_unverifiable


def test_iso_date_without_fiscal_year_infers_it_from_the_date() -> None:
    bounds = parse_period_bounds(period="2025-09-30:FY")
    assert bounds.fiscal_year == 2025


def test_fiscal_year_plus_quarter_resolves_calendar_quarter_end() -> None:
    bounds = parse_period_bounds(fiscal_year=2025, fiscal_quarter="Q3")
    assert bounds.end_date == date(2025, 9, 30)
    assert bounds.precision == PRECISION_EXACT_DATE


def test_fiscal_year_alone_uses_the_conservative_december_bound() -> None:
    bounds = parse_period_bounds(fiscal_year=2025)
    assert bounds.end_date == date(2025, 12, 31)
    assert bounds.precision == PRECISION_FISCAL_YEAR


def test_unreadable_quarter_falls_back_to_fiscal_year_precision() -> None:
    bounds = parse_period_bounds(fiscal_year=2025, fiscal_quarter="H1")
    assert bounds.precision == PRECISION_FISCAL_YEAR
    assert bounds.end_date == date(2025, 12, 31)


@pytest.mark.parametrize("raw", ["FY2025", "TTM-2025", "2025"])
def test_bare_year_in_free_text_is_fiscal_year_precision(raw: str) -> None:
    bounds = parse_period_bounds(period=raw)
    assert bounds.fiscal_year == 2025
    assert bounds.end_date == date(2025, 12, 31)
    assert bounds.precision == PRECISION_FISCAL_YEAR


def test_year_with_quarter_in_free_text_resolves_quarter_end() -> None:
    bounds = parse_period_bounds(period="2025 Q2")
    assert bounds.end_date == date(2025, 6, 30)
    assert bounds.precision == PRECISION_EXACT_DATE


@pytest.mark.parametrize("raw", [None, "", "   ", "sin periodo", "Q3"])
def test_nothing_usable_is_unknown_and_unverifiable(raw: str | None) -> None:
    bounds = parse_period_bounds(period=raw)
    assert bounds.precision == PRECISION_UNKNOWN
    assert bounds.end_date is None
    assert bounds.is_unverifiable
    assert bounds.raw is None or bounds.raw == raw.strip()


def test_period_bounds_as_dict_serialises_dates() -> None:
    payload = parse_period_bounds(period="2025-09-30:FY").as_dict()
    assert payload == {
        "raw": "2025-09-30:FY",
        "end_date": "2025-09-30",
        "fiscal_year": 2025,
        "precision": PRECISION_EXACT_DATE,
    }
    assert PeriodBounds().as_dict()["end_date"] is None


def test_known_on_is_the_later_of_period_end_and_publication() -> None:
    bounds = knowledge_bounds(period="2024-12-31:FY", published_at="2026-02-10")
    assert bounds.known_on == date(2026, 2, 10)
    assert not bounds.unverifiable


def test_missing_publication_date_makes_the_input_unverifiable() -> None:
    bounds = knowledge_bounds(period="2024-12-31:FY")
    assert bounds.known_on is None
    assert bounds.unverifiable


def test_unreadable_period_makes_the_input_unverifiable_even_if_published() -> None:
    bounds = knowledge_bounds(period="???", published_at=date(2025, 1, 1))
    assert bounds.known_on is None
    assert bounds.unverifiable


def test_knowledge_bounds_as_dict_reports_all_axes() -> None:
    payload = knowledge_bounds(period="2024-12-31:FY", published_at="2025-02-01").as_dict()
    assert payload["published_on"] == "2025-02-01"
    assert payload["known_on"] == "2025-02-01"
    assert payload["unverifiable"] is False
    empty = KnowledgeBounds(period=PeriodBounds()).as_dict()
    assert empty["published_on"] is None
    assert empty["known_on"] is None
    assert empty["unverifiable"] is True


def test_period_ending_after_as_of_raises_lookahead() -> None:
    bounds = parse_period_bounds(period="2025-09-30:FY")
    with pytest.raises(LookaheadError, match="look-ahead"):
        assert_period_no_lookahead(as_of=date(2025, 3, 31), bounds=bounds, label="ingresos")
    assert_period_no_lookahead(as_of=date(2025, 9, 30), bounds=bounds, label="ingresos")


def test_unknown_period_does_not_raise_it_is_absence_of_proof() -> None:
    assert_period_no_lookahead(
        as_of=date(2020, 1, 1), bounds=PeriodBounds(), label="ingresos"
    )


def test_publication_after_as_of_raises_even_when_period_is_past() -> None:
    with pytest.raises(LookaheadError, match="aun no era publico"):
        assert_publication_no_lookahead(
            as_of=date(2025, 6, 1), published_on=date(2026, 1, 5), label="FY2024"
        )
    assert_publication_no_lookahead(as_of=date(2025, 6, 1), published_on=None, label="x")
    assert_publication_no_lookahead(
        as_of=date(2025, 6, 1), published_on=date(2025, 6, 1), label="x"
    )


def test_combined_guard_reports_period_violation_first_then_source() -> None:
    late_period = knowledge_bounds(period="2025-12-31:FY", published_at="2024-01-01")
    with pytest.raises(LookaheadError, match="termina en"):
        assert_knowledge_no_lookahead(as_of=date(2025, 1, 1), bounds=late_period, label="FCF")
    late_source = knowledge_bounds(period="2024-12-31:FY", published_at="2026-01-01")
    with pytest.raises(LookaheadError, match=r"FCF \(fuente\)"):
        assert_knowledge_no_lookahead(as_of=date(2025, 6, 1), bounds=late_source, label="FCF")


def test_resolve_as_of_precedence_explicit_valuation_trace_snapshot_today() -> None:
    explicit = resolve_as_of(
        as_of="2025-01-02", valuation={"as_of": "2025-02-02"}, trace={"as_of": "2025-03-02"}
    )
    assert (explicit.cutoff, explicit.source, explicit.inferred) == (
        date(2025, 1, 2),
        AS_OF_SOURCE_EXPLICIT,
        False,
    )
    from_valuation = resolve_as_of(valuation={"as_of": "2025-02-02"}, trace={"as_of": "2025-03-02"})
    assert from_valuation.source == AS_OF_SOURCE_VALUATION
    assert from_valuation.cutoff == date(2025, 2, 2)
    from_trace = resolve_as_of(trace={"as_of": "2025-03-02"})
    assert from_trace.source == AS_OF_SOURCE_TRACE
    from_snapshot = resolve_as_of(trace={"snapshot": {"as_of": "2025-04-02"}})
    assert from_snapshot.cutoff == date(2025, 4, 2)
    assert from_snapshot.source == AS_OF_SOURCE_TRACE
    assert from_snapshot.inferred is False


@pytest.mark.parametrize("snapshot", [["2025-04-02"], "2025-04-02", 7, None])
def test_malformed_snapshot_never_breaks_resolution(snapshot: object) -> None:
    result = resolve_as_of(trace={"snapshot": snapshot}, today=date(2026, 1, 1))
    assert result.source == AS_OF_SOURCE_TODAY_DEFAULT
    assert result.inferred is True
    assert result.cutoff == date(2026, 1, 1)
    assert result.as_dict() == {
        "as_of": "2026-01-01",
        "as_of_source": AS_OF_SOURCE_TODAY_DEFAULT,
        "as_of_inferred": True,
    }


def test_resolve_as_of_defaults_to_today_when_nothing_given() -> None:
    result = resolve_as_of()
    assert result.cutoff == date.today()
    assert result.inferred is True
