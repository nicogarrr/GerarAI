"""Ruta GET /money-flows/themes/{theme_id}: 404 y camino feliz.

Sobre main solo se ejercitaba el listado de temas; el detalle por tema
(404 configurable y delegacion en build_theme_payload) no tenia cobertura.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import money_flows as mod
from app.api.routes.money_flows import get_flow_theme, list_flow_themes
from app.models.entities import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        yield db
    engine.dispose()


def test_list_flow_themes_devuelve_resumenes():
    out = list_flow_themes()
    assert len(out) >= 1
    assert out[0].id and out[0].name


def test_get_flow_theme_desconocido_es_404(db):
    with pytest.raises(HTTPException) as exc:
        get_flow_theme("tema-que-no-existe", db=db)
    assert exc.value.status_code == 404


def test_get_flow_theme_delega_en_el_payload_del_servicio(db, monkeypatch):
    capturado = {}

    def fake_payload(db_, theme, tenant):
        capturado["theme"] = theme
        capturado["tenant"] = tenant
        return {
            "id": theme["id"] if isinstance(theme, dict) and "id" in theme else "utilities",
            "name": "Utilities",
            "tagline": "t",
            "generated_at": datetime.now(UTC),
            "spenders": [],
            "destinations": [],
            "suppliers": [],
            "method": "m",
            "limitation": "l",
        }

    monkeypatch.setattr(mod, "build_theme_payload", fake_payload)
    db.info["tenant_id"] = 7
    out = get_flow_theme("utilities", db=db)
    assert out.id == "utilities"
    # El tenant de la sesion llega al constructor del payload.
    assert capturado["tenant"] == 7


def test_get_flow_theme_sin_tenant_en_sesion(db, monkeypatch):
    capturado = {}

    def fake_payload(db_, theme, tenant):
        capturado["tenant"] = tenant
        return {
            "id": "utilities",
            "name": "Utilities",
            "tagline": "t",
            "generated_at": datetime.now(UTC),
            "spenders": [],
            "destinations": [],
            "suppliers": [],
            "method": "m",
            "limitation": "l",
        }

    monkeypatch.setattr(mod, "build_theme_payload", fake_payload)
    out = get_flow_theme("utilities", db=db)
    assert out.id == "utilities"
    assert capturado["tenant"] is None
