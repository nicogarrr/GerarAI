"""edgartools_client: identidad, throttle async doblado, breaker, salud SEC y
snapshot en disco (aristas). Sin red: la libreria edgar y el registry de salud
se doblan; el snapshot se monta en tmp_path con ficheros reales.

Reloj doblado en wait_async (nunca tiempo real).

No se prueba aqui: throttle/breaker con reloj real ni http_status_from_error
desde texto (cubiertos en test_edgartools_offline.py), ni la seguridad de
symlinks (test_edgartools_snapshot_path_safety.py). La rama 228->230 de
http_status_from_error no se testea: _STATUS_RE (\\b(4\\d\\d|5\\d\\d)\\b) solo
produce 4xx/5xx, asi que el guard de rango no puede fallar por esa via.
El cierre defensivo de fd ante OSError posterior a os.open en _open_verified
(lineas 373-376) tampoco: la unica fuente de ese OSError es os.fstat, y
parchear os.fstat global rompe la captura de pytest (lo llama a mitad de test).
"""

from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

import pytest

import app.services.connectors.edgartools_client as client

# -- Identidad ---------------------------------------------------------------------


def test_resolve_identity_candidate_con_email_pasa(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(
            edgartools_identity="team@example.com", sec_user_agent=None
        ),
    )
    assert client.resolve_identity() == "team@example.com"


def test_ensure_identity_devuelve_none_si_set_identity_falla(monkeypatch):
    import edgar

    def _set_identity_que_falla(identity):
        raise RuntimeError("edgar roto")

    monkeypatch.setattr(edgar, "set_identity", _set_identity_que_falla)
    assert client.ensure_identity() is None


# -- Throttle async (reloj doblado) ---------------------------------------------------


def test_wait_async_espera_lo_justo(monkeypatch):
    throttle = client.EdgarToolsThrottle(requests_per_second=10)
    sleeps = []

    async def _sleep_falso(segundos):
        sleeps.append(segundos)

    monkeypatch.setattr(asyncio, "sleep", _sleep_falso)
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)
    throttle._last_at = 99.95
    asyncio.run(throttle.wait_async())
    assert sleeps == [pytest.approx(0.05)]
    assert throttle._last_at == 100.0


def test_wait_async_no_duerme_si_ya_paso(monkeypatch):
    throttle = client.EdgarToolsThrottle(requests_per_second=10)
    sleeps = []

    async def _sleep_falso(segundos):
        sleeps.append(segundos)

    monkeypatch.setattr(asyncio, "sleep", _sleep_falso)
    monkeypatch.setattr(time, "monotonic", lambda: 101.0)
    throttle._last_at = 100.0
    asyncio.run(throttle.wait_async())
    assert sleeps == []
    assert throttle._last_at == 101.0


def test_wrappers_del_throttle_por_defecto(monkeypatch):
    assert client.default_throttle() is client._default_throttle
    llamadas = []
    monkeypatch.setattr(
        client._default_throttle, "wait_sync", lambda: llamadas.append("sync")
    )

    async def _wait_async_falso():
        llamadas.append("async")

    monkeypatch.setattr(client._default_throttle, "wait_async", _wait_async_falso)
    client.throttle_sync()
    asyncio.run(client.throttle_async())
    assert llamadas == ["sync", "async"]


# -- Breaker y status ------------------------------------------------------------------


