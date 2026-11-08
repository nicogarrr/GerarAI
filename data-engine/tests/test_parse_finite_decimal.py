"""parse_finite_decimal: un solo guardarraíl anti-NaN para decimales de máquina.

damodaran, esef_shares y yahoo_fundamentals_service llevaban copiado el mismo
helper local (_decimal/_dec: Decimal(str(...)) finito o None). Vive ahora en
number_parsing junto a parse_machine_decimal. Se fija su contrato y que los
tres caminos no reintroducen su copia.
"""

from decimal import Decimal
from pathlib import Path

from app.services.number_parsing import parse_finite_decimal


def test_valores_validos():
    assert parse_finite_decimal(2.5) == Decimal("2.5")
    assert parse_finite_decimal("1.5") == Decimal("1.5")
    assert parse_finite_decimal(0) == Decimal("0")
    assert parse_finite_decimal(Decimal("3.25")) == Decimal("3.25")


def test_sin_dato_es_none():
    assert parse_finite_decimal(None) is None
    assert parse_finite_decimal("") is None
    assert parse_finite_decimal("abc") is None
    assert parse_finite_decimal(True) is None


def test_nan_e_infinitos_se_rechazan():
    assert parse_finite_decimal("nan") is None
    assert parse_finite_decimal(float("nan")) is None
    assert parse_finite_decimal("Infinity") is None
    assert parse_finite_decimal("-Infinity") is None


def test_sin_copias_locales_en_los_tres_caminos():
    root = Path(__file__).resolve().parents[1]
    for rel, nombre in (
        ("app/services/connectors/damodaran.py", "_decimal"),
        ("app/services/esef_shares.py", "_dec"),
        ("app/services/yahoo_fundamentals_service.py", "_dec"),
    ):
        src = (root / rel).read_text(encoding="utf-8")
        assert "parse_finite_decimal(" in src, rel
        assert f"def {nombre}(" not in src, rel
        assert "is_finite()" not in src, rel
