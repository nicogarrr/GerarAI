"""filings.xbrl.org sin 429 en cadena: espaciado, Retry-After y un solo build por semana.

Lectura de dead-letter en prod (1-nov-2026): 14 refresh_esef_fundamentals con
«EsefError 429 Too Many Requests» en /api/filings. El cron semanal encola el
job para TODOS los tenants a la vez (sab 6:30) y cada uno reconstruia el
mismo snapshot global con cientos de peticiones a 1 s de distancia; el 429
subia como EsefError, se reintentaba 2 veces a 60 s y acababa en dead-letter.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import dramatiq
import httpx
import pytest

from app.services.connectors import esef
from app.services.connectors.esef import EsefClient, EsefError, EsefRateLimited
from app.workers import dramatiq_app


@pytest.fixture
def waits(monkeypatch):
    slept: list[float] = []

    async def _pause(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(esef, "_pause", _pause)
    monkeypatch.setattr(esef, "_MIN_INTERVAL_S", 0)
    return slept


def _client(responses):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return responses.pop(0) if len(responses) > 1 else responses[0]

    transport = httpx.MockTransport(handler)
    return EsefClient(client=httpx.AsyncClient(transport=transport, base_url=esef.ESEF_BASE_URL)), calls


def test_espaciado_entre_peticiones_es_conservador():
    assert esef._MIN_INTERVAL_S >= 2.0


def test_429_con_retry_after_espera_y_reintenta(waits):
    ok = httpx.Response(200, json={"ok": True})
    client, calls = _client([httpx.Response(429, headers={"Retry-After": "7"}), ok])
    assert asyncio.run(client._get_json("/api/filings")) == {"ok": True}
    assert calls["n"] == 2
    assert waits and waits[0] >= 7


def test_429_sin_cabecera_usa_backoff_creciente(waits):
    ok = httpx.Response(200, json={"ok": True})
    client, _ = _client([httpx.Response(429), httpx.Response(429), ok])
    asyncio.run(client._get_json("/api/filings"))
    assert len(waits) == 2
    assert waits[1] > waits[0] > 0


def test_429_persistente_sube_tipado_con_la_ventana(waits):
    client, calls = _client([httpx.Response(429, headers={"Retry-After": "5"})])
    with pytest.raises(EsefRateLimited) as caught:
        asyncio.run(client._get_json("/api/filings"))
    assert isinstance(caught.value, EsefError)  # el contrato EsefError se mantiene
    assert calls["n"] == 1 + esef._MAX_429_RETRIES
    assert caught.value.retry_after >= 5


def test_ventana_larga_no_se_duerme_en_linea(waits):
    client, calls = _client([httpx.Response(429, headers={"Retry-After": "3600"})])
    with pytest.raises(EsefRateLimited) as caught:
        asyncio.run(client._get_json("/api/filings"))
    assert calls["n"] == 1
    assert waits == []
    assert caught.value.retry_after == 3600


# ---------- Retry-After: solo delay-seconds finito y no negativo ----------

# RFC 9110 10.2.3: Retry-After es delay-seconds (entero >= 0) o HTTP-date.
# Un servidor roto u hostil puede mandar "inf"/"nan": float() los acepta y una
# espera infinita o NaN colgaria el worker. Se ignoran y cae al backoff.


@pytest.mark.parametrize("raw", ["inf", "-inf", "Infinity", "-Infinity", "nan", "NaN"])
def test_retry_after_no_finito_se_ignora(raw):
    resp = httpx.Response(429, headers={"Retry-After": raw})
    assert esef._retry_after_header(resp) is None


@pytest.mark.parametrize("raw", ["-5", "-0.5", "-1e3"])
def test_retry_after_negativo_se_ignora(raw):
    resp = httpx.Response(429, headers={"Retry-After": raw})
    assert esef._retry_after_header(resp) is None


@pytest.mark.parametrize("raw,esperado", [("0", 0.0), ("7", 7.0), ("2.5", 2.5), ("3600", 3600.0)])
def test_retry_after_valido_se_respeta(raw, esperado):
    resp = httpx.Response(429, headers={"Retry-After": raw})
    assert esef._retry_after_header(resp) == esperado


def test_429_con_retry_after_infinito_cae_al_backoff_y_reintenta(waits):
    ok = httpx.Response(200, json={"ok": True})
    client, calls = _client([httpx.Response(429, headers={"Retry-After": "inf"}), ok])
    assert asyncio.run(client._get_json("/api/filings")) == {"ok": True}
    assert calls["n"] == 2
    # backoff exponencial del primer intento (10-12 s), nunca una espera infinita
    assert len(waits) == 1
    assert 10.0 <= waits[0] <= 13.0


# ---------- actor ----------


@pytest.fixture
def esef_actor(monkeypatch, tmp_path):
    import app.core.config as config

    class _DB:
        def rollback(self):
            pass

        def close(self):
            pass

        def commit(self):
            pass

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: _DB())
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(esef_snapshot_dir=str(tmp_path)))
    sent: list[dict] = []
    monkeypatch.setattr(dramatiq_app.refresh_esef_fundamentals, "send", lambda *a, **k: sent.append(k))
    scripts_dir = str(Path(dramatiq_app.__file__).resolve().parents[2] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import build_esef_snapshots

    builds = {"n": 0}

    def _install(build):
        async def _build(*args, **kwargs):
            builds["n"] += 1
            return await build(*args, **kwargs)

        monkeypatch.setattr(build_esef_snapshots, "build", _build)

    return SimpleNamespace(tmp=tmp_path, sent=sent, builds=builds, install=_install)


def _current(monkeypatch, retries):
    message = SimpleNamespace(
        options={"retries": retries},
        actor_name="refresh_esef_fundamentals",
        message_timestamp=time.time() * 1000,
    )
    monkeypatch.setattr(dramatiq_app.CurrentMessage, "get_current_message", classmethod(lambda cls: message))


def test_build_con_429_reencola_con_espera_larga(monkeypatch, esef_actor):
    async def _rate_limited(*args, **kwargs):
        raise EsefRateLimited("/api/filings", 30.0)

    esef_actor.install(_rate_limited)
    _current(monkeypatch, retries=0)
    with pytest.raises(dramatiq.Retry) as caught:
        dramatiq_app.refresh_esef_fundamentals.fn(1, "u1")
    assert caught.value.delay >= dramatiq_app.ESEF_RETRY_BASE_SECONDS * 1000


def test_build_con_429_en_el_ultimo_intento_no_va_a_dead_letter(monkeypatch, esef_actor):
    async def _rate_limited(*args, **kwargs):
        raise EsefRateLimited("/api/filings", 30.0)

    esef_actor.install(_rate_limited)
    _current(monkeypatch, retries=dramatiq_app.refresh_esef_fundamentals.options["max_retries"])
    result = dramatiq_app.refresh_esef_fundamentals.fn(1, "u1")
    assert result["status"] == "skipped"
    assert result["reason"] == "rate_limited_retries_exhausted"


def test_snapshot_fresco_de_esta_semana_no_se_reconstruye(esef_actor):
    """El 2.o tenant del cron reutiliza el snapshot global recien hecho."""

    async def _never(*args, **kwargs):
        raise AssertionError("no debe volver a pedir filings.xbrl.org")

    esef_actor.install(_never)
    manifest = {"issuers": {"L1": {}}, "unresolved": {}, "fetched_at": date.today().isoformat()}
    (esef_actor.tmp / "manifest.json").write_text(json.dumps(manifest))
    result = dramatiq_app.refresh_esef_fundamentals.fn(2, "u2")
    assert result["status"] == "ok"
    assert result["reason"] == "snapshot_fresh"
    assert esef_actor.builds["n"] == 0
    assert esef_actor.sent == [{"phase": "ingest", "cursor": 0}]


def test_snapshot_viejo_si_se_reconstruye(esef_actor):
    async def _build(*args, **kwargs):
        return {"issuers": {}, "unresolved": {}}

    esef_actor.install(_build)
    old = (date.today() - timedelta(days=7)).isoformat()
    (esef_actor.tmp / "manifest.json").write_text(json.dumps({"issuers": {}, "fetched_at": old}))
    result = dramatiq_app.refresh_esef_fundamentals.fn(2, "u2")
    assert result["status"] == "ok"
    assert esef_actor.builds["n"] == 1
