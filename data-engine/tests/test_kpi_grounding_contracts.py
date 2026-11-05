"""Contracts for a reported KPI: locale, scale and grounding in its quote.

The defects these pin down were all invisible from the outside because the
value passed every existing check:

* the Spanish decimal comma was stripped, so a reported 3.456,7 millones
  became 3.456.700 (1000x below reality) and was published as a canonical fact;
* the scale multiplier was read from the value text, so a bare "b" inside a
  label turned a number into billions;
* a verbatim quote vouched for a figure it never mentioned, so `approve()`
  wrote a number the document never reported.
"""

import asyncio
import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.routing import TaskModelRouter
from app.models.entities import (
    Base,
    Company,
    Document,
    DocumentChunk,
    KPIExtractionCandidate,
)
from app.services.kpi_extraction_service import KPIExtractionService
from app.services.number_parsing import find_number_tokens, parse_localized_number

LOCALE_TOKENS = [
    ("3.456,7", Decimal("3456.7")),
    ("0,24", Decimal("0.24")),
    ("1.234,56", Decimal("1234.56")),
    ("1,234.56", Decimal("1234.56")),
    ("1,234", Decimal("1234")),
    ("1.250", Decimal("1250")),
    ("1.234.567", Decimal("1234567")),
    ("1,234,567", Decimal("1234567")),
    ("12,5", Decimal("12.5")),
    ("120.50", Decimal("120.50")),
    ("1 234,5", Decimal("1234.5")),
    ("(1.234,5)", Decimal("-1234.5")),
    ("-45,75", Decimal("-45.75")),
]


@pytest.mark.parametrize("raw,expected", LOCALE_TOKENS)
def test_locale_tokens_keep_their_magnitude(raw, expected):
    parsed = parse_localized_number(raw)
    assert parsed is not None, raw
    assert parsed[0] == expected


@pytest.mark.parametrize("raw", ["n/a", "12%", "1.2.3", "", "   "])
def test_unparseable_tokens_never_become_a_zero(raw):
    assert parse_localized_number(raw) is None


def test_tokenizer_keeps_the_figures_of_a_spanish_sentence_apart():
    # "en 2024, 1.234,5 millones" is TWO figures. Merging them on the comma and
    # the space yields 20241.2345, which then vouches for nothing.
    assert find_number_tokens("en 2024, 1.234,5 millones") == ["2024,", "1.234,5"]
    assert find_number_tokens("1 234 567,89") == ["1234567,89"]
    assert find_number_tokens("12,5 % 3") == ["12,5", "3"]


SCALED_VALUES = [
    # raw, unit, canonical unit, expected value
    ("3.456,7", "millones", "decimal", Decimal("3456700000")),
    ("3.456,7", "million", "USD", Decimal("3456700000")),
    ("2,5", "mil millones", "USD", Decimal("2500000000")),
    ("2,5", "billones", "USD", Decimal("2500000000000")),
    ("500", "miles de euros", "EUR", Decimal("500000")),
    ("1,2", "b", "USD", Decimal("1200000000")),
    ("26,461", "M", "USD", Decimal("26461000000")),
    ("12,5", "por ciento", "decimal", Decimal("0.125")),
    ("25", "%", "decimal", Decimal("0.25")),
    ("(1.250)", "thousand", "USD", Decimal("-1250000")),
    ("(1,250)", "thousand", "USD", Decimal("-1250000")),
    ("391", "billion USD", "USD", Decimal("391000000000")),
    ("1234567", "USD", "USD", Decimal("1234567")),
]


@pytest.mark.parametrize("raw,unit,canonical,expected", SCALED_VALUES)
def test_scale_comes_from_the_declared_unit(raw, unit, canonical, expected):
    value, meta = KPIExtractionService._normalize(raw, unit, canonical)
    assert value == expected, (raw, unit)
    assert meta["scale_source"] == "unit_only"


def test_value_text_never_invents_a_scale():
    # A label that happens to contain a scale letter is not a unit: the
    # multiplier is 1 and the figure is left as written.
    value, meta = KPIExtractionService._normalize("balance b", "USD", "USD")
    assert value is None
    value, meta = KPIExtractionService._normalize("4,2 B clientes", "USD", "USD")
    assert value == Decimal("4.2")
    assert meta["multiplier"] == "1"


def test_label_text_does_not_become_the_figure():
    # The fiscal year is part of the raw value, not the KPI.
    value, _ = KPIExtractionService._normalize("Ingresos FY24: 1.234,5", "M EUR", "decimal")
    assert value == Decimal("1234500000")


GROUNDED_QUOTE = (
    "Los ingresos del ejercicio 2024 ascendieron a 1.234,5 millones de euros, "
    "un 12,5% mas que en 2023."
)


