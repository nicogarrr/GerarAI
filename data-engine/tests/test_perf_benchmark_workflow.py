"""The opt-in timing signal stays separate from blocking quality checks."""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/backend-perf-benchmark.yml'


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def test_benchmark_is_manual_read_only_serial_and_non_blocking():
    workflow = _workflow()
    events = workflow.get('on', workflow.get(True))
    assert set(events) == {'workflow_dispatch'}
    assert workflow['permissions'] == {'contents': 'read'}
    job = workflow['jobs']['benchmark']
    assert job['continue-on-error'] is True
    assert job['timeout-minutes'] <= 20
    assert 'strategy' not in job and 'needs' not in job
    assert job['env']['PERF_GUARD_ENFORCE_WALL_TIME'] == '1'
    assert job['env']['WORKERS_ENABLED'] == 'false'


def test_failed_benchmark_still_uploads_log_junit_and_environment():
    steps = _workflow()['jobs']['benchmark']['steps']
    benchmark = next(step for step in steps if step.get('id') == 'measure')
    command = benchmark['run']
    assert 'set -o pipefail' in command
    assert 'test_perf_guard_query_budgets.py' in command
    assert '-o addopts=' in command and '-o junit_family=legacy' in command
    assert '--junitxml=' in command and 'tee ' in command
    assert '-n ' not in command and '--cov' not in command
    upload = next(step for step in steps if 'actions/upload-artifact@' in step.get('uses', ''))
    assert upload['if'] == 'always()'
    assert upload['with']['if-no-files-found'] == 'error'
    assert 'perf-benchmark/' in upload['with']['path']
    environment = next(step for step in steps if step.get('id') == 'environment')
    assert 'lscpu' in environment['run'] and 'free -m' in environment['run']
    assert 'GITHUB_SHA' in environment['run']
    summary = next(step for step in steps if step.get('name') == 'Benchmark summary')
    assert summary['if'] == 'always()'
    assert 'steps.measure.outcome' in summary['env']['MEASUREMENT_OUTCOME']
