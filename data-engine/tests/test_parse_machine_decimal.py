"""parse_machine_decimal: el helper unico para valores numericos de maquina.

Contrato (antes copiado a mano en edgartools_facts, financial_ingestion_service
y thesis_evidence_service): None, "" o texto no numerico es "sin dato" (None,
nunca 0); numeros y strings con punto decimal de maquina pasan por Decimal.
"""

from decimal import Decimal

from app.services import financial_ingestion_service, thesis_evidence_service
from app.services.connectors import edgartools_facts
from app.services.number_parsing import parse_machine_decimal


def test_none_vacio_e_invalido_devuelven_none():
    assert parse_machine_decimal(None) is None
    assert parse_machine_decimal("") is None
    assert parse_machine_decimal("no numerico") is None


def test_numeros_y_strings_de_maquina():
    assert parse_machine_decimal("12.5") == Decimal("12.5")
    assert parse_machine_decimal(7) == Decimal("7")
    assert parse_machine_decimal("-0,5") is None  # coma de maquina no existe


def test_los_tres_modulos_usan_el_mismo_helper():
    assert edgartools_facts._decimal is parse_machine_decimal
    assert financial_ingestion_service._decimal is parse_machine_decimal
    assert thesis_evidence_service._decimal is parse_machine_decimal
