"""Nota del CAGR de ingresos de la proyección: «1 año» en singular."""

from decimal import Decimal

from app.models import FinancialFact
from app.services.thesis_projection_service import ThesisProjectionService


def _fact(value: float, year: int) -> FinancialFact:
    return FinancialFact(
        id=year, company_id=1, metric="revenue", value=Decimal(str(value)),
        period=f"FY{year}", fiscal_year=year, fiscal_quarter="FY", confidence=Decimal("0.9"),
    )


def test_two_fiscal_years_say_one_year_singular():
    out = ThesisProjectionService._revenue_cagr({2023: _fact(100, 2023), 2024: _fact(110, 2024)})
    assert out.base == (
        "CAGR de ingresos FY2023-FY2024 sobre facts anuales (1 año); la historia no garantiza el futuro"
    )


def test_longer_history_keeps_plural():
    out = ThesisProjectionService._revenue_cagr({2021: _fact(100, 2021), 2024: _fact(130, 2024)})
    assert out.base is not None and "(3 años);" in out.base
