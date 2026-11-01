"""El 400 por rango invertido llega al usuario: el detalle va entrecomillado.

Los parámetros se llaman ``desde`` y ``hasta`` en la query; el mensaje los
cita entre comillas («"desde" no puede ser posterior a "hasta"») para que se
lea como una frase y no como un identificador suelto.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_macro_calendar_rango_invertido_detalle_entrecomillado() -> None:
    client = TestClient(main.app, raise_server_exceptions=False)
    res = client.get("/api/macro-calendar/events?desde=2026-02-01&hasta=2026-01-01")
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == '"desde" no puede ser posterior a "hasta"'
