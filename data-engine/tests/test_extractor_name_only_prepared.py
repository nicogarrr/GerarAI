"""Formato SINTETICO de comentarios preparados con hablante solo en su linea (sin cargo)."""
from datetime import date

from app.services.commitment_extraction_service import (
    ROLE_NOT_IN_DOCUMENT,
    extract_with_diagnostics,
)

DOC = """Third Quarter Results
Teleconference Prepared Remarks
Moderator:
Welcome to the Acme Corp call. I will now turn the conference over to Jane Roe.
Jane Roe
We will open 12 new sites by the end of the year.
Across the business:
• We expect to ship version two in 2027;
• We will hire 200 engineers during 2027.
John Doe
We expect to reach 30% margin in 2028.
Now, operator, let's open the line for questions.
Post Q&A Jane Close
We will double the budget in 2029.
"""


def test_name_only_prepared_remarks_recognise_turns_and_do_not_invent_role():
    cs, dg = extract_with_diagnostics(DOC, call_date=date(2026, 10, 13))
    assert dg["parser"] == "nombre_solo_comentarios_preparados" and dg["management_turns"] == 2
    assert {c.speaker for c in cs} == {"Jane Roe", "John Doe"}
    assert all(c.speaker_role == ROLE_NOT_IN_DOCUMENT for c in cs)
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