def test_grounding_accepts_the_figures_the_quote_states():
    figures = KPIExtractionService._quote_figures(GROUNDED_QUOTE)
    assert figures, GROUNDED_QUOTE
    assert {figure.value for figure in figures} == {
        Decimal("2024"), Decimal("1234.5"), Decimal("12.5"), Decimal("2023"),
    }
    # The canonical value carries the multiplier the quote states explicitly.
    assert KPIExtractionService._value_supported(Decimal("1234500000"), figures, "USD") is True
    # A percentage is stored as a decimal rate.
    assert KPIExtractionService._value_supported(Decimal("0.125"), figures, "decimal") is True


def test_grounding_rejects_a_figure_the_quote_never_states():
    figures = KPIExtractionService._quote_figures(GROUNDED_QUOTE)
    assert KPIExtractionService._value_supported(Decimal("9999"), figures, "USD") is False
    # The 1000x error this service used to publish: 3.456.700 instead of
    # 3.456.700.000 is a real number, but not one the quote supports.
    assert KPIExtractionService._value_supported(Decimal("3456700"), figures, "USD") is False


def test_a_quote_without_figures_cannot_vouch_for_a_value():
    assert KPIExtractionService._quote_figures("los ingresos del ejercicio") == []


def test_the_fiscal_year_cannot_vouch_for_the_kpi():
    # "Ingresos FY2025: 100 millones" yields the tokens {2025, 100}. The old
    # magnitude ladder accepted 2.025.000.000 because the year 2025 was in the
    # set and a 1e6 ratio was tolerated: the fiscal year became the KPI.
    figures = KPIExtractionService._quote_figures(
        "Ingresos FY2025: 100 millones de euros."
    )
    by_value = {figure.value: figure for figure in figures}
    assert by_value[Decimal("2025")].year_like is True
    assert by_value[Decimal("100")].scale == Decimal("1e6")
    assert KPIExtractionService._value_supported(Decimal("2025000000"), figures, "EUR") is False
    assert KPIExtractionService._value_supported(Decimal("100000000"), figures, "EUR") is True


def test_a_scale_the_quote_does_not_state_cannot_vouch():
    # The quote says "millones": a figure stored in miles, or a hundred times
    # over, is not what the document reported even though a global magnitude
    # ladder used to wave both through.
    figures = KPIExtractionService._quote_figures("Los ingresos fueron 100 millones.")
    assert KPIExtractionService._value_supported(Decimal("100000"), figures, "EUR") is False
    assert KPIExtractionService._value_supported(Decimal("10000000000"), figures, "EUR") is False
    assert KPIExtractionService._value_supported(Decimal("100000000"), figures, "EUR") is True


def test_the_sign_of_the_quote_is_part_of_the_figure():
    # abs() used to erase accounting parentheses, so a loss vouched for a
    # profit of the same magnitude.
    figures = KPIExtractionService._quote_figures("El resultado fue (100) millones de euros.")
    assert {figure.value for figure in figures} == {Decimal("-100")}
    assert KPIExtractionService._value_supported(Decimal("-100000000"), figures, "EUR") is True
    assert KPIExtractionService._value_supported(Decimal("100000000"), figures, "EUR") is False
    figures = KPIExtractionService._quote_figures("El resultado fue -100 millones de euros.")
    assert KPIExtractionService._value_supported(Decimal("100000000"), figures, "EUR") is False


def test_a_figure_cannot_borrow_the_unit_of_the_next_one():
    # The unit window is cut where the next figure starts: in "un 12,5% mas
    # que en 2023", the year must not pick up the percent sign, and the 12,5
    # must not pick up a scale meant for another number.
    figures = KPIExtractionService._quote_figures("un 12,5% mas que en 2023")
    by_value = {figure.value: figure for figure in figures}
    assert by_value[Decimal("12.5")].percent is True
    assert by_value[Decimal("2023")].year_like is True


# --------------------------------------------------------------------------
# end to end: an ungrounded observation must not reach a canonical fact
# --------------------------------------------------------------------------


class _StaticProvider(LLMProvider):
    name = "test-provider"

    def __init__(self, payload):
        super().__init__(
            model_router=TaskModelRouter(default_model="test-model"),
            timeout_seconds=1,
            max_retries=0,
        )
        self.payload = payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            message=Message("assistant", json.dumps(self.payload)),
            usage=Usage(100, 50, 150, cache_read_tokens=20),
            model="test-model",
            provider=self.name,
            request_id="test-request",
        )


