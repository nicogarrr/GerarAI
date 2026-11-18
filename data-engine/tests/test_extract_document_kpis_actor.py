"""extract_document_kpis: ramas del cuerpo del actor sin test directo.

Los tests vecinos (backpressure, helpers, broker acotado) solo stubban ``.send``.
Aqui se ejecuta el cuerpo con sesion, documento y servicio falsos y se fijan:
- ok / partial (deterministic-only con metricas sin resolver) y limpieza de la marca de diferido;
- documento inexistente -> error estructurado, rollback y cierre de sesion;
- limite diario de llamadas KPI -> deferred hasta medianoche UTC, sin error;
- HTTP 402 del proveedor -> deferred con ventana y SIN gastar el intento;
- HTTP 429 -> reencolado con backoff (dramatiq.Retry) y, agotados, skipped sin dead-letter;
- 401 -> fallo permanente estructurado (no se difiere).

Run from data-engine/:
    pytest tests/test_extract_document_kpis_actor.py -v
"""

from __future__ import annotations

import dramatiq
import pytest

from app.llm.errors import ProviderHTTPError
from app.services import kpi_extraction_service
from app.services.kpi_call_quota import KPIDailyDeferred
from app.workers import dramatiq_app as worker
from app.workers import rate_limit_retry


class _Doc:
    def __init__(self, meta=None):
        self.metadata_ = meta or {}


class _DB:
    def __init__(self, doc):
        self.doc = doc
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def get(self, model, pk):
        return self.doc

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


class _Cand:
    def __init__(self, id_):
        self.id = id_


@pytest.fixture()
def env(monkeypatch):
    class E:
        db = _DB(_Doc())
        result = []
        error = None

    e = E()

    class _Service:
        async def extract_document(self, db, document):
            if e.error:
                raise e.error
            return e.result

    monkeypatch.setattr(kpi_extraction_service, "KPIExtractionService", _Service)
    monkeypatch.setattr(worker, "_session", lambda tenant, user: e.db)
    monkeypatch.setattr(worker.time, "time", lambda: 1_700_000_000)
    return e


def _call():
    return worker.extract_document_kpis.fn(9, tenant_id=1, user_id="u")


def test_ok_devuelve_candidatos_y_limpia_marca_de_diferido(env):
    env.db = _DB(_Doc({worker.KPI_DEFERRED_KEY: {"attempts": 1}, "otro": 1}))
    env.result = [_Cand(4), _Cand(5)]

    out = _call()

    assert out == {
        "status": "ok",
        "mode": "auto",
        "unresolved_metrics": [],
        "document_id": 9,
        "candidate_ids": [4, 5],
        "candidates": 2,
    }
    assert worker.KPI_DEFERRED_KEY not in env.db.doc.metadata_
    assert env.db.doc.metadata_["otro"] == 1
    assert env.db.commits == 1
    assert env.db.closed == 1


def test_deterministic_only_con_metricas_sin_resolver_es_partial(env):
    env.db = _DB(_Doc({"kpi_deterministic": {"mode": "deterministic-only", "unresolved_metrics": ["fcf"]}}))
    env.result = []

    out = _call()

    assert out["status"] == "partial"
    assert out["mode"] == "deterministic-only"
    assert out["unresolved_metrics"] == ["fcf"]
    assert out["candidates"] == 0
    assert env.db.commits == 0  # sin marca de diferido no hay nada que limpiar


def test_documento_inexistente_error_estructurado_y_cierre(env):
    env.db = _DB(None)

    out = _call()

    assert out["status"] == "error"
    assert out["actor"] == "extract_document_kpis"
    assert env.db.rollbacks == 1
    assert env.db.closed == 1


