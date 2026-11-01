"""Catalogo de empresas UNA vez por transaccion (peticion, mensaje de chat o
corrida de ingesta): la tabla companies se lee entera en varios detectores de
texto (ticker, nombre, ambiguedad) y cada lectura son ~2.100 filas ORM.

El cache vive en ``db.info`` pero atado a la transaccion abierta: se relee en
cuanto la transaccion cambia (commit, rollback o close + reutilizacion del
mismo objeto Session), y un hook ``after_flush`` lo invalida si la propia
sesion inserta, actualiza o borra empresas, y una escritura de Company aun
sin flush (``db.new``/``dirty``/``deleted``) fuerza la lectura para no
cortocircuitar antes del autoflush. Nunca sirve datos de otro
tenant: cada sesion tiene su propio ``db.info``.

Caveat: escrituras bulk por SQL (``session.execute(insert(Company))``) no
disparan eventos ORM; esos caminos deben seguir consultando directo.
"""
from __future__ import annotations

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import Company

_CACHE_KEY = "_company_catalog_all"
_HOOK_KEY = "_company_catalog_invalidation_hook"


def all_companies(db: Session) -> list[Company]:
    """Todas las empresas del maestro, una lectura por transaccion como maximo."""
    tx = db.get_transaction()
    cached = db.info.get(_CACHE_KEY)
    if (
        tx is not None
        and cached is not None
        and cached[0] is tx
        and not _has_pending_company_writes(db)
    ):
        return cached[1]
    rows = list(db.scalars(select(Company)).all())
    db.info[_CACHE_KEY] = (db.get_transaction(), rows)
    _install_invalidation_hook(db)
    return rows


def _install_invalidation_hook(db: Session) -> None:
    if db.info.get(_HOOK_KEY):
        return
    db.info[_HOOK_KEY] = True

    @event.listens_for(db, "after_flush")
    def _drop_catalog_on_company_write(session: Session, flush_context) -> None:
        touched = session.new | session.dirty | session.deleted
        if any(isinstance(obj, Company) for obj in touched):
            session.info.pop(_CACHE_KEY, None)


def _has_pending_company_writes(db: Session) -> bool:
    """Company pendiente de flush: el SELECT de abajo autoflushea y la veria;
    servir el cache aqui la esconderia."""
    return any(
        isinstance(obj, Company)
        for state in (db.new, db.dirty, db.deleted)
        for obj in state
    )
