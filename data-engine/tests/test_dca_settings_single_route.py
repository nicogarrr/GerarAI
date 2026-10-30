"""Los ajustes DCA viven en UNA ruta: /api/settings/dca (la que usa la web).

Antes el mismo router se montaba tambien en /api/dca-settings: dos rutas para
el mismo recurso, duplicadas en el OpenAPI y en el cliente generado.
"""
import main


def test_dca_settings_is_served_only_under_settings():
    paths = main.app.openapi()["paths"]
    assert set(paths["/api/settings/dca"]) >= {"get", "put"}
    assert "/api/dca-settings" not in paths
