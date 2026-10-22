"""Formato SINTETICO de comentarios preparados con hablante solo en su linea (sin cargo)."""
from datetime import date

from app.services.commitment_extraction_service import (
    ROLE_NOT_IN_DOCUMENT,
    extract_with_diagnostics,
)

DOC = """Third Quarter Results
Teleconference Prepared Remarks
Moderator:
Welcome to the Acme Corp call. I will now turn the conference over to the chief executive officer of Acme, Jane Roe.
Jane Roe
We will open 12 new sites by the end of the year.
Across the business:
• We expect to ship version two in 2027;
• We will hire 200 engineers during 2027.
With that, I will turn it over to John.
John Doe
We expect to reach 30% margin in 2028.
Now, operator, let's open the line for questions.
Post-Q&A Jane Close
We will double the budget in 2029.
"""


def test_name_only_prepared_remarks_recognise_turns_and_do_not_invent_role():
    cs, dg = extract_with_diagnostics(DOC, call_date=date(2026, 10, 13))
    assert dg["parser"] == "nombre_solo_comentarios_preparados" and dg["management_turns"] == 2
    assert {c.speaker for c in cs} == {"Jane Roe", "John Doe"}
    roles = {c.speaker: c.speaker_role for c in cs}
    assert roles["Jane Roe"] == "chief executive officer of Acme" and roles["John Doe"] == ROLE_NOT_IN_DOCUMENT
    quotes = [c.quote_literal for c in cs]
    assert any("12 new sites" in q for q in quotes)
    # viñetas: una frase por punto, sin mezclarlas
    assert any(q.startswith("We expect to ship version two in 2027") and "hire" not in q for q in quotes)
    assert any(q.startswith("We will hire 200 engineers") for q in quotes)


def test_post_qa_closing_is_not_attributed_to_previous_speaker():
    cs, _ = extract_with_diagnostics(DOC, call_date=date(2026, 10, 13))
    assert not any("double the budget" in c.quote_literal for c in cs)


def test_name_only_requires_prepared_remarks_header():
    cs, dg = extract_with_diagnostics(DOC.replace("Prepared Remarks", "Notes"), call_date=date(2026, 10, 13))
    assert dg["management_turns"] == 0 and cs == []


INLINE = (
    "Intro. On August 5, Acme reported results. Below is the transcript. Jane Roe, PhD, CEO and President of Acme:\n"
    "Good morning. We will open 12 new sites by the end of the year. \u200d\n"
    "\u200dJohn Doe, Chief Financial Officer of Acme:We expect to reach 30% margin in 2028.\n"
    "Sam Lee, Analyst at Bank Capital:\n"
    "We will triple the dividend in 2030.\n"
)


def test_inline_header_name_role_colon_recognised_and_analysts_cut():
    cs, dg = extract_with_diagnostics(INLINE, call_date=date(2026, 8, 5))
    assert dg["parser"] == "encabezado_nombre_cargo_inline" and dg["management_turns"] == 2
    assert {c.speaker for c in cs} == {"Jane Roe, PhD", "John Doe"}
    assert {c.speaker_role for c in cs} == {"CEO and President of Acme", "Chief Financial Officer of Acme"}
    assert not any("triple the dividend" in c.quote_literal for c in cs)


FAKE = """Quarterly Teleconference Prepared Remarks
Moderator:
I will now turn the conference over to the chief executive officer of Acme, Jane Roe.
Jane Roe
Good morning.
Key Highlights
We will open 12 new sites by the end of the year.
Operating Margin
We expect to reach 30% margin in 2028.
Forward Looking
We will hire 200 engineers during 2027.
Acme Corp
We will double the budget in 2029.
"""


def test_title_lines_shaped_like_names_are_not_speakers_without_document_evidence():
    cs, dg = extract_with_diagnostics(FAKE, call_date=date(2026, 10, 13))
    assert dg["management_turns"] == 1
    assert {c.speaker for c in cs} == {"Jane Roe"}  # los titulos quedan como texto de Jane, no como hablantes
    assert not any(c.speaker in ("Key Highlights", "Operating Margin", "Forward Looking", "Acme Corp") for c in cs)


def test_post_qa_variants_cut_the_turn():
    for mark in ("Post Q&A", "Post-Q&A", "Post Q & A", "Q&A", "(Post-Q&A Close)"):
        doc = DOC.replace("Post-Q&A Jane Close", f"Jane {mark}" if mark.startswith("(") else f"{mark} Jane Close")
        cs, _ = extract_with_diagnostics(doc, call_date=date(2026, 10, 13))
        assert not any("double the budget" in c.quote_literal for c in cs), mark


AMBIG = """Quarterly Teleconference Prepared Remarks
Moderator:
Welcome. I will now turn it over to Tim.
Tim Noel
We will open 12 new sites by the end of the year.
Tim Brown
We expect to reach 30% margin in 2028.
"""


def test_first_name_handoff_is_ignored_when_two_name_lines_share_it():
    cs, dg = extract_with_diagnostics(AMBIG, call_date=date(2026, 10, 13))
    assert dg["management_turns"] == 0 and cs == []  # "Tim" no identifica a nadie: fail closed


def test_first_name_handoff_still_works_when_unique():
    doc = AMBIG.replace("Tim Brown", "Ann Brown").replace("turn it over to Tim.", "turn it over to Tim. Ann Brown, thanks.")
    cs, dg = extract_with_diagnostics(doc, call_date=date(2026, 10, 13))
    assert {c.speaker for c in cs} == {"Tim Noel"}
