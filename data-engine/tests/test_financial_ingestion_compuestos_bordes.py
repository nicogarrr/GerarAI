"""Bordes de financial_ingestion_service.py (lote A2): compuestos y guards.

Helpers sincronos por via directa (precedente aceptado: sec_helpers,
sec_xbrl_instance, fi_helpers A1), datos sinteticos, sin DB/red/reloj/estado
global. Nombres de concepto LITERALES (independientes de las constantes del
modulo, observacion del auditor en A1). Esperados construidos como literales,
no reutilizando el dict de entrada.

DECLARADAS inalcanzables hoy (con fuzz ejecutable en el propio test):
- 1742 (end con len < 7) y 1744->1728 (mes normalizado None) de
  _fiscal_annual_pairs: el calculo del span (1734-1737) ya exige
  date.fromisoformat(end) valido; el fuzz prueba que ninguna cadena de
  digitos de 4-6 chars parsea (y que toda fecha valida tiene mes). Si una
  version futura de Python acepta cadenas mas cortas, el test revienta y
  la guarda vuelve a ser alcanzable.
"""

from __future__ import annotations

import itertools
from datetime import date

import pytest

from app.services import financial_ingestion_service as fis

# --- _compose_bank_revenue (1107, 1111) ---


def test_compose_bank_revenue_exige_ambos_componentes_y_valores():
    """1107: periodo sin NoninterestIncome no compone (fail closed, nunca se
    imputa a cero). 1111: componente con val no decimal tampoco. Compone solo
    el periodo con ambos valores, suma exacta y concepto compuesto literal."""
    us_gaap = {
        "InterestIncomeExpenseNet": {
            "units": {
                "USD": [
                    {  # sin pareja Noninterest -> 1107
                        "form": "10-K",
                        "fp": "FY",
                        "start": "2022-01-01",
                        "end": "2022-12-31",
                        "filed": "2023-03-01",
                        "accn": "0000320193-23-000010",
                        "val": 7,
                    },
                    {  # pareja presente pero val no decimal -> 1111
                        "form": "10-K",
                        "fp": "FY",
                        "start": "2025-01-01",
                        "end": "2025-12-31",
                        "filed": "2026-03-01",
                        "accn": "0000320193-26-000010",
                        "val": "no-numero",
                    },
                    {  # compone
                        "form": "10-K",
                        "fp": "FY",
                        "start": "2023-01-01",
                        "end": "2023-12-31",
                        "filed": "2024-03-01",
                        "accn": "0000320193-24-000010",
                        "val": 8,
                    },
                ]
            }
        },
        "NoninterestIncome": {
            "units": {
                "USD": [
                    {
                        "form": "10-K",
                        "fp": "FY",
                        "start": "2025-01-01",
                        "end": "2025-12-31",
                        "filed": "2026-03-01",
                        "accn": "0000320193-26-000010",
                        "val": 5,
                    },
                    {
                        "form": "10-K",
                        "fp": "FY",
                        "start": "2023-01-01",
                        "end": "2023-12-31",
                        "filed": "2024-03-01",
                        "accn": "0000320193-24-000010",
                        "val": 4,
                    },
                ]
            }
        },
    }
    resultado = fis._compose_bank_revenue(us_gaap, forms={"10-K"}, periods={"FY"}, min_span=300, max_span=380)
    assert resultado == {
        "2023-12-31": {
            "form": "10-K",
            "fp": "FY",
            "start": "2023-01-01",
            "end": "2023-12-31",
            "filed": "2024-03-01",
            "accn": "0000320193-24-000010",
            "val": 12.0,
            "_concept": "InterestIncomeExpenseNet+NoninterestIncome",
        }
    }


# --- _merge_esef_periods (1446, 1453) ---


