"""Nombres de filtros guardados: duplicados y nombres liberados al archivar.

Encontrado con Schemathesis: crear dos filtros con el mismo nombre devolvía un
500 (IntegrityError de ``uq_saved_screen_tenant_name``), y un filtro archivado
seguía reservando su nombre, así que «borrar y volver a crear» fallaba igual.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.screeners import (
    ScreenCreate,
    create_screen,
    delete_screen,
    list_screens,
    update_screen,
)
from app.core.database import Base
from app.models import SavedScreen, Tenant

CRITERIA = [{"left": "market_cap", "operator": ">", "right": "100"}]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="screen-names"))
        session.flush()
        session.info["tenant_id"] = 1
        yield session


def _payload(name: str) -> ScreenCreate:
    return ScreenCreate(name=name, criteria=CRITERIA)


def test_duplicate_active_name_is_a_400_not_a_500(db):
    create_screen(_payload("Value"), db)
    with pytest.raises(HTTPException) as error:
        create_screen(_payload("Value"), db)
    assert error.value.status_code == 400
    assert "nombre" in str(error.value.detail)
    # La sesión sigue usable tras el rechazo.
    assert [row["name"] for row in list_screens(db)] == ["Value"]


def test_duplicate_name_ignores_surrounding_whitespace(db):
    create_screen(_payload("Value"), db)
    with pytest.raises(HTTPException) as error:
        create_screen(_payload("  Value "), db)
    assert error.value.status_code == 400


def test_archived_screen_releases_its_name(db):
    first = create_screen(_payload("Value"), db)
    delete_screen(first["id"], db)
    second = create_screen(_payload("Value"), db)
    assert second["id"] != first["id"]
    assert [row["name"] for row in list_screens(db)] == ["Value"]
    archived = db.get(SavedScreen, first["id"])
    assert archived is not None and archived.active is False
    assert archived.name != "Value"


def test_rename_onto_archived_name_is_allowed(db):
    old = create_screen(_payload("Value"), db)
    delete_screen(old["id"], db)
    other = create_screen(_payload("Growth"), db)
    renamed = update_screen(other["id"], _payload("Value"), db)
    assert renamed["name"] == "Value"


def test_rename_onto_active_name_is_rejected(db):
    create_screen(_payload("Value"), db)
    other = create_screen(_payload("Growth"), db)
    with pytest.raises(HTTPException) as error:
        update_screen(other["id"], _payload("Value"), db)
    assert error.value.status_code == 400


def test_blank_name_is_rejected_on_create(db):
    with pytest.raises(HTTPException) as error:
        create_screen(_payload("   "), db)
    assert error.value.status_code == 400
