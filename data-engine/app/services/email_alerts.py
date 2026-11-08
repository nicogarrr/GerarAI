"""Correo por usuario: destino propio verificado + opt-in por tipo de evento.

Mismas garantias que Telegram (``subscription_for``) y push
(``preference_for``):

* La direccion sale de ``user_email_bindings`` y SOLO la escribe el backend
  cuando el frontend la firma con el secreto de la identidad (la direccion de
  la sesion better-auth): un usuario no puede hacer que sus alertas salgan a
  la direccion de otro, y nadie recibe las alertas de otro.
* Consentimiento: el usuario activa cada tipo (``EmailPreference.enabled``) y
  lo apaga cuando quiera. Solo se envian alertas creadas tras el alta
  (``enabled_at``), como en Telegram y push.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmailPreference, ResearchAlert, UserEmailBinding


@dataclass(frozen=True)
class UserEmailTarget:
    """Destino de correo propio aplicable a una alerta."""

    preference: EmailPreference
    binding: UserEmailBinding


def binding_for(db: Session, tenant_id: int, user_id: str) -> UserEmailBinding | None:
    """Direccion verificada del usuario, si el frontend ya la firmo alguna vez."""
    return db.scalar(
        select(UserEmailBinding).where(
            UserEmailBinding.tenant_id == tenant_id,
            UserEmailBinding.user_id == user_id,
        )
    )


def sync_binding(db: Session, tenant_id: int, user_id: str, address: str) -> UserEmailBinding:
    """Crea o actualiza la direccion del usuario (solo con direccion firmada).

    Idempotente: si no cambio, no escribe. El commit lo hace el llamador.
    """
    row = binding_for(db, tenant_id, user_id)
    if row is not None:
        if row.address != address:
            row.address = address
        return row
    row = UserEmailBinding(tenant_id=tenant_id, user_id=user_id, address=address)
    db.add(row)
    db.flush()
    return row


def preference_for(db: Session, alert: ResearchAlert) -> UserEmailTarget | None:
    """Destino de correo propio que cubre esta alerta, o None.

    Solo aplica si la alerta es del tenant y del usuario de la sesion que la
    despacha, el tipo tiene opt-in activo y la alerta nacio tras el alta.
    """
    from app.services.outbound_alerts import alert_after_opt_in, alert_category

    category = alert_category(db, alert)
    user = db.info.get("user_id")
    if not category or not user:
        return None
    row = db.scalar(
        select(EmailPreference).where(
            EmailPreference.tenant_id == alert.tenant_id,
            EmailPreference.user_id == user,
            EmailPreference.event_type == category,
            EmailPreference.enabled.is_(True),
        )
    )
    if row is None:
        return None
    if not alert_after_opt_in(alert.created_at, row.enabled_at):
        return None
    binding = binding_for(db, alert.tenant_id, user)
    if binding is None:
        return None
    return UserEmailTarget(preference=row, binding=binding)


def opted_out(db: Session, alert: ResearchAlert) -> bool:
    """True si el usuario ya tiene decision sobre este tipo y NO autoriza esta
    alerta (tipo apagado u alerta anterior al alta).

    En ese caso el correo se omite del todo: caer al destino global
    ALERT_EMAIL_TO ignoraria el opt-out. Sin fila todavia no hay decision y
    se mantiene el comportamiento historico (cuenta propietaria).
    """
    from app.services.outbound_alerts import alert_after_opt_in, alert_category

    category = alert_category(db, alert)
    user = db.info.get("user_id")
    if not category or not user:
        return False
    row = db.scalar(
        select(EmailPreference).where(
            EmailPreference.tenant_id == alert.tenant_id,
            EmailPreference.user_id == user,
            EmailPreference.event_type == category,
        )
    )
    if row is None:
        return False
    if not row.enabled:
        return True
    return not alert_after_opt_in(alert.created_at, row.enabled_at)
