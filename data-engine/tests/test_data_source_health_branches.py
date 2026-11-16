"""Ramas del registro de salud: estados, claves desconocidas y resumen."""

from __future__ import annotations

from app.services.data_source_health import (
    CircuitState,
    DataSourceHealthRegistry,
    DataSourceStatus,
    get_data_source_registry,
)


def test_as_dict_estados_degraded_y_failing():
    base = DataSourceStatus(name="x", is_primary=False)
    base.last_checked_at = "2026-11-17T00:00:00+00:00"
    base.state = CircuitState.HALF_OPEN
    assert base.as_dict()["status"] == "degraded"
    base.state = CircuitState.OPEN
    assert base.as_dict()["status"] == "failing"
    never = DataSourceStatus(name="y", is_primary=False)
    assert never.as_dict()["status"] == "unknown"


def test_singleton_devuelve_la_misma_instancia():
    assert DataSourceHealthRegistry() is DataSourceHealthRegistry()


def test_clave_desconocida_no_revienta_ni_registra():
    registry = get_data_source_registry()
    # get_status devuelve un estado sintetico; record_* son no-op.
    status = registry.get_status("fuente_inexistente")
    assert status.name == "fuente_inexistente" and status.is_primary is False
    registry.record_success("fuente_inexistente", 1.0)
    registry.record_failure("fuente_inexistente", "x")
    assert "fuente_inexistente" not in registry.sources


def test_summary_desconocido_si_ninguna_fuente_sondeada():
    registry = get_data_source_registry()
    guardado = {k: s.last_checked_at for k, s in registry.sources.items()}
    try:
        for source in registry.sources.values():
            source.last_checked_at = None
        assert registry.summary()["overall_status"] == "unknown"
    finally:
        for key, value in guardado.items():
            registry.sources[key].last_checked_at = value