def test_record_success_resetea_la_racha(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    breaker = client.RateLimitBreaker(window_s=600.0, streak_limit=5, cooldown_s=60.0)
    assert breaker.record_429() is False
    assert breaker._streak == 1
    breaker.record_success()
    assert breaker._streak == 0


def test_http_status_desde_response_status_code():
    exc = RuntimeError("boom sin codigo")
    exc.response = SimpleNamespace(status_code=503)
    assert client.http_status_from_error(exc) == 503


def test_http_status_recorre_la_cadena_de_causas():
    causa = ValueError("SEC EDGAR request failed (502 Bad Gateway)")
    exc = RuntimeError("boom sin codigo")
    exc.__cause__ = causa
    assert client.http_status_from_error(exc) == 502


# -- Salud SEC en el registry ------------------------------------------------------------


class _RegistryEspia:
    def __init__(self):
        self.failures = []
        self.successes = []

    def record_failure(self, key, reason):
        self.failures.append((key, reason))

    def record_success(self, key):
        self.successes.append(key)


def test_report_sec_failure_registry_por_defecto_y_http_generico(monkeypatch):
    registry = _RegistryEspia()
    monkeypatch.setattr(
        "app.services.data_source_health.get_data_source_registry", lambda: registry
    )
    assert client.report_sec_failure_to_health(503) is True
    assert registry.failures == [("sec_edgar", "HTTP 503")]


def test_report_sec_success_registry_por_defecto(monkeypatch):
    registry = _RegistryEspia()
    monkeypatch.setattr(
        "app.services.data_source_health.get_data_source_registry", lambda: registry
    )
    client.report_sec_success_to_health()
    assert registry.successes == ["sec_edgar"]


# -- Snapshot en disco --------------------------------------------------------------------


def test_snapshot_root_rutas(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(edgartools_snapshot_dir=""),
    )
    assert client.snapshot_root() is None
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(edgartools_snapshot_dir=str(tmp_path / "no_existe")),
    )
    assert client.snapshot_root() is None
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(edgartools_snapshot_dir=str(tmp_path)),
    )
    assert client.snapshot_root() == tmp_path


def test_manifest_cik_tickers_no_dict(tmp_path):
    (tmp_path / "manifest.json").write_text('{"tickers": "no-es-dict"}')
    assert client.manifest_cik("AAPL", tmp_path) is None


def test_resolve_within_oserror_devuelve_none(monkeypatch, tmp_path):
    def _realpath_roto(path):
        raise OSError("fs roto")

    monkeypatch.setattr(os.path, "realpath", _realpath_roto)
    assert client._resolve_within(tmp_path, tmp_path / "x.json") is None


def test_open_verified_directorio_padre_ausente(tmp_path):
    # La ruta resuelve dentro del root pero el directorio padre no existe.
    assert client._open_verified(tmp_path, tmp_path / "sub" / "f.json") is None


def test_read_json_invalido_devuelve_none(tmp_path):
    (tmp_path / "manifest.json").write_text("{json corrupto")
    assert client.read_manifest(tmp_path) is None


def test_read_json_fdopen_oserror(monkeypatch, tmp_path):
    (tmp_path / "manifest.json").write_text("{}")

    def _fdopen_roto(fd, encoding=None):
        raise OSError("fdopen roto")

    monkeypatch.setattr(os, "fdopen", _fdopen_roto)
    assert client.read_manifest(tmp_path) is None


def test_readers_sin_snapshot_configurado(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(edgartools_snapshot_dir=""),
    )
    assert client.read_companyfacts("0000320193") is None
    assert client.read_submissions("0000320193") is None
    assert client.read_filing_xml("0000320193-26-000001", "form4.xml") is None


def test_read_filing_xml_fdopen_y_read_oserror(monkeypatch, tmp_path):
    carpeta = tmp_path / "filings" / "000123456726000001"
    carpeta.mkdir(parents=True)
    (carpeta / "form4.xml").write_text("<xml/>")

    def _fdopen_roto(fd, encoding=None):
        raise OSError("fdopen roto")

    monkeypatch.setattr(os, "fdopen", _fdopen_roto)
    assert client.read_filing_xml("0001234567-26-000001", "form4.xml", tmp_path) is None

    class _FhQueFalla:
        """Doble que falla al leer; cierra el fd real recibido para no fugarselo
        al proceso (produccion no lo cierra cuando fdopen "tiene exito")."""

        def __init__(self, fd):
            self._fd = fd

        def read(self):
            raise OSError("read roto")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            os.close(self._fd)
            return False

    monkeypatch.setattr(os, "fdopen", lambda fd, encoding=None: _FhQueFalla(fd))
    assert client.read_filing_xml("0001234567-26-000001", "form4.xml", tmp_path) is None
