"""Huecos de cobertura en ownership y propicks_radar (lote 6).

Medicion previa (mismo metodo, tests que referencian cada modulo):
ownership 65 % (lista de gestores, los dos sync, changes, holdings con
autosync, institutions y funds) y propicks_radar 98 % (el `continue` de
una senal cuya compania ya no existe en el catalogo). Estos tests cierran
esas ramas con servicios doblados en el modulo de ruta.

Que NO se prueba aqui: nada de HTTP, middleware ni auth; ningun servicio
real (ManagerHoldingIngestionService, institutional_holders, fund_holders,
autosync, quality_for_companies van doblados); ninguna fuente externa (SEC
13F/N-PORT); y el encolado de sync-async solo certifica que se llama a
.send con el tenant/user de la sesion doblada: no prueba dramatiq, el
broker ni el worker.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import ownership as ownership_route
from app.api.routes import propicks_radar as radar_route

# --- ownership -------------------------------------------------------------


def test_lista_gestores_revisados_con_limitaciones():
    """GET /ownership/managers: el catalogo fijo de gestores revisados."""
    result = ownership_route.list_managers()
    ciks = {m["cik"] for m in result["managers"]}
    assert ciks == set(ownership_route.REVIEWED_MANAGERS)
    assert result["limitations"] == ownership_route.LIMITATIONS


def test_sync_async_encola_el_actor_con_el_tenant(monkeypatch):
    """POST /managers/sync-async: encola y devuelve el id del mensaje."""
    enviado = {}

    class ActorFalso:
        def send(self, **kwargs):
            enviado.update(kwargs)
            return SimpleNamespace(message_id="msg-1")

    from app.workers import dramatiq_app

    monkeypatch.setattr(dramatiq_app, "sync_investor_holdings", ActorFalso())
    db = Mock()
    db.info = {"tenant_id": 7, "user_id": 3}
    result = ownership_route.sync_managers_async(db=db)
    assert enviado == {"tenant_id": 7, "user_id": 3}
    assert result == {"status": "queued", "broker_message_id": "msg-1"}


def test_sync_con_cik_solo_ese_gestor(monkeypatch):
    """POST /managers/sync?cik=...: sincroniza un gestor, no todos."""
    servicio = Mock()
    servicio.sync_manager.return_value = {"synced": 1}
    monkeypatch.setattr(
        ownership_route, "ManagerHoldingIngestionService", lambda: servicio
    )
    result = ownership_route.sync_managers(cik="0001067983", db=Mock())
    servicio.sync_manager.assert_called_once()
    servicio.sync_all.assert_not_called()
    assert result == {"synced": 1}


def test_cambios_trimestrales_de_un_gestor(monkeypatch):
    servicio = Mock()
    servicio.changes.return_value = {"changes": []}
    monkeypatch.setattr(
        ownership_route, "ManagerHoldingIngestionService", lambda: servicio
    )
    assert ownership_route.manager_changes(cik="X", db=Mock()) == {"changes": []}


def test_holdings_dispara_autosync_y_devuelve_cartera(monkeypatch):
    """GET /managers/{cik}/holdings: autosync en lectura y luego la cartera."""
    from app.services import investor_autosync

    llamadas = []
    monkeypatch.setattr(
        investor_autosync, "maybe_autosync_holdings", lambda db: llamadas.append("auto")
    )
    servicio = Mock()
    servicio.latest_holdings.return_value = {"holdings": []}
    monkeypatch.setattr(
        ownership_route, "ManagerHoldingIngestionService", lambda: servicio
    )
    result = ownership_route.manager_holdings(cik="X", db=Mock())
    assert llamadas == ["auto"]
    assert result == {"holdings": []}


def test_institutions_compania_desconocida_es_404(monkeypatch):
    from app.services import institutional_holders

    monkeypatch.setattr(institutional_holders, "institutional_holders", lambda db, t: None)
    with pytest.raises(HTTPException) as exc:
        ownership_route.institutional_holders_route("NOPE", db=Mock())
    assert exc.value.status_code == 404


def test_institutions_devuelve_los_tenedores(monkeypatch):
    from app.services import institutional_holders

    monkeypatch.setattr(
        institutional_holders,
        "institutional_holders",
        lambda db, t: {"ticker": t, "holders": []},
    )
    result = ownership_route.institutional_holders_route("ASTS", db=Mock())
    assert result["ticker"] == "ASTS"


def test_funds_compania_desconocida_es_404(monkeypatch):
    from app.services import fund_holders

    monkeypatch.setattr(fund_holders, "fund_holders", lambda db, t: None)
    with pytest.raises(HTTPException) as exc:
        ownership_route.fund_holders_route("NOPE", db=Mock())
    assert exc.value.status_code == 404


def test_funds_devuelve_los_fondos(monkeypatch):
    from app.services import fund_holders

    monkeypatch.setattr(
        fund_holders, "fund_holders", lambda db, t: {"ticker": t, "funds": []}
    )
    result = ownership_route.fund_holders_route("ASTS", db=Mock())
    assert result["ticker"] == "ASTS"


# --- propicks_radar: senal sin compania en catalogo ------------------------


def test_radar_senal_huerfana_cuenta_en_evaluadas_no_en_items(monkeypatch):
    """Una senal cuya compania ya no existe se salta: ni item ni invalid."""
    monkeypatch.setattr(
        radar_route,
        "latest_public_signals",
        lambda db, as_of: [
            {"company_id": 999, "payload": {"status": "ok"}, "scan_date": "2026-10-30", "change": 0}
        ],
    )
    monkeypatch.setattr(radar_route, "quality_for_companies", lambda db, ids, as_of: {})
    monkeypatch.setattr(radar_route, "universe_company_ids", lambda db: [999])
    monkeypatch.setattr(
        radar_route,
        "page_candidates",
        lambda rows, **kw: {"page": 1, "total": 0, "has_more": False, "items": []},
    )
    db = Mock()
    db.scalars.return_value.all.return_value = []  # catalogo vacio
    result = radar_route.list_radar_opportunities(
        page=1, level=None, sector=None, outside_tracked=False, quality=None, db=db
    )
    assert result["items"] == []
    assert result["coverage"]["evaluated"] == 1
    assert result["coverage"]["ok"] == 0
    assert result["coverage"]["invalid"] == 0
