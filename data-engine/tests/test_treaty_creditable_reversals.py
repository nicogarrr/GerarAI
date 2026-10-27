"""Regresión: reversiones de retención en la deducción 0588.

Antes del fix, una reversión posterior imputada por fecha a un dividendo
distinto del suyo evaporaba el negativo sobrante (clamp max(., 0)) y la
deducción salía inflada: con retenido neto 10 se acreditaban 15.
"""
from decimal import Decimal

from app.services.tax_irpf_filing import _treaty_creditable, build_double_taxation

C = Decimal


def _bucket(pairs):
    return {
        "ticker": "X",
        "missing_fx": False,
        "ambiguous_cash": False,
        "dividends_base": C("200"),
        "withholding_base": C("10"),
        "payments": [
            {"type": kind, "date": day, "amount_base": amount}
            for kind, day, amount in pairs
        ],
    }


_REVERSAL_PAIRS = [
    ("dividend", "2025-03-10", C("100")),
    ("withholding", "2025-03-10", C("30")),
    ("dividend", "2025-06-10", C("100")),
    ("withholding", "2025-06-10", C("5")),
    ("withholding", "2025-07-01", C("-25")),  # reversión del exceso de marzo
]


def test_reversal_never_exceeds_net_withheld():
    """Lo acreditable no puede superar lo efectivamente retenido (neto)."""
    result = _treaty_creditable(_bucket(_REVERSAL_PAIRS), C("200"), C("10"), C("0.15"))
    assert result <= C("10")


def test_single_dividend_reversal_still_computes():
    """Con un único dividendo la atribución de la reversión es inequívoca:
    se netea y se aplica el tope de convenio sobre el resultado."""
    pairs = [
        ("dividend", "2025-03-10", C("100")),
        ("withholding", "2025-03-10", C("30")),
        ("withholding", "2025-04-01", C("-20")),
    ]
    result = _treaty_creditable(_bucket(pairs), C("100"), C("10"), C("0.15"))
    assert result == C("10")


def test_double_taxation_flags_ambiguous_reversal_for_manual_review():
    """Reversión + varios dividendos: el bloque va a revisión manual y no
    entra en el total de la deducción (partial), nunca una cifra inventada."""
    out = build_double_taxation(
        [_bucket(_REVERSAL_PAIRS)], {"X": "US"}, 2025, tme=C("0.20")
    )
    assert any(item["ticker"] == "X" for item in out["manual_review"])
    assert out["countries"] == []
    assert out["total_deduction_base"] is None
    assert out["partial"] is True


def test_double_taxation_clean_bucket_unaffected():
    """Sin reversión todo sigue igual: tope por dividendo y total publicado."""
    pairs = [
        ("dividend", "2025-03-10", C("100")),
        ("withholding", "2025-03-10", C("30")),
        ("dividend", "2025-06-10", C("100")),
        ("withholding", "2025-06-10", C("15")),
    ]
    bucket = _bucket(pairs)
    bucket["dividends_base"] = C("200")
    bucket["withholding_base"] = C("45")
    out = build_double_taxation([bucket], {"X": "US"}, 2025, tme=C("0.20"))
    assert out["manual_review"] == []
    assert out["countries"][0]["treaty_cap_base"] == 30.0  # min(30,15)+min(15,15)
    assert out["total_deduction_base"] == 30.0
