"""Rutas de AST (satelites) y flujos de dinero: paso al servicio y 404 limpio.

Los servicios se sustituyen por dobles y las funciones de la ruta se llaman
directamente: se prueba solo el mapeo funcion -> resultado (cada endpoint
devuelve lo de su servicio; un tema de flujo no configurado es 404, nunca un
500). El analisis LLM de AST va doblado: no se prueba el LLM real, ni la
capa HTTP ni la auth del despliegue.
"""

from __future__ import annotations

from unittest.mock import ANY, Mock

import pytest
from fastapi import HTTPException

from app.api.routes import asts as asts_routes
from app.api.routes import money_flows as flows_routes


class TestAsts:
    def test_catalogo_devuelve_lo_del_servicio(self, monkeypatch):
        monkeypatch.setattr(asts_routes, "read_catalog", lambda db: {"sats": 3})
        assert asts_routes.ast_satellites(db=object()) == {"sats": 3}

    def test_analisis_llm_devuelve_lo_del_servicio(self, monkeypatch):
        monkeypatch.setattr(
            asts_routes, "analyze_asts_catalog", lambda db: {"analysis": "ok"}
        )
        assert asts_routes.ast_llm_analysis(db=object()) == {"analysis": "ok"}

    def test_orbita_devuelve_el_historial_de_ese_norad(self, monkeypatch):
        historial = Mock(return_value={"points": []})
        monkeypatch.setattr(asts_routes, "read_orbit_history", historial)
        assert asts_routes.ast_satellite_orbit(norad_cat_id=25544, db=object()) == {"points": []}
        historial.assert_called_once_with(ANY, 25544)

    def test_resumen_orbitas_devuelve_lo_del_servicio(self, monkeypatch):
        monkeypatch.setattr(asts_routes, "read_orbit_overview", lambda db: {"orbits": []})
        assert asts_routes.ast_orbits(db=object()) == {"orbits": []}


class TestMoneyFlows:
    def test_temas_lista_los_resumenes(self, monkeypatch):
        monkeypatch.setattr(
            flows_routes,
            "theme_summaries",
            lambda: [{"id": "defensa", "name": "Defensa", "tagline": "t"}],
        )
        result = flows_routes.list_flow_themes()
        assert [t.id for t in result] == ["defensa"]

    def test_tema_no_configurado_es_404(self, monkeypatch):
        build = Mock()
        monkeypatch.setattr(flows_routes, "build_theme_payload", build)
        with pytest.raises(HTTPException) as exc:
            flows_routes.get_flow_theme(theme_id="no-existe", db=object())
        assert exc.value.status_code == 404
        build.assert_not_called()

    def test_tema_configurado_devuelve_el_payload(self, monkeypatch):
        tema_id, tema = next(iter(flows_routes.FLOW_THEMES.items()))
        monkeypatch.setattr(
            flows_routes,
            "build_theme_payload",
            lambda db, theme, tenant: {
                "id": "defensa",
                "name": "Defensa",
                "tagline": "t",
                "generated_at": __import__("datetime").datetime(2026, 11, 8),
                "spenders": [],
                "destinations": [],
                "suppliers": [],
                "method": "m",
                "limitation": "l",
            },
        )
        db = Mock(info={"tenant_id": 3})
        result = flows_routes.get_flow_theme(theme_id=tema_id, db=db)
        assert result.id == "defensa"
