"""Divisa del dividendo de Yahoo/FMP: solo codigos reales (ISO 4217 o subunidad).

``_known_currency`` pasaba a mayusculas cualquier texto del proveedor: «NaN»,
«N/A» o «None» se guardaban como divisa del registro (``NAN``) y ningun tipo
de cambio sabria convertirlos; el dividendo quedaba fuera de la proyeccion sin
avisar. Ahora un codigo que no es ISO ni subunidad cuenta como «sin divisa»
(el registro no se ingiere y la sincronizacion lo declara ``currency_unknown``),
y las subunidades de cotizacion conservan su sentido (peniques no son libras).
"""

import pytest

from app.services.dividend_ingestion_service import DividendIngestionService

known = DividendIngestionService._known_currency


@pytest.mark.parametrize("raw", ["NaN", "nan", "N/A", "None", "XYZ", "QQQ", "-", "0", "EURO", "US$"])
def test_codigo_inventado_cuenta_como_sin_divisa(raw):
    assert known(raw) is None


def test_codigo_inventado_deja_paso_al_siguiente_candidato():
    assert known("NaN", "chf") == "CHF"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("usd", "USD"), (" EUR ", "EUR"), ("CNH", "CNH"),
        ("GBp", "GBX"), ("GBX", "GBX"), ("GBP", "GBP"),
        ("ZAc", "ZAC"), ("ILa", "ILA"),
    ],
)
def test_divisas_reales_y_subunidades_se_conservan(raw, expected):
    assert known(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_vacio_sigue_siendo_sin_divisa(raw):
    assert known(raw) is None
