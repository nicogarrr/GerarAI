from app.services.thesis_evidence_service import _sec_filing_title


def test_filing_title_with_date_is_es_es():
    assert _sec_filing_title("10-K", "2026-09-30") == "10-K presentado ante la SEC el 30 sept 2026"


def test_filing_title_without_date_never_says_none():
    for filed in (None, "", "no-es-fecha"):
        title = _sec_filing_title("8-K", filed)
        assert "None" not in title
        assert title == "8-K presentado ante la SEC"


def test_filing_title_without_form_is_still_spanish():
    assert _sec_filing_title(None, None) == "Documento presentado ante la SEC"
