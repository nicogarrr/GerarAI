from app.services.financial_ingestion_service import _annual_fiscal_year


def test_52_53_week_year_closing_in_first_week_of_january_belongs_to_previous_year():
    # EXEL: 2025-01-03 es el FY2024 y 2026-01-02 el FY2025.
    assert _annual_fiscal_year("2025-01-03", "12") == 2024
    assert _annual_fiscal_year("2026-01-02", "12") == 2025
    assert _annual_fiscal_year("2025-01-03", None) == 2024


def test_regular_year_ends_keep_the_end_year():
    assert _annual_fiscal_year("2023-12-29", "12") == 2023
    assert _annual_fiscal_year("2024-12-31", "12") == 2024
    assert _annual_fiscal_year("2025-06-30", "6") == 2025
    # Cierres de enero tardios (retail/NVDA) no se tocan.
    assert _annual_fiscal_year("2025-01-26", "1") == 2025
    # Cierre de enero temprano pero ejercicio con otro mes modal: no se mueve.
    assert _annual_fiscal_year("2025-01-03", "6") == 2025


def test_esef_annual_rows_use_the_same_fiscal_year_rule():
    import inspect

    from app.services import financial_ingestion_service as svc

    source = inspect.getsource(svc)
    assert "fiscal_year=int(period_date[:4])" not in source
    assert "fiscal_year=_annual_fiscal_year(period_date, None)" in source
