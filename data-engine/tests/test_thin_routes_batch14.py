"""Huecos de cobertura en alerts (lote 14).

Medicion previa (mismo metodo, tests que referencian el modulo): alerts 73,4 %.
Se cubren: create (404), listado con filtro ticker (404) y filtro active,
evaluate, deactivate (404 y feliz), analisis (404), action (404/400/feliz),
dispatch (404/feliz), canales (404/feliz con dedup), email-preferences (401),
_push_identity, y todo el bloque push: config, status, registro de dispositivo
(409/422/403/alta/actualizacion), baja y preferencias (409/403/alta/cambio).

Refuerzo (deuda del auditor): las altas de suscripcion y preferencia
assertan la fila completa (tenant, user, endpoint_hash, p256dh, auth,
user_agent / event_type, enabled, enabled_at); los rechazos 409/422/403
assertan que NO se llama a db.add ni db.commit; desactivar asserta con
espias que no se consulta ni la config ni los dispositivos; y el listado
de reglas inspecciona la SQL compilada con valores literales.

Que NO se prueba aqui: nada de HTTP ni auth; ninguna base de datos real (las
consultas SQL se construyen pero van contra una db doblada: el filtrado SQL
real NO se prueba); AlertRuleService, ReviewAlertService, NotificationService,
resolve_company, read_analysis y web_push (is_configured, devices_for,
endpoint_hash, endpoint_is_allowed) van doblados (solo delegacion); no se envia
ninguna notificacion push/email real.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import alerts as a


def _db(tenant=1, user="u1"):
    db = Mock()
    db.info = {"tenant_id": tenant, "user_id": user}
    return db


def _settings(**kw):
    base = dict(
        telegram_enabled=False, telegram_bot_token=None, telegram_chat_id=None,
        vapid_public_key="VAPID-KEY",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --- reglas de alerta ----------------------------------------------------------


def _payload_alerta():
    return a.ManualAlertCreate(ticker="ASTS", alert_type="price_above", operator=">", value=10.0)


def test_crear_alerta_empresa_desconocida_es_404(monkeypatch):
    monkeypatch.setattr(a, "resolve_company", lambda db, ticker: None)
    with pytest.raises(HTTPException) as exc:
        a.create_alert(_payload_alerta(), db=_db())
    assert exc.value.status_code == 404


def test_listar_reglas_ticker_desconocido_es_404(monkeypatch):
    monkeypatch.setattr(a, "resolve_company", lambda db, ticker: None)
    with pytest.raises(HTTPException) as exc:
        a.list_alert_rules(ticker="NOPE", active=None, limit=10, offset=0, db=_db())
    assert exc.value.status_code == 404


def test_listar_reglas_con_ticker_y_activas(monkeypatch):
    monkeypatch.setattr(a, "resolve_company", lambda db, ticker: SimpleNamespace(id=7))
    db = _db()
    db.scalars.return_value.all.return_value = []
    assert a.list_alert_rules(ticker="ASTS", active=True, limit=10, offset=0, db=db) == []
    # La SQL construida se inspecciona compilada (valores literales); NO se
    # ejecuta contra ninguna base de datos.
    stmt = db.scalars.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "company_id = 7" in sql
    assert "active IS true" in sql
    assert "ORDER BY" in sql and "created_at DESC" in sql and "id DESC" in sql


def test_evaluar_reglas_delega(monkeypatch):
    monkeypatch.setattr(
        a, "AlertRuleService", lambda: SimpleNamespace(evaluate_all=lambda db: [{"r": 1}, {"r": 2}])
    )
    result = a.evaluate_alert_rules(db=_db())
    assert result["status"] == "ok"
    assert result["evaluated"] == 2


def test_desactivar_regla_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        a.deactivate_alert_rule(5, db=db)
    assert exc.value.status_code == 404


def test_desactivar_regla_feliz():
    regla = SimpleNamespace(id=5, active=True)
    db = _db()
    db.get.return_value = regla
    result = a.deactivate_alert_rule(5, db=db)
    assert result.active is False
    db.commit.assert_called_once()


# --- alertas de research ---------------------------------------------------------


def test_analisis_inexistente_es_404(monkeypatch):
    from app.services import alert_analysis_service

    def no_hay(db, alert_id):
        raise LookupError("sin analisis")

    monkeypatch.setattr(alert_analysis_service, "read_analysis", no_hay)
    with pytest.raises(HTTPException) as exc:
        a.get_alert_analysis(5, db=_db())
    assert exc.value.status_code == 404


def test_analisis_feliz(monkeypatch):
    from app.services import alert_analysis_service

    monkeypatch.setattr(alert_analysis_service, "read_analysis", lambda db, i: {"id": i})
    assert a.get_alert_analysis(5, db=_db()) == {"id": 5}


def _payload_accion(accion="acknowledge"):
    from app.schemas import ResearchAlertAction

    return ResearchAlertAction(action=accion)


def test_accion_alerta_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        a.action_alert(5, _payload_accion(), db=db)
    assert exc.value.status_code == 404


def test_accion_alerta_feliz(monkeypatch):
    visto = {}
    monkeypatch.setattr(
        a,
        "ReviewAlertService",
        lambda: SimpleNamespace(
            transition_alert=lambda alert, action, actor, snoozed_until: visto.update(
                action=action, actor=actor)
        ),
    )
    alerta = SimpleNamespace(id=5)
    db = _db()
    db.get.return_value = alerta
    assert a.action_alert(5, _payload_accion("resolve"), db=db) is alerta
    assert visto["action"] == "resolve"
    db.commit.assert_called_once()


def test_accion_invalida_es_400(monkeypatch):
    def conflicto(alert, action, actor, snoozed_until):
        raise ValueError("transicion imposible")

    monkeypatch.setattr(
        a, "ReviewAlertService", lambda: SimpleNamespace(transition_alert=conflicto)
    )
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    with pytest.raises(HTTPException) as exc:
        a.action_alert(5, _payload_accion(), db=db)
    assert exc.value.status_code == 400


def test_dispatch_alerta_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        a.dispatch_alert(5, db=db)
    assert exc.value.status_code == 404


def test_dispatch_alerta_feliz(monkeypatch):
    monkeypatch.setattr(
        a, "NotificationService", lambda: SimpleNamespace(dispatch=lambda db, alert: ["in_app"])
    )
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    result = a.dispatch_alert(5, db=db)
    assert result == {"alert_id": 5, "deliveries": ["in_app"]}


def test_canales_alerta_inexistente_es_404():
    from app.schemas import ResearchAlertChannels

    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        a.update_alert_channels(5, ResearchAlertChannels(channels=["email"]), db=db)
    assert exc.value.status_code == 404


def test_canales_dedup_y_guardado():
    from app.schemas import ResearchAlertChannels

    alerta = SimpleNamespace(id=5, channels=[])
    db = _db()
    db.get.return_value = alerta
    result = a.update_alert_channels(
        5, ResearchAlertChannels(channels=["email", "email", "push"]), db=db
    )
    assert result.channels == ["email", "push"]
    db.commit.assert_called_once()


# --- email preferences ------------------------------------------------------------


def test_email_preference_sin_identidad_es_401():
    with pytest.raises(HTTPException) as exc:
        a.set_email_preference("new_filing", a.EmailPreferenceIn(enabled=False), db=_db(None, None))
    assert exc.value.status_code == 401


# --- push --------------------------------------------------------------------------


def test_push_identity_sin_identidad_es_401():
    with pytest.raises(HTTPException) as exc:
        a._push_identity(_db(None, None))
    assert exc.value.status_code == 401


def test_push_identity_feliz():
    assert a._push_identity(_db(3, "u9")) == (3, "u9")


def test_push_config_no_configurado(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: False)
    monkeypatch.setattr(a, "get_settings", _settings)
    assert a.push_config() == {"enabled": False, "public_key": None}


def test_push_config_configurado(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(a, "get_settings", _settings)
    assert a.push_config() == {"enabled": True, "public_key": "VAPID-KEY"}


def test_push_status(monkeypatch):
    from app.services import outbound_alerts, web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(web_push, "devices_for", lambda db, t, u: ["dev1", "dev2"])
    monkeypatch.setattr(a, "get_settings", _settings)
    db = _db()
    db.scalars.return_value = iter([
        SimpleNamespace(event_type=outbound_alerts.EVENT_TYPES[0], enabled=True)
    ])
    result = a.push_status(db=db)
    assert result["devices"] == 2
    assert result["preferences"][0]["enabled"] is True
    assert all(not p["enabled"] for p in result["preferences"][1:])


def _sub_payload():
    return a.PushSubscriptionIn(
        endpoint="https://push.example.com/sub/abcdef",
        keys=a.PushKeys(p256dh="B" * 24, auth="A" * 12),
        user_agent="agente",
    )


def test_registro_push_sin_configurar_es_409(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: False)
    monkeypatch.setattr(a, "get_settings", _settings)
    db = _db()
    with pytest.raises(HTTPException) as exc:
        a.register_push_device(_sub_payload(), db=db)
    assert exc.value.status_code == 409
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_registro_push_endpoint_no_soportado_es_422(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(web_push, "endpoint_is_allowed", lambda endpoint: False)
    monkeypatch.setattr(a, "get_settings", _settings)
    db = _db()
    with pytest.raises(HTTPException) as exc:
        a.register_push_device(_sub_payload(), db=db)
    assert exc.value.status_code == 422
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_registro_push_dispositivo_de_otro_es_403(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(web_push, "endpoint_is_allowed", lambda endpoint: True)
    monkeypatch.setattr(web_push, "endpoint_hash", lambda endpoint: "h1")
    monkeypatch.setattr(a, "get_settings", _settings)
    db = _db(user="u1")
    db.scalar.return_value = SimpleNamespace(user_id="otro")
    with pytest.raises(HTTPException) as exc:
        a.register_push_device(_sub_payload(), db=db)
    assert exc.value.status_code == 403
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_registro_push_alta_nueva(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(web_push, "endpoint_is_allowed", lambda endpoint: True)
    monkeypatch.setattr(web_push, "endpoint_hash", lambda endpoint: "h1")
    monkeypatch.setattr(a, "get_settings", _settings)
    db = _db()
    db.scalar.return_value = None
    result = a.register_push_device(_sub_payload(), db=db)
    assert result == {"registered": True}
    db.add.assert_called_once()
    db.commit.assert_called_once()
    # La fila de alta lleva TODOS los campos de la suscripcion.
    fila = db.add.call_args.args[0]
    assert fila.tenant_id == 1
    assert fila.user_id == "u1"
    assert fila.endpoint == "https://push.example.com/sub/abcdef"
    assert fila.endpoint_hash == "h1"
    assert fila.p256dh == "B" * 24
    assert fila.auth_secret == "A" * 12
    assert fila.user_agent == "agente"


def test_registro_push_actualiza_existente(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(web_push, "endpoint_is_allowed", lambda endpoint: True)
    monkeypatch.setattr(web_push, "endpoint_hash", lambda endpoint: "h1")
    monkeypatch.setattr(a, "get_settings", _settings)
    fila = SimpleNamespace(user_id="u1", p256dh=None, auth_secret=None, user_agent=None)
    db = _db(user="u1")
    db.scalar.return_value = fila
    a.register_push_device(_sub_payload(), db=db)
    assert fila.p256dh == "B" * 24
    assert fila.auth_secret == "A" * 12
    assert fila.user_agent == "agente"
    db.commit.assert_called_once()
    db.add.assert_not_called()


def test_baja_push_inexistente(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "endpoint_hash", lambda endpoint: "h1")
    db = _db()
    db.scalar.return_value = None
    payload = a.PushEndpointIn(endpoint="https://push.example.com/sub/abcdef")
    assert a.remove_push_device(payload, db=db) == {"removed": False}
    db.delete.assert_not_called()


def test_baja_push_feliz(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "endpoint_hash", lambda endpoint: "h1")
    db = _db()
    db.scalar.return_value = SimpleNamespace(id=9)
    payload = a.PushEndpointIn(endpoint="https://push.example.com/sub/abcdef")
    assert a.remove_push_device(payload, db=db) == {"removed": True}
    db.delete.assert_called_once()


def test_preferencia_push_activar_sin_configurar_es_409(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: False)
    monkeypatch.setattr(a, "get_settings", _settings)
    db = _db()
    with pytest.raises(HTTPException) as exc:
        a.set_push_preference("new_filing", a.PushPreferenceIn(enabled=True), db=db)
    assert exc.value.status_code == 409
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_preferencia_push_activar_sin_dispositivos_es_403(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(web_push, "devices_for", lambda db, t, u: [])
    monkeypatch.setattr(a, "get_settings", _settings)
    db = _db()
    with pytest.raises(HTTPException) as exc:
        a.set_push_preference("new_filing", a.PushPreferenceIn(enabled=True), db=db)
    assert exc.value.status_code == 403
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_preferencia_push_alta_nueva(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(web_push, "devices_for", lambda db, t, u: ["dev"])
    monkeypatch.setattr(a, "get_settings", _settings)
    db = _db()
    db.scalar.return_value = None
    result = a.set_push_preference("new_filing", a.PushPreferenceIn(enabled=True), db=db)
    assert result["enabled"] is True
    db.add.assert_called_once()
    # La fila de alta queda completa: tenant, user, evento, enabled y fecha.
    fila = db.add.call_args.args[0]
    assert fila.tenant_id == 1
    assert fila.user_id == "u1"
    assert fila.event_type == "new_filing"
    assert fila.enabled is True
    assert fila.enabled_at is not None


def test_preferencia_push_reactivar_marca_fecha(monkeypatch):
    from app.services import web_push

    monkeypatch.setattr(web_push, "is_configured", lambda settings: True)
    monkeypatch.setattr(web_push, "devices_for", lambda db, t, u: ["dev"])
    monkeypatch.setattr(a, "get_settings", _settings)
    fila = SimpleNamespace(enabled=False, enabled_at=None)
    db = _db()
    db.scalar.return_value = fila
    result = a.set_push_preference("new_filing", a.PushPreferenceIn(enabled=True), db=db)
    assert result["enabled"] is True
    assert fila.enabled_at is not None


def test_preferencia_push_desactivar_no_pide_config_ni_dispositivos(monkeypatch):
    # enabled=False salta las comprobaciones de configuracion y dispositivos,
    # y sobre una fila existente no toca enabled_at.
    from app.services import web_push

    configurada = Mock(return_value=False)
    dispositivos = Mock(return_value=[])
    monkeypatch.setattr(web_push, "is_configured", configurada)
    monkeypatch.setattr(web_push, "devices_for", dispositivos)
    fila = SimpleNamespace(enabled=True, enabled_at="ayer")
    db = _db()
    db.scalar.return_value = fila
    result = a.set_push_preference("new_filing", a.PushPreferenceIn(enabled=False), db=db)
    assert result["enabled"] is False
    assert fila.enabled_at == "ayer"
    configurada.assert_not_called()
    dispositivos.assert_not_called()
    db.commit.assert_called_once()
    db.add.assert_not_called()
