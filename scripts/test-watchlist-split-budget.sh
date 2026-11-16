#!/bin/sh
set -eu
cd "$(dirname "$0")/../data-engine"
APP_ENV=test .venv/bin/pytest tests/test_watchlist*.py tests/test_dca*.py tests/test_split_after_price_date.py tests/test_derived_market_cap.py tests/test_r5_valor3_per_meses_completos.py tests/test_r5_datos_per_antiguedad.py tests/test_price_units_same_major_unit.py tests/test_per_company_minor_unit.py tests/test_reviewed_eps_integration.py tests/test_lse_paris_quote_currency.py tests/test_monitor_behavior_boundaries.py -p no:randomly --cov=app.api.routes.watchlist --cov-branch --cov-report=term-missing --cov-report=json:/tmp/watchlist-split-budget-coverage.json --cov-fail-under=85 -q -W ignore
