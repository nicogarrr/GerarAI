"""Suscripciones de Telegram por tipo de evento (/api/alerts/telegram-subscriptions): sin tests hasta ahora.

Identidad obligatoria, activar solo con un chat vinculado y confirmado, propietario único
por espacio y tipo, y enabled_at que solo se mueve al (re)activar o cambiar de chat.
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.alerts import (
    TelegramSubscriptionIn,
    list_telegram_subscriptions,
    set_telegram_subscription,
)
from app.models.entities import AlertSubscription, Base, TelegramChatBinding

CHAT = "123456789"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info.update(tenant_id=1, user_id="user-a")
        yield session
    engine.dispose()


def _bind(db, user="user-a", chat=CHAT, tenant=1):
    db.add(TelegramChatBinding(tenant_id=tenant, user_id=user, chat_id=chat))
    db.commit()


def test_sin_identidad_verificada_401_en_lectura_y_escritura(db):
    db.info.pop("user_id")
    with pytest.raises(HTTPException) as listed:
        list_telegram_subscriptions(db)
    assert listed.value.status_code == 401
    with pytest.raises(HTTPException) as put:
        set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=False, chat_id=CHAT), db)
    assert put.value.status_code == 401


def test_listado_por_defecto_todo_apagado_y_sin_chat(db):
    rows = list_telegram_subscriptions(db)
    assert [row["event_type"] for row in rows] == [
        "thesis_broken", "new_filing", "insiders", "shorts_rising", "daily_digest", "dca_levels", "macro_event",
    ]
    assert all(row["enabled"] is False and row["chat_id"] is None for row in rows)


def test_activar_sin_chat_vinculado_es_403_y_no_escribe(db):
    with pytest.raises(HTTPException) as exc:
        set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=True, chat_id=CHAT), db)
    assert exc.value.status_code == 403
    assert db.scalar(select(AlertSubscription)) is None


def test_el_chat_vinculado_de_otro_usuario_no_vale(db):
    _bind(db, user="user-b")
    with pytest.raises(HTTPException) as exc:
        set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=True, chat_id=CHAT), db)
    assert exc.value.status_code == 403


def test_activar_con_chat_vinculado_crea_y_se_lista(db):
    _bind(db)
    out = set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=True, chat_id=CHAT), db)
    assert out == {"event_type": "insiders", "enabled": True, "chat_id": CHAT}
    listed = {row["event_type"]: row for row in list_telegram_subscriptions(db)}
    assert listed["insiders"] == {"event_type": "insiders", "enabled": True, "chat_id": CHAT}
    assert listed["daily_digest"]["enabled"] is False


def test_otro_usuario_del_mismo_espacio_no_puede_cambiarla(db):
    _bind(db)
    set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=True, chat_id=CHAT), db)
    db.info["user_id"] = "user-b"
    with pytest.raises(HTTPException) as exc:
        set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=False, chat_id=CHAT), db)
    assert exc.value.status_code == 403
    # Y su listado no ve la suscripción ajena.
    assert all(row["enabled"] is False for row in list_telegram_subscriptions(db))


def test_enabled_at_solo_cambia_al_reactivar(db):
    _bind(db)
    set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=True, chat_id=CHAT), db)
    row = db.scalar(select(AlertSubscription))
    old = datetime.now(UTC) - timedelta(days=3)
    row.enabled_at = old
    db.commit()
    # Volver a guardar lo mismo (ya activa, mismo chat) no reinicia la fecha.
    set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=True, chat_id=CHAT), db)
    db.refresh(row)
    assert row.enabled_at.replace(tzinfo=UTC) == old
    # Apagar tampoco.
    set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=False, chat_id=CHAT), db)
    db.refresh(row)
    assert row.enabled is False
    assert row.enabled_at.replace(tzinfo=UTC) == old
    # Reactivar sí: lo anterior a esta fecha no se envía de golpe.
    set_telegram_subscription("insiders", TelegramSubscriptionIn(enabled=True, chat_id=CHAT), db)
    db.refresh(row)
    assert row.enabled is True
    assert row.enabled_at.replace(tzinfo=UTC) > old


@pytest.mark.parametrize("chat_id", ["0123", "-100123", "abc", "1" * 21, ""])
def test_chat_id_debe_ser_un_chat_privado_numerico(chat_id):
    with pytest.raises(ValidationError):
        TelegramSubscriptionIn(enabled=True, chat_id=chat_id)
