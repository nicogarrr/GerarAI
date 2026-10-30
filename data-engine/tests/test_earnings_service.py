"""EarningsWorkflowService deterministic extraction contract tests.

Extracted metrics are always staged as candidate_pending_reconciliation
(never auto-applied), scaling is explicit, and tone is a transparent
lexical score - the deterministic base the thesis review relies on.
"""

from decimal import Decimal

from app.services.earnings_service import (
    EarningsWorkflowService,
    _scaled_value,
)


def test_scaled_value_margins_become_decimals():
    assert _scaled_value("45.5", "%", "gross_margin") == Decimal("0.455")
    assert _scaled_value("12", None, "operating_margin") == Decimal("0.12")


def test_scaled_value_money_scales():
    assert _scaled_value("123.4", "billion", "revenue") == Decimal("123400000000.0")
    assert _scaled_value("2.5", "bn", "revenue") == Decimal("2500000000.0")
    assert _scaled_value("900", "million", "revenue") == Decimal("900000000")
    assert _scaled_value("900", "m", "revenue") == Decimal("900000000")
    assert _scaled_value("42", None, "revenue") == Decimal("42")


def test_extract_metrics_stages_candidates_with_source_document():
    service = EarningsWorkflowService()
    doc_text = "Total revenue was $123.4 billion driven by services. Gross margin of 45.5%."
    metrics = service._extract_metrics(doc_text, {7: doc_text})
    by_metric = {item["metric"]: item for item in metrics}

    revenue = by_metric["revenue"]
    assert revenue["value"] == "123400000000.0"
    assert revenue["unit"] == "USD"
    assert revenue["status"] == "candidate_pending_reconciliation"
    assert revenue["source_document_id"] == 7
    assert "revenue" in revenue["quote"].lower()

    margin = by_metric["gross_margin"]
    assert margin["value"] == "0.455"
    assert margin["unit"] == "decimal"
    assert margin["status"] == "candidate_pending_reconciliation"

    # One candidate per metric at most (first match wins).
    assert sum(1 for m in metrics if m["metric"] == "revenue") == 1
    # Metrics absent from the text are omitted, never invented.
    assert "free_cash_flow" not in by_metric


def test_extract_metrics_marks_unknown_source_document():
    service = EarningsWorkflowService()
    metrics = service._extract_metrics("Net income reached $25 billion", {1: "other text"})
    assert metrics[0]["metric"] == "net_income"
    assert metrics[0]["source_document_id"] is None


def test_tone_lexical_contract():
    service = EarningsWorkflowService()
    positive = service._tone("Strong results, record revenue, improving outlook")
    assert positive["label"] == "positive"
    assert positive["positive_markers"] >= 3
    assert positive["method"] == "lexical_tone_v1"

    negative = service._tone("Weak demand and lowered guidance")
    assert negative["label"] == "negative"
    assert negative["negative_markers"] >= 2

    neutral = service._tone("")
    assert neutral["label"] == "neutral"
    assert neutral["score"] == 0


def test_signed_and_grouped_earnings_numbers_keep_their_value():
    service = EarningsWorkflowService()
    cases = [
        ("Operating margin was -12.5%.", "operating_margin", Decimal("-0.125")),
        ("Net income was -$25 million.", "net_income", Decimal("-25000000")),
        ("Net income was $-25 million.", "net_income", Decimal("-25000000")),
        ("Net income was $25.", "net_income", Decimal("25")),
        ("Net income was $1,250 million.", "net_income", Decimal("1250000000")),
        ("Free cash flow was -1,250.5 million.", "free_cash_flow", Decimal("-1250500000")),
        ("Operating margin was −12.5%.", "operating_margin", Decimal("-0.125")),
        ("Gross margin was +12.5%.", "gross_margin", Decimal("0.125")),
    ]
    for text, metric, expected in cases:
        candidates = {row["metric"]: row for row in service._extract_metrics(text, {9: text})}
        assert metric in candidates, text
        assert Decimal(candidates[metric]["value"]) == expected, text
        assert candidates[metric]["source_document_id"] == 9
        assert candidates[metric]["status"] == "candidate_pending_reconciliation"


def test_accounting_parentheses_are_not_silently_read_as_positive():
    text = "Operating margin was (12.5)%. Net income was ($25 million)."
    assert EarningsWorkflowService()._extract_metrics(text, {1: text}) == []


def test_incomplete_numeric_groups_do_not_create_truncated_candidates():
    for text in ("Net income was $1,25 million.", "Net income was $12.5.3 million."):
        assert EarningsWorkflowService()._extract_metrics(text, {1: text}) == []


def test_metric_patterns_skip_fiscal_years_and_growth_rates():
    import re as _re

    from app.services.earnings_service import METRIC_PATTERNS as _P

    def first(metric, text):
        m = _re.search(_P[metric], text, _re.IGNORECASE)
        return m.groups() if m else None

    assert first("revenue", "Revenue for the third quarter of 2026 was $5.1 billion.") == ("$5.1", "billion")
    assert first("revenue", "Revenue grew 12% to $5.1 billion.") == ("$5.1", "billion")
    assert first("revenue", "Revenue grew 12.5% year over year to 5.1 billion.") == ("5.1", "billion")
    assert first("revenue", "Revenue for fiscal 2026 is expected to grow.") is None
    assert first("net_income", "Net income in 2025 was -$1.2 million.") == ("-$1.2", "million")
    assert first("revenue", "Revenue was $2,026 million.") == ("$2,026", "million")
    assert first("gross_margin", "Gross margin for 2026 was 45.5%.") == ("45.5",)
