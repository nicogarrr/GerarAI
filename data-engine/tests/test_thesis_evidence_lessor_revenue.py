"""Atajo de evidencia de la tesis con ingresos de arrendador (ASC 842).

Caso real (CPT, medido por el Piloto en prod): la tesis marcaba «respaldada /
1 prueba: ingresos 12,97 MUSD» para FY2025 porque el atajo solo leia
RevenueFromContractWithCustomerExcludingAssessedTax (partida residual de
Camden), mientras la vista de finanzas mostraba 1.573,5 MUSD del
OperatingLeaseLeaseIncome del MISMO 10-K. Regla de la ingesta completa
(_revenue_with_lessor_income): en la misma presentacion (mismo periodo y
mismo accn) gana el mayor; presentaciones distintas no se mezclan.

Cifras de SEC companyfacts de Camden Property Trust, 10-K FY2025, USD.
"""

from app.services.thesis_evidence_service import ThesisEvidenceService

REVENUE_RESIDUAL_FY2025 = 12_970_000  # RevenueFromContractWithCustomerExcludingAssessedTax
LEASE_INCOME_FY2025 = 1_573_500_000  # OperatingLeaseLeaseIncome
ACCN_10K = "0000906345-26-000001"


def _e(val, end, accn, start=None, form="10-K", filed="2026-02-06"):
    entry = {"form": form, "val": val, "end": end, "fy": 2025, "fp": "FY", "filed": filed, "accn": accn}
    if start:
        entry["start"] = start
    return entry


CPT_US_GAAP = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
        _e(REVENUE_RESIDUAL_FY2025, "2025-12-31", ACCN_10K, start="2025-01-01"),
    ]}},
    "OperatingLeaseLeaseIncome": {"units": {"USD": [
        _e(LEASE_INCOME_FY2025, "2025-12-31", ACCN_10K, start="2025-01-01"),
    ]}},
}


def test_misma_presentacion_gana_el_ingreso_de_arrendador():
    """Sin la regla el atajo coronaba la partida residual (12,97 M)."""
    extracted = ThesisEvidenceService()._extract_recent_annuals(CPT_US_GAAP)
    revenue = extracted["revenue"]
    assert revenue[0]["value"] == LEASE_INCOME_FY2025
    assert revenue[0]["concept"] == "OperatingLeaseLeaseIncome"
    assert revenue[0]["period"] == "2025-12-31:FY"


def test_presentaciones_distintas_no_se_mezclan():
    """Arrendador en OTRO accn (otra presentacion) no desplaza al contractual:
    el maximo solo vale dentro del mismo filing."""
    us_gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _e(REVENUE_RESIDUAL_FY2025, "2025-12-31", ACCN_10K, start="2025-01-01"),
        ]}},
        "OperatingLeaseLeaseIncome": {"units": {"USD": [
            _e(LEASE_INCOME_FY2025, "2025-12-31", "0000906345-25-000099", start="2025-01-01"),
        ]}},
    }
    extracted = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    revenue = extracted["revenue"]
    assert revenue[0]["value"] == REVENUE_RESIDUAL_FY2025
    assert revenue[0]["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_emisor_solo_con_tag_arrendador_si_lo_usa():
    """Un REIT que solo etiqueta OperatingLeaseLeaseIncome no se queda sin
    revenue: el tag esta en el pool (ultima preferencia)."""
    us_gaap = {
        "OperatingLeaseLeaseIncome": {"units": {"USD": [
            _e(LEASE_INCOME_FY2025, "2025-12-31", ACCN_10K, start="2025-01-01"),
        ]}},
    }
    extracted = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    assert extracted["revenue"][0]["value"] == LEASE_INCOME_FY2025


def test_emisor_sin_tags_arrendador_no_cambia():
    """Empresa normal: el contractual sigue mandando como antes."""
    us_gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _e(70_918_000_000, "2025-12-31", ACCN_10K, start="2025-01-01"),
        ]}},
    }
    extracted = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    assert extracted["revenue"][0]["value"] == 70_918_000_000


def test_arrendador_menor_que_contractual_no_desplaza():
    """Si la partida contractual es la mayor de la presentacion, se queda."""
    us_gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _e(2_000_000_000, "2025-12-31", ACCN_10K, start="2025-01-01"),
        ]}},
        "OperatingLeaseLeaseIncome": {"units": {"USD": [
            _e(300_000_000, "2025-12-31", ACCN_10K, start="2025-01-01"),
        ]}},
    }
    extracted = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    assert extracted["revenue"][0]["value"] == 2_000_000_000
    assert extracted["revenue"][0]["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
