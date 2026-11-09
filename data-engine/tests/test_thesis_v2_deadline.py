"""Plazo TOTAL de la tesis v2 (tesis-3: CPT y AMZN, una llamada de 1.901 s pese al tope de 600/900 s).

El tope por llamada del adaptador vive dentro de su event loop: no ve lo que se acumula fuera (dos partes,
reintentos del validador) ni un loop congelado. La redacción tiene ahora un plazo total repartido por parte;
la parte que lo agota queda como N/D («tiempo agotado») y el resto de la tesis se conserva. Un 402 o un 429
del proveedor para la tesis sin reintentar y se ve en el job. Todo con razonadores simulados: sin red."""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app.llm.errors import ProviderHTTPError, ProviderTransportError
from app.services.expert_team import thesis_v2 as T
from tests.test_thesis_v2 import _ctx

GOOD = "El precio de {{punto.precio}} y una TIR base de {{esc.base.tir10}}."


def _keys(user: str) -> list[str]:
    return [s["clave"] for s in json.loads(user)["secciones"]]


def _good(user: str) -> str:
    return json.dumps({"sections": dict.fromkeys(_keys(user), GOOD), "probabilidades": "sesgo_bajista",
                       "probabilidades_razon": "riesgo"})


def _parts(ctx) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"a": [], "b": []}
    for k, _title, part, _tn in T.active_sections(ctx):
        out[part].append(k)
    return out


def _run(coro, limit: float = 10.0):
    t0 = time.monotonic()
    res = asyncio.run(asyncio.wait_for(coro, limit))
    return res, time.monotonic() - t0


def test_proveedor_colgado_corta_en_el_plazo_total(monkeypatch):
    monkeypatch.setattr(T, "TOTAL_DEADLINE_SECONDS", 0.4)
    ctx = _ctx()

    async def colgado(system, user, max_tokens, task):
        await asyncio.sleep(3600)

    res, secs = _run(T.write_thesis(reasoner=colgado, ctx=ctx))
    assert secs < 1.0  # antes: sin tope en la redacción, el job esperaba lo que tardase el proveedor
    assert res.status == "timeout" and not res.sections
    assert set(res.missing) == {k for k, *_ in T.active_sections(ctx)}
    assert set(res.missing.values()) == {T.TIMEOUT_REASON}


def test_parte_lenta_queda_nd_y_no_vacia_la_tesis(monkeypatch):
    monkeypatch.setattr(T, "TOTAL_DEADLINE_SECONDS", 0.6)
    ctx = _ctx()
    parts = _parts(ctx)

    async def reasoner(system, user, max_tokens, task):
        if task.endswith("_b"):
            await asyncio.sleep(3600)
        return _good(user)

    res, secs = _run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert secs < 1.2
    assert res.status == "partial"
    assert set(res.sections) == set(parts["a"])  # la parte a, ya escrita, se conserva
    assert set(res.missing) == set(parts["b"])
    assert any(T.TIMEOUT_REASON in p for p in res.problems)


def test_loop_congelado_no_empieza_otra_llamada(monkeypatch):
    """Tesis-3: el loop estuvo parado (E/S del disco) y el wait_for del adaptador no pudo saltar. La respuesta
    que llega tarde se aprovecha, pero pasado el plazo no se lanza ninguna llamada más."""
    monkeypatch.setattr(T, "TOTAL_DEADLINE_SECONDS", 0.3)
    ctx = _ctx()
    parts = _parts(ctx)
    calls: list[str] = []

    async def bloquea_el_loop(system, user, max_tokens, task):
        calls.append(task)
        time.sleep(0.45)  # síncrono a propósito: ningún temporizador del loop corre mientras tanto
        return _good(user)

    res, _ = _run(T.write_thesis(reasoner=bloquea_el_loop, ctx=ctx))
    assert calls == ["expert_team.tesis_v2_a"]
    assert set(res.sections) == set(parts["a"])
    assert set(res.missing) == set(parts["b"]) and res.status == "partial"


