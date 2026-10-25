"""Primer uso sin datos: encola la descarga 13F del tenant, una vez como mucho
por ventana de enfriamiento.

El cron semanal (lunes 04:20) deja a una cuenta creada un martes hasta seis
dias sin carteras. Con este auto-encolado, la primera lectura de inversores o
13F sin datos lanza el mismo actor del boton «Sincronizar» y responde igual de
rapido (el actor trabaja en segundo plano).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import FundManager

# El actor tarda minutos; reintentos como mucho uno por hora por tenant.
COOLDOWN_SECONDS = 3600


def maybe_autosync_holdings(db: Session) -> bool:
    """Encola sync_investor_holdings si el tenant no tiene ningun gestor 13F
    descargado y no se encolo ya en la ultima hora. Devuelve True si encolo.

    Sin Redis no se encola: Redis es tambien el broker del actor, asi que el
    mensaje no podria correr y cada carga de pagina reintentaria en vano.
    La lectura que nos llama nunca rompe por el auto-encolado: cualquier
    fallo devuelve False y la respuesta sale con datos o sin ellos.
    """
    try:
        if db.scalar(
            select(FundManager.id)
            .where(*tenant_filters(db, FundManager))
            .limit(1)
        ) is not None:
            return False
        from app.workers.dramatiq_app import _redis_client, sync_investor_holdings

        client = _redis_client()
        if client is None:
            return False
        claimed = client.set(
            f"autosync:investor-holdings:{db.info.get('tenant_id')}",
            "1",
            nx=True,
            ex=COOLDOWN_SECONDS,
        )
        if not claimed:
            return False
        sync_investor_holdings.send(
            tenant_id=db.info.get("tenant_id"),
            user_id=db.info.get("user_id"),
        )
        return True
    except Exception:  # noqa: BLE001 - la lectura nunca rompe por el auto-encolado
        return False
