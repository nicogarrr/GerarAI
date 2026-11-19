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

Excepcion acotada: ``pinned_catalog`` fija la lista para UNA tanda (p.ej. la
ingesta de N noticias, que commitea por item y re-leia las ~2.100 filas y
reconstruia el matcher de alias por noticia: medido 25 lecturas completas
para 25 items, ~154 ms/item en SQLite). El pin sobrevive a los commits de
la tanda pero NO a un rollback (los objetos quedan expirados y servirlos
dispararia un SELECT por fila: el hook ``after_rollback`` lo retira), y la
escritura de Company en la propia sesion (flush o pendiente) sigue
forzando lectura fresca.

Caveat: escrituras bulk por SQL (``session.execute(insert(Company))``) no
disparan eventos ORM; esos caminos deben seguir consultando directo.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models import Company

_CACHE_KEY = "_company_catalog_all"
_HOOK_KEY = "_company_catalog_invalidation_hook"
_PIN_KEY = "_company_catalog_pin"


def _probe(db: Session) -> tuple:
    """Firma barata del catalogo en UNA fila agregada: (filas, max updated, max id).

    Un alta mueve count y max(id); una baja, count; una edicion ORM mueve
    max(updated_at) (``onupdate``). La sonda se lee ANTES de la lista: una
    escritura que aterrice entre sonda y lectura deja la firma vieja y el
    siguiente ``pinned_catalog`` relee (nunca sirve una firma mas nueva que
    los datos). Escrituras bulk por SQL sin ``onupdate`` no la mueven:
    mismo caveat del modulo.
    """
    return db.execute(
        select(func.count(Company.id), func.max(Company.updated_at), func.max(Company.id))
    ).one()


def all_companies(db: Session) -> list[Company]:
    """Todas las empresas del maestro, una lectura por transaccion como maximo."""
    pinned = db.info.get(_PIN_KEY)
    # El pin solo vale en sesiones expire_on_commit=False (las de la app):
    # con expiracion, los objetos pineados se refrescarian fila a fila tras
    # cada commit (un SELECT por empresa: peor que re-leer el catalogo).
    if (
        pinned is not None
        and not db.expire_on_commit
        and not _has_pending_company_writes(db)
    ):
        return pinned[1]
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


def catalog_if_loaded(db: Session) -> list[Company] | None:
    """El catalogo SOLO si ya esta en memoria (pin o cache de transaccion).

    Nunca lee: para resolvedores que prefieren una busqueda indexada a
    cargar las ~2.100 filas cuando el catalogo no esta caliente (p.ej.
    resolve_company). Mismos guards que all_companies.
    """
    pinned = db.info.get(_PIN_KEY)
    if (
        pinned is not None
        and not db.expire_on_commit
        and not _has_pending_company_writes(db)
    ):
        return pinned[1]
    tx = db.get_transaction()
    cached = db.info.get(_CACHE_KEY)
    if (
        tx is not None
        and cached is not None
        and cached[0] is tx
        and not _has_pending_company_writes(db)
    ):
        return cached[1]
    return None


@contextmanager
def pinned_catalog(db: Session):
    """Fija el catalogo para una tanda de lecturas intensiva (p.ej. ingesta).

    Una lectura completa al entrar; las siguientes llamadas de la tanda la
    reutilizan aunque haya commits intermedios. La tanda de ingesta no
    escribe Company, y si lo hiciera el guard de escrituras pendientes y
    el hook after_flush invalidan el pin en el acto.

    Reentrante y validado por sonda: un pin anidado (la ingesta dentro de
    un barrido que ya pinea, p.ej. refresh_news por empresa) NO relee las
    ~2.100 filas ni retira el pin del exterior; comprueba la sonda
    agregada de una fila (``_probe``) y solo relee si el catalogo cambio
    desde que se fijo (p.ej. otra sesion dio de alta una empresa a mitad
    de barrido). Medido: un barrido de 30 tandas pasaba de 30 lecturas
    completas del catalogo a 1 lectura + 30 sondas de una fila.
    """
    _install_invalidation_hook(db)
    pin = db.info.get(_PIN_KEY)
    if (
        pin is not None
        and not db.expire_on_commit
        and not _has_pending_company_writes(db)
    ):
        sig, rows = pin
        if _probe(db) == sig:
            yield rows
            return
        # Catalogo cambiado a mitad de pin: relee y sustituye (el pin lo
        # sigue poseyendo el exterior; no se retira aqui). Sonda ANTES de
        # la lectura, como en la entrada: una escritura entre ambas deja
        # la firma vieja y la siguiente sonda fuerza otra relectura.
        sig = _probe(db)
        rows = list(db.scalars(select(Company)).all())
        db.info[_PIN_KEY] = (sig, rows)
        yield rows
        return
    sig = _probe(db)
    rows = all_companies(db)
    db.info[_PIN_KEY] = (sig, rows)
    try:
        yield rows
    finally:
        db.info.pop(_PIN_KEY, None)


def _install_invalidation_hook(db: Session) -> None:
    if db.info.get(_HOOK_KEY):
        return
    db.info[_HOOK_KEY] = True

    @event.listens_for(db, "after_flush")
    def _drop_catalog_on_company_write(session: Session, flush_context) -> None:
        touched = session.new | session.dirty | session.deleted
        if any(isinstance(obj, Company) for obj in touched):
            session.info.pop(_CACHE_KEY, None)
            session.info.pop(_PIN_KEY, None)

    @event.listens_for(db, "after_rollback")
    def _drop_pin_on_rollback(session: Session) -> None:
        # Los objetos pineados quedan expirados tras rollback: servirlos
        # dispararia un SELECT de refresco por fila (peor que re-leer).
        session.info.pop(_PIN_KEY, None)


def _has_pending_company_writes(db: Session) -> bool:
    """Company pendiente de flush: el SELECT de abajo autoflushea y la veria;
    servir el cache aqui la esconderia."""
    return any(
        isinstance(obj, Company)
        for state in (db.new, db.dirty, db.deleted)
        for obj in state
    )
