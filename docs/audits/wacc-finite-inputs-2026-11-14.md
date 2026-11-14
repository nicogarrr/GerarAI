# WACC finite numeric input boundary

Base: c7f56d9. Controlled fixture reproduction, not a confirmed production incident.

WaccInputService._decimal accepted Decimal NaN and infinities. Yahoo beta or marketCap NaN raised InvalidOperation at its positive-value comparison. Positive infinity passed that comparison. A FRED NaN refresh failed on SQLite persistence (NOT NULL), while infinity was not rejected at the numeric boundary.

Change: the shared numeric parser returns None for all non-finite Decimal results. FRED then leaves the risk-free input absent and creates no FRED source document; Yahoo drops only the invalid field, retaining the other valid field. Finite zero/negative values retain existing consumer-specific handling. No database migration, deletion, network request, fallback observation selection or economic-bound change.

Red first: 13 failing cases among 15 new cases. Negative infinity Yahoo cases already passed the positive filter. Cases cover string NaN/sNaN/infinities, float nan/inf, SQLite refresh integration and actual Yahoo parsing with a stubbed yfinance module.

Green command (from data-engine):
PYTHONPATH=. pytest tests/test_wacc_input_service.py tests/test_damodaran_erp.py tests/test_fred_connector_series.py -q --cov=app.services.wacc_input_service --cov-branch --cov-report=term-missing --cov-fail-under=85

54 tests pass, module coverage including branches 96.34%. Ruff scoped checks and git diff --check pass. This is a scoped suite, not a full backend or production validation. Previously delivered FRED series-identity and WACC observation-date patches remain separate and frozen; this patch does not include or rebase them.
