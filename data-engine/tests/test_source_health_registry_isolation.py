"""Aislamiento del registry de salud de fuentes entre tests.

El registry (``get_data_source_registry``) es un singleton de proceso. Antes,
los fallos que registraba un test (o un circuito abierto) los heredaba el
siguiente test del mismo worker de xdist, y
test_source_health_wiring.py::test_yahoo_ticker_desconocido_no_degrada_la_fuente
fallaba o pasaba según el orden. Estos dos tests van en orden: el primero deja
el registry sucio a propósito y el segundo exige partir de uno limpio.
"""

from __future__ import annotations

from app.services.data_source_health import CircuitState, get_data_source_registry


def test_1_un_test_deja_fuentes_con_fallos_y_circuito_abierto():
    registry = get_data_source_registry()
    for _ in range(registry.get_status("yahoo_finance").failure_threshold):
        registry.record_failure("yahoo_finance", "fallo de prueba que no se limpia")
    registry.record_failure("nasdaq", "fallo de prueba que no se limpia")

    assert registry.get_status("yahoo_finance").state == CircuitState.OPEN


def test_2_el_siguiente_test_parte_de_un_registry_limpio():
    registry = get_data_source_registry()

    sucias = {
        key: (status.consecutive_failures, status.state.value)
        for key, status in registry.sources.items()
        if status.consecutive_failures or status.state != CircuitState.CLOSED
    }
    assert sucias == {}
    assert registry.get_status("yahoo_finance").can_attempt()
