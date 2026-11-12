"""Rutas de flujos de dinero: paso al servicio y 404 limpio.

Los servicios se sustituyen por dobles y las funciones de la ruta se llaman
directamente: se prueba solo el mapeo funcion -> resultado (cada endpoint
devuelve lo de su servicio; un tema de flujo no configurado es 404, nunca un
500). No se prueba la capa HTTP ni la auth del
despliegue.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import money_flows as flows_routes


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