def test_limite_diario_difiere_hasta_medianoche_utc(env):
    env.db = _DB(_Doc())
    env.error = KPIDailyDeferred("cap")

    out = _call()

    assert out == {"status": "deferred", "reason": "daily_call_limit", "document_id": 9}
    meta = env.db.doc.metadata_
    assert meta[worker.KPI_DEFERRED_KEY] == {"attempts": 0, "not_before": (1_700_000_000 // 86400 + 1) * 86400}
    assert meta["kpi_daily_deferred"]["reason"] == "daily_call_limit"
    assert env.db.commits == 1
    assert env.db.closed == 1


def test_http_402_difiere_sin_gastar_el_intento(env):
    env.db = _DB(_Doc({worker.KPI_DEFERRED_KEY: {"attempts": 3, "not_before": 1}}))
    env.error = ProviderHTTPError("opencode-go", 402)

    out = _call()

    assert out == {"status": "deferred", "reason": "provider_payment_required", "document_id": 9}
    deferred = env.db.doc.metadata_[worker.KPI_DEFERRED_KEY]
    assert deferred["attempts"] == 2  # el intento ya persistido se devuelve
    assert deferred["not_before"] == 1_700_000_000 + worker.KPI_PAYMENT_DEFER_SECONDS
    assert env.db.doc.metadata_["kpi_provider_deferred"]["reason"] == "provider_payment_required"
    assert env.db.closed == 1


def test_http_402_sin_intentos_previos_no_baja_de_cero(env):
    env.db = _DB(_Doc())
    env.error = ProviderHTTPError("opencode-go", 402)

    _call()

    assert env.db.doc.metadata_[worker.KPI_DEFERRED_KEY]["attempts"] == 0


def test_http_429_reencola_con_backoff(env, monkeypatch):
    env.db = _DB(_Doc())
    env.error = ProviderHTTPError("opencode-go", 429)
    monkeypatch.setattr(rate_limit_retry, "retry_budget", lambda: (0, 2))

    with pytest.raises(dramatiq.Retry) as info:
        _call()

    assert info.value.delay >= int(worker.KPI_RATE_LIMIT_BASE_SECONDS * 1000 * 0.5)
    assert info.value.delay <= int(worker.KPI_RATE_LIMIT_CAP_SECONDS * 1000 * 1.5)
    assert env.db.closed == 1


def test_http_429_con_reintentos_agotados_skipped_sin_dead_letter(env, monkeypatch):
    env.db = _DB(_Doc())
    env.error = ProviderHTTPError("opencode-go", 429)
    monkeypatch.setattr(rate_limit_retry, "retry_budget", lambda: (2, 2))

    out = _call()

    assert out["status"] == "skipped"
    assert out["reason"] == "rate_limited_retries_exhausted"
    assert out["document_id"] == 9
    assert env.db.closed == 1


def test_http_401_es_fallo_permanente_no_se_difiere(env):
    env.db = _DB(_Doc())
    env.error = ProviderHTTPError("opencode-go", 401)

    out = _call()

    assert out["status"] == "error"
    assert worker.KPI_DEFERRED_KEY not in env.db.doc.metadata_
    assert env.db.closed == 1


def test_deterministic_only_sin_metricas_sin_resolver_es_ok(env):
    env.db = _DB(_Doc({"kpi_deterministic": {"mode": "deterministic-only", "unresolved_metrics": []}}))
    env.result = [_Cand(1)]

    out = _call()

    assert out["status"] == "ok"
    assert out["mode"] == "deterministic-only"
    assert out["unresolved_metrics"] == []


def test_metricas_sin_resolver_fuera_de_deterministic_only_es_ok(env):
    # Solo el modo deterministic-only degrada a partial: con LLM el hueco no es un fallo.
    env.db = _DB(_Doc({"kpi_deterministic": {"mode": "auto", "unresolved_metrics": ["fcf"]}}))
    env.result = [_Cand(1)]

    out = _call()

    assert out["status"] == "ok"
    assert out["mode"] == "auto"
    assert out["unresolved_metrics"] == ["fcf"]
