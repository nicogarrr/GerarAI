"""Rutas /api/health: ramas de fallo y sonda de fuentes externas.

Sobre main (68.9% con los tests existentes) faltaban: el fallback
'main-unknown' cuando git no responde, la rama de error de
_scheduler_status (endpoint publico: solo el tipo de excepcion, nunca el
texto con rutas del host), el 'error:<Clase>' de la sonda de BD y el
handler /health/data-sources (cuota Alpha Vantage y frenos de proveedor
fail-open). Todo con dobles: sin red, sin subprocess real, sin APScheduler.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.api.routes import health as mod


def test_git_version_git_caido_es_main_unknown(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    mod._git_version.cache_clear()
    try:
        def _boom(*args, **kwargs):
            raise FileNotFoundError("sin git en la imagen")

        monkeypatch.setattr(mod.subprocess, "run", _boom)
        assert mod._git_version() == "main-unknown"
    finally:
        mod._git_version.cache_clear()


def test_scheduler_status_error_reporta_solo_el_tipo(monkeypatch):
    class ErrorConRuta(Exception):
        pass

    monkeypatch.setattr(
        mod, "get_settings", lambda: SimpleNamespace(workers_enabled=True)
    )

    def _boom():
        raise ErrorConRuta("/home/host/secreto/config.py")

    monkeypatch.setattr(mod, "_scheduler_job_count", _boom)
    status = mod._scheduler_status()
    assert status["enabled"] is True
    assert status["running"] is False
    assert status["jobs"] == 0
    # Endpoint publico: el tipo de excepcion, nunca el texto (puede traer
    # rutas del host).
    assert status["error"] == "ErrorConRuta"
    assert "/home" not in str(status)


def test_probe_database_error_es_clase_de_excepcion(monkeypatch):
    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mod, "SessionLocal", _boom)
    assert mod._probe_database() == "error:RuntimeError"


class _FakeRegistry:
    def summary(self):
        return {
            "sources": [
                {"name": "Alpha Vantage", "status": "ok"},
                {"name": "SEC", "status": "ok"},
            ]
        }


def test_data_sources_health_inyecta_cuota_y_frenos_fail_open(monkeypatch):
    monkeypatch.setattr(mod, "get_data_source_registry", _FakeRegistry)
    monkeypatch.setattr(
        mod,
        "get_alpha_vantage_client",
        lambda: SimpleNamespace(quota_status=lambda: {"remaining": 25}),
    )
    out = mod.data_sources_health()
    alpha = next(s for s in out["sources"] if s["name"] == "Alpha Vantage")
    assert alpha["quota"] == {"remaining": 25}
    # La cuota solo se inyecta en Alpha Vantage.
    sec = next(s for s in out["sources"] if s["name"] == "SEC")
    assert "quota" not in sec
    # Sin Redis real los frenos no tumban el health: lista vacia.
    assert out["provider_brakes"] == []
