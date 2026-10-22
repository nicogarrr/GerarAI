from datetime import date

from app.services.commitment_extraction_service import extract_candidates

SYNTH = """Acme Corp (ACME)
Second Quarter 2030 Results Conference Call
July 1st, 2030

Jane Doe, Director, Investor Relations

Our remarks include forward-looking statements. We undertake no obligation to update them and we expect 2030 to differ.

Ana Perez, CEO

Thanks everyone. We expect to launch 12 units by the end of 2031.
If demand holds, we will open 3 sites in the third quarter 2030.
We love our customers.

Operator:           Please press star one to ask a question.

Bob Analyst:      Do you expect 99 units in 2031?

Ana Perez:        We do not expect margins above 20% in 2030, and we will review it
                  next call.
"""


def test_extracts_management_only_with_exact_quotes():
    cands = extract_candidates(SYNTH)
    quotes = [c.quote_literal for c in cands]
    assert "We expect to launch 12 units by the end of 2031." in quotes
    assert all(c.speaker == "Ana Perez" and c.speaker_role == "CEO" for c in cands)
    assert not any("forward-looking" in q or "Do you expect" in q for q in quotes)
    flat = " ".join(SYNTH.split())
    assert all(flat[c.char_start : c.char_end] == c.quote_literal for c in cands)
    assert all(c.source_status == "suggested" for c in cands)


def test_flags_conditionals_and_negations_and_due_hints():
    cands = {c.quote_literal: c for c in extract_candidates(SYNTH)}
    cond = cands["If demand holds, we will open 3 sites in the third quarter 2030."]
    assert "conditional" in cond.flags
    assert cond.due_date_hint == date(2030, 9, 30) and cond.due_basis == "quarter_end_hint"
    neg = [c for c in cands.values() if "do not expect" in c.quote_literal][0]
    assert "negation_present" in neg.flags


def test_no_candidates_without_roster():
    assert extract_candidates("Sin cabeceras. We expect 5 units in 2030.") == []


def test_reference_year_does_not_become_due_hint():
    text = "Ana Perez, CEO\n\nWe expect to deliver income this year above 2025 income of $5 billion.\n"
    cands = extract_candidates(text)
    assert cands and cands[0].due_date_hint is None and cands[0].due_basis == "none"


def test_analyst_with_head_role_is_not_management():
    text = (
        "Ana Perez, CEO\n\nWe expect 5 units in 2030.\n\nOperator:  Go ahead.\n\n"
        "Cy Rival, Head of Equity Research\n\nWe expect 99 units in 2031.\n"
    )
    cands = extract_candidates(text)
    assert [c.speaker for c in cands] == ["Ana Perez"]


def test_analyst_header_before_qa_is_excluded():
    text = "Cy Rival, Head of Equity Research\n\nWe expect 99 units in 2031.\n"
    assert extract_candidates(text) == []


def test_abbreviations_do_not_truncate_quote():
    text = "Ana Perez, CEO\n\nWe expect to sign the U.S. Government contract worth $5 billion in 2030. Next topic.\n"
    cands = extract_candidates(text)
    assert cands[0].quote_literal.endswith("worth $5 billion in 2030.")
    assert "U.S. Government" in cands[0].quote_literal


def test_locator_declares_normalization_and_context():
    from app.services.commitment_extraction_service import locator_for, normalize_for_locator

    text = "Ana Perez, CEO\n\nIntro  line.\n\nWe expect\n 5 units in 2030.\n"
    c = extract_candidates(text)[0]
    flat = normalize_for_locator(text)
    assert locator_for(c).startswith("ws_collapse_v1:")
    assert flat[c.char_start : c.char_end] == c.quote_literal
    assert text.find(c.quote_literal) == -1  # offsets NO son del original
    assert c.context_before.rstrip().endswith("Intro line.")
