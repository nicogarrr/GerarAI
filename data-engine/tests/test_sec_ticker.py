"""match_cik: exacto gana; clase US normalizada solo con match unico."""
from app.services.sec_ticker import match_cik, normalize_sec_ticker

TABLE = [
    ("BRK-B", "0001067983"),
    ("AAPL", "0000320193"),
    ("GOOG", "0001652044"),
    ("GOOGL", "0001652044"),
]


def test_exact_match_wins():
    assert match_cik(TABLE, "BRK-B") == "0001067983"
    assert match_cik(TABLE, "brk-b") == "0001067983"
    assert match_cik(TABLE, "AAPL") == "0000320193"


def test_dotted_class_resolves_to_sec_dash_notation():
    assert match_cik(TABLE, "BRK.B") == "0001067983"
    assert match_cik(TABLE, "brk.b") == "0001067983"


def test_ambiguous_normalized_match_fails_closed():
    # Dos CIK distintos con la misma forma normalizada: nunca se elige uno.
    table = [("AB-C", "0000000001"), ("AB.C", "0000000002")]
    assert match_cik(table, "ABC") is None


def test_same_cik_twice_is_not_ambiguous():
    # GOOG y GOOGL comparten CIK (Alphabet): un ticker que normalizara igual
    # no es ambiguo si el CIK es el mismo.
    table = [("XYZ-A", "0000000001"), ("XYZ.A", "0000000001")]
    assert match_cik(table, "XYZ.A") == "0000000001"


def test_unknown_ticker_is_none():
    assert match_cik(TABLE, "NOEXISTE") is None


def test_normalize_strips_all_separators():
    assert normalize_sec_ticker("BRK.B") == "BRKB"
    assert normalize_sec_ticker("BRK-B") == "BRKB"
    assert normalize_sec_ticker("BRK/B") == "BRKB"
    assert normalize_sec_ticker("SAN.MC") == "SANMC"
