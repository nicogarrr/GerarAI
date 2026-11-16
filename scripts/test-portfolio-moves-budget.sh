#!/bin/sh
set -eu
cd "$(dirname "$0")/../data-engine"
APP_ENV=test .venv/bin/pytest tests/test_portfolio_moves*.py -p no:randomly -q -s --cov=app.services.portfolio_moves_service --cov-branch --cov-report=term-missing --cov-report=json:/tmp/moves-coverage.json
.venv/bin/python - <<'PY'
import json
for path, source in json.load(open('/tmp/moves-coverage.json'))['files'].items():
    s = source['summary']
    assert s['covered_lines'] / s['num_statements'] >= .85, path
    assert s['covered_branches'] / s['num_branches'] >= .85, path
PY
