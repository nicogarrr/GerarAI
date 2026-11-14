"""Regression guard semantics, independent of elapsed runner wall time."""
import pytest

from tests import test_perf_guard_query_budgets as guard


def test_shared_runner_delay_is_telemetry_not_a_query_regression():
    properties = []
    guard._check_wall_time('/delayed', {'warm_s': 2.75, 'cold_s': 12.0},
                           lambda key, value: properties.append((key, value)), enforce=False)
    assert properties == [('perf.warm_s', 2.75), ('perf.cold_s', 12.0)]


def test_controlled_benchmark_keeps_existing_wall_limits():
    with pytest.raises(AssertionError, match='caliente'):
        guard._check_wall_time('/cpu-or-io', {'warm_s': 2.75, 'cold_s': 1.0},
                               lambda *_: None, enforce=True)
    with pytest.raises(AssertionError, match='frío'):
        guard._check_wall_time('/cold', {'warm_s': 0.1, 'cold_s': 10.1},
                               lambda *_: None, enforce=True)
    guard._check_wall_time('/ok', {'warm_s': 0.1, 'cold_s': 1.0}, lambda *_: None, enforce=True)


def test_warm_sql_regression_fails_even_with_fast_clock():
    with pytest.raises(AssertionError, match='caliente'):
        guard._check_warm_queries('/fast-n-plus-one', ['SELECT 1'] * 20, budget=7)
    guard._check_warm_queries('/ok', ['SELECT 1'] * 7, budget=7)


def test_default_policy_records_delays_but_still_checks_warm_queries(monkeypatch):
    path = '/api/risk/dashboard'
    run = {'warm_s': 2.75, 'cold_s': 12.0, 'stmts_warm': ['SELECT 1'] * guard.BUDGETS[path]}
    properties = []
    monkeypatch.delenv('PERF_GUARD_ENFORCE_WALL_TIME', raising=False)
    guard.test_presupuesto_caliente_y_telemetria({path: run}, path,
        lambda key, value: properties.append((key, value)))
    assert properties == [('perf.warm_s', 2.75), ('perf.cold_s', 12.0)]
    run['stmts_warm'] *= 10
    with pytest.raises(AssertionError, match='consultas en caliente'):
        guard.test_presupuesto_caliente_y_telemetria({path: run}, path, lambda *_: None)


def test_wall_enforcement_is_explicitly_opt_in(monkeypatch):
    path = '/api/risk/dashboard'
    run = {'warm_s': 2.75, 'cold_s': 0.1, 'stmts_warm': []}
    monkeypatch.setenv('PERF_GUARD_ENFORCE_WALL_TIME', '1')
    with pytest.raises(AssertionError, match='caliente'):
        guard.test_presupuesto_caliente_y_telemetria({path: run}, path, lambda *_: None)