def test_merge_esef_periods_instante_desplazado_duplicado_se_salta():
    """1446: dos instantes de apertura del MISMO concepto que mapean al mismo
    cierre: el segundo se descarta (gana el primero)."""
    primera = {"instant": "2023-01-01", "val": 50}
    segunda = {"instant": "2023-01-01", "val": 70}
    facts_data = {
        "ifrs-full:Revenue": {"ifrs-full:EUR": [{"start": "2022-01-01", "end": "2022-12-31", "val": 1}]},
        "ifrs-full:CashAndCashEquivalents": {"ifrs-full:EUR": [primera, segunda]},
    }
    by_period, coverage = fis._merge_esef_periods(
        facts_data,
        ["ifrs-full:CashAndCashEquivalents"],
        "ifrs-full:EUR",
        "total_debt",
    )
    assert by_period == {"2022-12-31": {"instant": "2023-01-01", "val": 50}}
    assert coverage == {"ambiguous": {}, "partial": {}}


def test_merge_esef_periods_parte_con_valor_no_decimal_se_salta():
    """1453: una parte con val no decimal no entra en la suma; el periodo con
    ambas partes validas suma exacto con componentes declarados."""
    parte_ppe = "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
    parte_int = "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"
    facts_data = {
        parte_ppe: {
            "ifrs-full:EUR": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": "no-numero"},
                {"start": "2025-01-01", "end": "2025-12-31", "val": 100},
            ]
        },
        parte_int: {"ifrs-full:EUR": [{"start": "2025-01-01", "end": "2025-12-31", "val": 50}]},
    }
    by_period, coverage = fis._merge_esef_periods(
        facts_data,
        [parte_ppe, parte_int],
        "ifrs-full:EUR",
        "capital_expenditure",
    )
    assert by_period == {
        "2025-12-31": {
            "val": 150.0,
            "period": "2025-12-31",
            "_components": {parte_ppe: "100", parte_int: "50"},
        }
    }
    assert coverage == {"ambiguous": {}, "partial": {}}


# --- _fiscal_annual_pairs (1742, 1744->1728 declaradas con fuzz) ---


def test_fiscal_annual_pairs_guards_1742_y_1744_son_defensa_muerta_hoy():
    """1742 y 1744->1728 son inalcanzables con el fromisoformat actual.

    El calculo del span (1734-1737) ya exige date.fromisoformat(end) valido
    antes de llegar a 1740-1744. Fuzz: ninguna cadena de digitos de 4-6
    caracteres parsea (1.110.000 candidatos), asi que un end valido siempre
    tiene len >= 7 (1742 no puede disparar); y _normalized_fiscal_month solo
    devuelve None cuando fromisoformat falla, imposible ahi (1744->1728).
    Si una version futura de Python relaja fromisoformat, este test revienta
    y las guards vuelven a ser alcanzables.
    """
    for n in (4, 5, 6):
        for tup in itertools.product("0123456789", repeat=n):
            candidata = "".join(tup)
            try:
                date.fromisoformat(candidata)
            except ValueError:
                continue
            pytest.fail(f"{candidata!r} parsea con len < 7: revisar guard 1742")
    for candidata in ("2025-1", "2025-W1", "2025W1", "202501"):
        try:
            date.fromisoformat(candidata)
        except ValueError:
            continue
        pytest.fail(f"{candidata!r} parsea con len < 7: revisar guard 1742")
    # Toda fecha valida tiene mes normalizado (guard 1744->1728 sin camino).
    assert fis._normalized_fiscal_month("2025-12-31") is not None


# --- _sec_reporting_currency: competencia entre divisas (refuerzo A1) ---


def test_sec_reporting_currency_competencia_y_empate():
    """Gana la divisa con mas observaciones; empate -> desconocida (None)."""
    us_gaap_cny = {
        "Assets": {
            "units": {
                "USD": [{"end": "2025-12-31"}],
                "CNY": [{"end": "2025-12-31"}, {"end": "2024-12-31"}],
            }
        }
    }
    assert fis._sec_reporting_currency(us_gaap_cny) == "CNY"
    us_gaap_empate = {
        "Assets": {
            "units": {
                "USD": [{"end": "2025-12-31"}],
                "CNY": [{"end": "2025-12-31"}],
            }
        }
    }
    assert fis._sec_reporting_currency(us_gaap_empate) is None
