"""Destinos de notificacion GLOBALES = del propietario.

ALERT_EMAIL_TO (SMTP), ALERT_EMAIL_WEBHOOK_URL, ALERT_PUSH_WEBHOOK_URL y el
TELEGRAM_CHAT_ID de aprobacion de tesis son UN solo destino para toda la
instalacion. Con varios usuarios, si cualquier tenant pudiera usarlos, las
alertas del usuario 2 (sus posiciones, sus tesis) llegarian al correo o al
Telegram del propietario y el usuario 2 no recibiria nada. Aqui se decide si
un tenant puede usar esos destinos: solo el del propietario.

Propietario = GLOBAL_ALERT_OWNER_USER_ID (el tenant de un usuario tiene como
external_id su id de usuario) o, si no esta, la primera cuenta creada (tenant
activo de id mas bajo), que es como se comportaba la instalacion de un solo
usuario.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings

NOT_OWNER_ERROR = "Destino global solo para la cuenta propietaria"


def owner_tenant_id(db: Session, settings=None) -> int | None:
    from app.models import Tenant

    settings = settings or get_settings()
    owner = str(getattr(settings, "global_alert_owner_user_id", None) or "").strip()
    statement = select(Tenant.id).where(Tenant.status == "active")
    if owner:
        statement = statement.where(Tenant.external_id == owner)
    statement = statement.order_by(Tenant.id).limit(1).execution_options(include_all_tenants=True)
    return db.scalar(statement)


def may_use_global_destination(db: Session, tenant_id: int | None, settings=None) -> bool:
    """True si las alertas de ``tenant_id`` pueden salir por un destino global.

    Sin tenant (modo local sin autenticacion) se mantiene el comportamiento de
    siempre: un solo usuario, el destino global es el suyo.
    """
    if tenant_id is None:
        return True
    settings = settings or get_settings()
    owner = owner_tenant_id(db, settings)
    if owner is None:
        # Sin ninguna cuenta registrada (instalacion local/tests) no hay a
        # quien proteger; con propietario explicito que no existe, nadie usa
        # el destino global.
        return not str(getattr(settings, "global_alert_owner_user_id", None) or "").strip()
    return owner == tenant_id
