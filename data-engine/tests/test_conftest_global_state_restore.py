"""Harness de las fixtures de estado global del conftest (gemelas de #5121).

Con sentinels NO vacios en los dicts originales, cada fixture debe ofrecer
al test dicts limpios y restaurar al terminar el contenido original
exactamente como estaba (snapshot + restauracion, nunca un clear() pelado
que destruya el estado previo de la sesion). Mismo patron que
tests/test_conftest_failed_until_restore.py.
"""

import pytest

from app.llm import base as llm_base
from app.services import company_events_service, historical_stress_service
from tests import conftest


def _comprueba_snapshot_y_restaura(gen_factory, dics):
    """dics: lista de dicts de estado global ya sembrados con sentinels."""
    snapshots = [dict(d) for d in dics]
    gen = gen_factory()
    next(gen)  # setup: snapshots internos + clear
    assert all(d == {} for d in dics)
    for d in dics:
        d["sucio"] = 1.0  # un test puede dejar basura
    with pytest.raises(StopIteration):
        next(gen)  # teardown: clear + restauracion
    assert all(snapshot == d for snapshot, d in zip(snapshots, dics, strict=True))


def test_fixture_company_filings_sec_down_restaura_con_sentinel():
    original = company_events_service._FAILED_UNTIL
    original["sentinela"] = 123.0
    try:
        _comprueba_snapshot_y_restaura(conftest._reset_company_filings_sec_down.__wrapped__, [original])
        assert company_events_service._FAILED_UNTIL is original
    finally:
        company_events_service._FAILED_UNTIL.clear()


def test_fixture_historical_stress_restaura_con_sentinel():
    original = historical_stress_service._FAILED_UNTIL
    original["sentinela"] = 123.0
    try:
        _comprueba_snapshot_y_restaura(
            conftest._reset_historical_stress_failure_cache.__wrapped__, [original]
        )
        assert historical_stress_service._FAILED_UNTIL is original
    finally:
        historical_stress_service._FAILED_UNTIL.clear()


def test_fixture_llm_breakers_restaura_con_sentinels():
    estados = [getattr(llm_base, name) for name in conftest._BREAKER_STATES]
    originales = list(estados)
    for i, d in enumerate(estados):
        d[("sentinela", str(i))] = float(i)
    try:
        _comprueba_snapshot_y_restaura(conftest.isolate_llm_free_tier_breaker.__wrapped__, estados)
        assert all(
            getattr(llm_base, name) is o for name, o in zip(conftest._BREAKER_STATES, originales, strict=True)
        )
    finally:
        for d in originales:
            d.clear()
