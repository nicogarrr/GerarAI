"""Huecos de cobertura en analyst_notes y obsidian (lote 8).

Medicion previa (mismo metodo, tests que referencian cada modulo):
analyst_notes 96,9 % (ranked_firms sin ningun horizonte con datos y la
vista que se queda "empty") y obsidian 87,7 % (vault sin empresas -> {} y
la ruta /obsidian.zip: dos 404 y la respuesta zip). Estos tests cierran
esas ramas con dobles sencillos.

Que NO se prueba aqui: nada de HTTP ni auth; el zip es un doble (no se
genera ni se descomprime nada); no hay base de datos real (db va doblada);
y ranked_firms se prueba como funcion pura con historiales fabricados, sin
servicio de casas ni errores de estimacion reales. La exportacion es de
notas de tesis YA persistidas: no se genera ninguna tesis.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import analyst_notes as notes_route
from app.api.routes import obsidian as obsidian_route

# --- analyst_notes ----------------------------------------------------------


def _historia(best_horizon, horizontes):
    return SimpleNamespace(
        status="available",
        note=None,
        best_horizon=best_horizon,
        horizons=horizontes,
    )


def test_ranked_firms_sin_horizonte_con_datos_devuelve_vacio():
    """Horizontes presentes pero sin casas puntuadas: (None, [])."""
    history = _historia("12m", [SimpleNamespace(horizon="12m", top=[])])
    assert notes_route.ranked_firms(history) == (None, [])


def test_ranked_firms_best_horizon_desaparecido_pasa_al_siguiente():
    """Si el mejor horizonte ya no esta en la lista, se sigue con el resto."""
    top = [SimpleNamespace(firm="Casa X")]
    history = _historia(
        "6m", [SimpleNamespace(horizon="12m", top=top)]
    )
    clave, firms = notes_route.ranked_firms(history)
    assert clave == "12m"
    assert [f.firm for f in firms] == ["Casa X"]


def test_vista_sin_notas_se_queda_empty():
    """Sin ranking y sin notas del tenant, el estado no sube a available."""
    view = notes_route.build_view(
        db=Mock(), tenant_id=1, ticker="asts ", history=None, per_firm=1, others=0
    )
    assert view.status == "empty"
    assert view.notes == []
    assert view.other_notes == []
    assert view.ticker == "ASTS"


# --- obsidian ----------------------------------------------------------------


def test_vault_sin_empresas_es_diccionario_vacio():
    """Sin empresas seguidas no hay consultas: {} de inmediato."""
    db = Mock()
    assert obsidian_route._load_thesis_notes_by_company(db, []) == {}
    db.scalars.assert_not_called()


def test_export_compania_desconocida_es_404(monkeypatch):
    monkeypatch.setattr(obsidian_route, "resolve_company", lambda db, t: None)
    with pytest.raises(HTTPException) as exc:
        obsidian_route.export_obsidian("NOPE", db=Mock())
    assert exc.value.status_code == 404


def test_export_sin_tesis_es_404(monkeypatch):
    company = SimpleNamespace(ticker="ASTS")
    monkeypatch.setattr(obsidian_route, "resolve_company", lambda db, t: company)
    monkeypatch.setattr(obsidian_route, "_load_thesis_notes", lambda db, c: [])
    with pytest.raises(HTTPException) as exc:
        obsidian_route.export_obsidian("ASTS", db=Mock())
    assert exc.value.status_code == 404


def test_export_devuelve_el_zip(monkeypatch):
    company = SimpleNamespace(ticker="ASTS")
    monkeypatch.setattr(obsidian_route, "resolve_company", lambda db, t: company)
    monkeypatch.setattr(
        obsidian_route, "_load_thesis_notes", lambda db, c: [SimpleNamespace()]
    )
    monkeypatch.setattr(
        obsidian_route, "build_obsidian_zip", lambda ticker, notes: b"PK-falso"
    )
    result = obsidian_route.export_obsidian("ASTS", db=Mock())
    assert result.body == b"PK-falso"
    assert "ASTS" in result.headers["content-disposition"]