def test_reintentos_no_se_acumulan_pasado_el_plazo(monkeypatch):
    monkeypatch.setattr(T, "TOTAL_DEADLINE_SECONDS", 0.5)
    monkeypatch.setattr(T, "MAX_ATTEMPTS", 50)
    ctx = _ctx()
    calls: list[str] = []

    async def basura_lenta(system, user, max_tokens, task):
        calls.append(task)
        await asyncio.sleep(0.1)
        return "no es json"

    res, secs = _run(T.write_thesis(reasoner=basura_lenta, ctx=ctx))
    assert secs < 0.9
    assert len(calls) <= 7  # 0,5 s / 0,1 s por llamada, y no 50 × 2 partes
    assert res.status == "timeout" and set(res.missing.values()) == {T.TIMEOUT_REASON}


def test_timeout_del_adaptador_cuenta_como_tiempo_agotado(monkeypatch):
    ctx = _ctx()
    parts = _parts(ctx)

    async def reasoner(system, user, max_tokens, task):
        if task.endswith("_b"):
            raise ProviderTransportError("opencode-go", "timeout", 1)
        return _good(user)

    res, _ = _run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert res.status == "partial" and set(res.missing) == set(parts["b"])
    assert set(res.missing.values()) == {T.TIMEOUT_REASON}


@pytest.mark.parametrize("code", [402, 429])
def test_402_y_429_paran_sin_reintentar(monkeypatch, code):
    monkeypatch.setattr(T, "MAX_ATTEMPTS", 5)
    ctx = _ctx()
    calls: list[str] = []

    async def sin_saldo(system, user, max_tokens, task):
        calls.append(task)
        raise ProviderHTTPError("opencode-go", code)

    res, _ = _run(T.write_thesis(reasoner=sin_saldo, ctx=ctx))
    assert calls == ["expert_team.tesis_v2_a"]  # ni reintento ni parte b
    assert res.status == "provider_stopped" and res.stopped == T.STOP_HTTP[code]
    assert set(res.missing) == {k for k, *_ in T.active_sections(ctx)}
    assert f"HTTP {code}" in res.problems[0]


def test_402_en_la_parte_b_conserva_la_a(monkeypatch):
    ctx = _ctx()
    parts = _parts(ctx)

    async def reasoner(system, user, max_tokens, task):
        if task.endswith("_b"):
            raise ProviderHTTPError("opencode-go", 402)
        return _good(user)

    res, _ = _run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert res.status == "partial" and res.stopped == T.STOP_HTTP[402]
    assert set(res.sections) == set(parts["a"]) and set(res.missing) == set(parts["b"])


def test_402_envuelto_en_otra_excepcion_tambien_para():
    try:
        try:
            raise ProviderHTTPError("opencode-go", 402)
        except ProviderHTTPError as inner:
            raise RuntimeError("envoltorio") from inner
    except RuntimeError as exc:
        assert T.provider_stop_reason(exc) == T.STOP_HTTP[402]
    assert T.provider_stop_reason(ProviderHTTPError("x", 500)) is None


def test_error_en_el_reintento_no_borra_lo_ya_validado(monkeypatch):
    monkeypatch.setattr(T, "MAX_ATTEMPTS", 2)
    ctx = _ctx()
    seen: list[int] = []

    async def reasoner(system, user, max_tokens, task):
        seen.append(1)
        if len(seen) == 1:
            return json.dumps({"sections": dict.fromkeys(_keys(user), GOOD) | {"historial": "Crece un 12 %."}})
        raise RuntimeError("caída")

    res, _ = _run(T.write_thesis(reasoner=reasoner, ctx=ctx))
    assert res.status == "error"
    assert res.sections.get("introduccion") == GOOD and "historial" not in res.sections