def _extraction(chunk_text: str, raw_value: str, raw_unit: str = "percent") -> KPIExtractionCandidate:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(
            ticker="ASTS", name="ASTS Test", exchange="TEST", currency="USD",
            sector="Test", industry="Test", company_type="space_telecom_pre_fcf",
            valuation_model="space_pre_revenue_dcf", special_sources=[],
            special_risks=[], factor_tags=["space", "telecom"],
        )
        db.add(company)
        db.flush()
        db.info["tenant_id"] = "grounding-fixture"
        document = Document(
            company_id=company.id, title="FY2025 update", source_type="company_ir"
        )
        db.add(document)
        db.flush()
        chunk = DocumentChunk(document_id=document.id, chunk_index=0, text=chunk_text)
        db.add(chunk)
        db.commit()

        provider = _StaticProvider(
            {
                "observations": [
                    {
                        "metric_key": "penetration",
                        "raw_label": "Penetration",
                        "raw_value": raw_value,
                        "raw_unit": raw_unit,
                        "period": "FY2025",
                        "fiscal_year": 2025,
                        "fiscal_quarter": "FY",
                        "chunk_id": chunk.id,
                        "quote": chunk_text,
                        "confidence": 0.95,
                    }
                ]
            }
        )
        candidates = asyncio.run(
            KPIExtractionService(provider).extract_document(db, document)
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.trace["locator_verified"] is True  # the sentence is real
        if candidate.status == "needs_review":
            with pytest.raises(ValueError, match="pending candidates"):
                KPIExtractionService().approve(db, candidate, actor="analyst")
        return candidate


def test_a_verbatim_quote_cannot_vouch_for_a_figure_it_never_states():
    # Locator verification passes: the sentence IS in the chunk. The reported
    # 38.7% is nowhere in it, so the candidate must not be approvable.
    candidate = _extraction("Penetration reached 12.5% in FY2025.", "38.7%")
    assert candidate.normalized_value == Decimal("0.387")
    assert candidate.reconciliation_status == "needs_review"
    assert candidate.trace["value_grounded"] is False
    assert candidate.trace["figures_in_quote"] == ["12.5", "2025"]


def test_a_quote_without_a_figure_cannot_vouch_for_a_value():
    candidate = _extraction("Penetration was not disclosed for FY2025.", "12.5%")
    assert candidate.reconciliation_status == "needs_review"
    assert candidate.trace["value_grounded"] is False
    assert candidate.trace["figures_in_quote"] == ["2025"]


def test_a_grounded_figure_stays_approvable():
    candidate = _extraction("Penetration reached 12.5% in FY2025.", "12.5%")
    assert candidate.normalized_value == Decimal("0.125")
    assert candidate.reconciliation_status == "reconciled"
    assert candidate.status == "pending_approval"
    assert candidate.trace["value_grounded"] is True


def test_the_fiscal_year_cannot_become_the_kpi_end_to_end():
    # "Penetration reached 12.5% in FY2025." reported as "2025": the year was
    # in the quote's figure set and the old magnitude ladder accepted it, so
    # 2025 percent points reached pending_approval as a canonical fact. It
    # must now stop at needs_review, where approve() refuses to persist it.
    candidate = _extraction("Penetration reached 12.5% in FY2025.", "2025")
    assert candidate.reconciliation_status == "needs_review"
    assert candidate.status == "needs_review"
    assert candidate.trace["value_grounded"] is False


def test_a_negative_report_cannot_hide_behind_a_positive_quote_end_to_end():
    # The quote says penetration ROSE to 12.5%. Reporting -12.5% used to pass
    # because abs() erased the sign on both sides of the comparison.
    candidate = _extraction("Penetration reached 12.5% in FY2025.", "(12,5)%")
    assert candidate.normalized_value == Decimal("-0.125")
    assert candidate.reconciliation_status == "needs_review"
    assert candidate.trace["value_grounded"] is False


def test_a_percent_quote_vouches_only_the_fraction_for_a_decimal_kpi():
    figures = KPIExtractionService._quote_figures("Penetration reached 12.5% in FY2025.")
    assert KPIExtractionService._value_supported(Decimal("0.125"), figures, "decimal") is True
    # The points as written are 100x the rate: with canonical decimal they
    # must NOT vouch, or a raw_unit "unknown" sneaks 12,5 in as reconciled.
    assert KPIExtractionService._value_supported(Decimal("12.5"), figures, "decimal") is False


def test_a_percent_quote_with_raw_unit_unknown_degrades_end_to_end():
    # Real path of the hole: canonical_unit decimal, raw_value "12,5" with
    # raw_unit "unknown" normalizes to 12.5 (no percent division), and the
    # quote "12,5%" used to vouch it via the points as written: a 100x error
    # that approve() could persist. It must stop at needs_review.
    engine_chunk = "Penetration reached 12.5% in FY2025."
    candidate = _extraction(engine_chunk, "12,5", "unknown")
    assert candidate.normalized_value == Decimal("12.5")
    assert candidate.reconciliation_status == "needs_review"
    assert candidate.status == "needs_review"
    assert candidate.trace["value_grounded"] is False
