from app.services.text_clip import clip_words


def test_short_text_is_unchanged() -> None:
    assert clip_words("hola mundo", 20) == "hola mundo"


def test_cuts_on_whole_word_with_ellipsis() -> None:
    assert clip_words("uno dos tres cuatro", 10) == "uno dos…"


def test_complete_last_word_is_kept() -> None:
    assert clip_words("uno dos tres cuatro", 7) == "uno dos…"


def test_single_giant_word_cuts_at_limit() -> None:
    assert clip_words("abcdefghij", 5) == "abcde…"
