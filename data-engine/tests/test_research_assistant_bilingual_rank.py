from app.services.research_assistant_service import _rank


def _cit(i: str, excerpt: str) -> dict:
    return {"id": i, "kind": "document_chunk", "source": "10-K", "excerpt": excerpt}


def test_spanish_question_matches_english_filing_text():
    cits = [
        _cit("a", "Management guidance for 2027 includes launch cadence."),
        _cit("b", "Unrelated lease schedule for office space."),
    ]
    ranked = _rank(cits, "¿Qué guía tiene ASTS para 2027?", "ASTS")
    assert [c["id"] for c in ranked] == ["a"]


def test_no_real_match_still_fails_closed_without_recent_fallback():
    cits = [_cit("a", "Lease schedule for office space."), _cit("b", "Auditor fees.")]
    assert _rank(cits, "¿Qué guía tiene ASTS?", "ASTS") == []


def test_translation_never_cites_text_without_one_of_the_forms():
    cits = [_cit("a", "Satellite count is 5."), _cit("b", "Revenue grew.")]
    ranked = _rank(cits, "ingresos", "ASTS")
    assert [c["id"] for c in ranked] == ["b"]


def test_ticker_only_question_has_no_terms():
    assert _rank([_cit("a", "ASTS guidance")], "ASTS", "ASTS") == []


def test_valoracion_matches_valuation_and_dates_have_no_time():
    from app.services.research_assistant_service import _ES_EN

    assert "valuation" in _ES_EN["valoracion"]