def test_present_pinta_nd_con_su_motivo_y_lo_avisa():
    ctx = _ctx()
    parts = _parts(ctx)
    doc = {"status": "partial", "sections": dict.fromkeys(parts["a"], GOOD), "fingerprint": "x",
           "missing": dict.fromkeys(parts["b"], T.TIMEOUT_REASON), "stopped": None}
    out = T.present(ctx, doc, T.thesis_markers(ctx))
    texts = {s["key"]: s["text"] for s in out["sections"]}
    assert all(texts[k] == "N/D (tiempo agotado)" for k in parts["b"])
    assert all(texts[k] and not texts[k].startswith("N/D") for k in parts["a"])
    assert any(w.startswith(f"tesis incompleta: {len(parts['b'])} de ") for w in out["warnings"])
    assert "stopped" not in out  # sin parada del proveedor, el JSON no cambia

    stopped = T.present(ctx, {**doc, "stopped": T.STOP_HTTP[402],
                              "missing": dict.fromkeys(parts["b"], T.STOP_HTTP[402])}, T.thesis_markers(ctx))
    assert stopped["stopped"] == T.STOP_HTTP[402]
    assert "tesis v2 parada sin reintentar: proveedor del modelo: HTTP 402 (sin saldo)" in stopped["warnings"]


def test_present_sin_huecos_no_cambia():
    ctx = _ctx()
    doc = {"status": "ok", "sections": {k: GOOD for k, *_ in T.active_sections(ctx)}, "fingerprint": "x"}
    out = T.present(ctx, doc, T.thesis_markers(ctx))
    assert not any(w.startswith("tesis incompleta") for w in out["warnings"])
    assert all(not s["text"].startswith("N/D") for s in out["sections"])


def test_regenerar_solo_pide_lo_que_quedo_nd():
    ctx = _ctx()
    parts = _parts(ctx)
    fp = T.thesis_fingerprint(ctx)
    asked: list[list[str]] = []

    async def reasoner(system, user, max_tokens, task):
        asked.append(_keys(user))
        return _good(user)

    cached = {"fingerprint": fp, "status": "partial", "sections": dict.fromkeys(parts["a"], GOOD),
              "missing": dict.fromkeys(parts["b"], T.TIMEOUT_REASON)}
    res, _ = _run(T.write_thesis(reasoner=reasoner, ctx=ctx, cached=cached))
    assert asked == [parts["b"]]
    assert res.status == "ok" and not res.missing


def test_el_job_queda_degradado_y_visible(monkeypatch):
    run = SimpleNamespace(result_payload={"thesis_id": 7})

    class Db:
        info = {"tenant_id": 1}

        def get(self, model, rid):
            return run

        def commit(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr("app.services.company_resolver.resolve_company", lambda db, t: SimpleNamespace(ticker=t))
    monkeypatch.setattr(T, "generate_thesis_v2", lambda db, c, tenant_id=None: {
        "status": "provider_stopped", "llm_calls": 1, "fingerprint": "f", "stopped": T.STOP_HTTP[402],
        "sections": [{"key": "introduccion", "text": "N/D (proveedor del modelo: HTTP 402 (sin saldo))"}]})
    out = T.attach_to_thesis_run(Db(), 5, "CPT")  # type: ignore[arg-type]
    assert out["status"] == "provider_stopped" and out["missing"] == ["introduccion"]
    assert run.result_payload["degraded"] == {"step": "thesis_v2", "reason": T.STOP_HTTP[402]}
    assert run.result_payload["thesis_id"] == 7  # lo demás del run no se toca


def test_el_puente_espera_el_plazo_total_por_defecto(monkeypatch):
    seen: dict = {}

    def fake_run(coro, timeout=None):
        seen["timeout"] = timeout
        coro.close()
        return T.ThesisResult(status="timeout")

    monkeypatch.setattr("app.services.async_bridge.run_from_any_context", fake_run)
    monkeypatch.setattr(T, "build_context", lambda *a, **k: SimpleNamespace(valuation={"status": "ok"}))
    monkeypatch.setattr(T, "_latest_row", lambda db, c: None)
    monkeypatch.setattr(T, "thesis_markers", lambda ctx: (_ for _ in ()).throw(StopIteration))
    with pytest.raises(StopIteration):
        T.generate_thesis_v2(SimpleNamespace(info={}), SimpleNamespace(ticker="X", id=1),  # type: ignore[arg-type]
                             reasoner=lambda *a: None, tenant_id=1)  # type: ignore[arg-type]
    assert seen["timeout"] > T.TOTAL_DEADLINE_SECONDS
