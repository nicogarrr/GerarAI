"""Bordes de sec_edgar: user-agent, snapshot, mirror HF y errores de _get_json.

Cero red real: las respuestas salen de httpx.MockTransport o de clientes
httpx.AsyncClient doblados; el manifest/documento del mirror HF van doblados
en el namespace del modulo. El registro de salud (data_source_health) va
espiado con conteos y mensajes exactos; pacer/rate_limited doblados en
sec_pacing (imports vivos dentro de _get_json); asyncio.sleep doblado con el
truco SimpleNamespace de la casa (no contaminar el modulo asyncio global).

NO prueba (declarado):
- Arco 170->218 y lineas 219-220 de _get_json (salir del bucle con
  direct_error=None): inalcanzable. El continue del 429 exige
  attempt < max_retries (185), asi que la ultima iteracion cae en
  raise_for_status y sale por 203-206; todo camino del cuerpo termina en
  raise, return (217) o break (202) con direct_error asignado. El bucle no
  puede completarse con normalidad. Acotado a max_retries entero >= 0
  (contrato de la funcion), no a llamadas fuera de contrato.
"""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest

from app.services.connectors import sec_edgar, sec_pacing
from app.services.connectors.sec_edgar import (
    BROWSER_USER_AGENT,
    COMPANYFACTS_URL,
    DEFAULT_CONTACT,
)

CIK_URL = COMPANYFACTS_URL.format(cik="0000320193")
DATASET = "org/mi-dataset"
MIRROR_URL = f"https://huggingface.co/datasets/{DATASET}/resolve/main/companyfacts/CIK0000320193.json"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def _settings_frescos():
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def red_doblada(monkeypatch):
    """Espias comunes de _get_json: registry, pacer, rate_limited y sleep."""
    failures: list[tuple] = []
    successes: list[tuple] = []
    sleeps: list[float] = []
    spy = SimpleNamespace(
        record_failure=lambda *a: failures.append(a),
        record_success=lambda *a: successes.append(a),
    )
    monkeypatch.setattr(sec_edgar, "get_data_source_registry", lambda: spy)

    async def _wait() -> None:
        return None

    monkeypatch.setattr(sec_pacing.pacer, "wait", _wait)
    monkeypatch.setattr(sec_pacing, "rate_limited", lambda response: None)

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    # SimpleNamespace: no contaminar el modulo asyncio global (casa).
    monkeypatch.setattr(
        sec_edgar, "asyncio", SimpleNamespace(**(vars(asyncio) | {"sleep": _sleep}))
    )
    return SimpleNamespace(failures=failures, successes=successes, sleeps=sleeps)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- resolve_user_agent (66, 68) ---


def test_user_agent_sin_arroba_cae_al_navegador_defecto(monkeypatch):
    """66: un UA configurado sin contacto no se sirve: cabecera navegador."""
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "EquipoSinContacto")
    assert sec_edgar.resolve_user_agent() == BROWSER_USER_AGENT.format(
        contact=DEFAULT_CONTACT
    )


def test_user_agent_prefijo_cavaai_conserva_solo_el_contacto(monkeypatch):
    """68: 'CavaAI/x (contacto)' se reescribe a cabecera navegador con ese contacto."""
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "CavaAI/1.2 (ops@example.com)")
    assert sec_edgar.resolve_user_agent() == BROWSER_USER_AGENT.format(
        contact="ops@example.com"
    )


# --- snapshot local (101) y manifest del snapshot (351) ---


def test_snapshot_path_para_companyfacts(tmp_path, monkeypatch, _settings_frescos):
    """103: URL de companyfacts con snapshot configurado -> ruta local tipada."""
    monkeypatch.setenv("SEC_SNAPSHOT_DIR", str(tmp_path))
    esperada = tmp_path / "companyfacts" / "CIK0000320193.json"
    assert sec_edgar._snapshot_path_for(CIK_URL) == esperada


def test_snapshot_path_para_el_mapa_de_tickers(tmp_path, monkeypatch, _settings_frescos):
    """101: la URL del mapa de tickers -> company_tickers.json en la raiz."""
    monkeypatch.setenv("SEC_SNAPSHOT_DIR", str(tmp_path))
    assert sec_edgar._snapshot_path_for(sec_edgar.TICKER_MAP_URL) == (
        tmp_path / "company_tickers.json"
    )


def test_manifest_cik_sin_fichero_manifest_devuelve_none(
    tmp_path, monkeypatch, _settings_frescos
):
    """351: directorio snapshot configurado pero sin manifest.json -> None."""
    monkeypatch.setenv("SEC_SNAPSHOT_DIR", str(tmp_path))
    assert sec_edgar._manifest_cik("AAPL") is None


# --- registro de servidos del mirror (250->exit) ---


def test_record_mirror_serve_sin_colector_no_falla():
    """250->exit: sin colector activo en el ContextVar, no se anexa nada."""
    token = sec_edgar._MIRROR_SERVES.set(None)
    try:
        assert sec_edgar._record_mirror_serve({"url": "x"}) is None
        assert sec_edgar._MIRROR_SERVES.get() is None
    finally:
        sec_edgar._MIRROR_SERVES.reset(token)


# --- manifest del mirror HF (269) ---


def test_mirror_manifest_no_dict_fail_closed(monkeypatch):
    """269: un manifest que no es objeto JSON aborta (fail closed)."""

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            return SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: [1, 2, 3]
            )

    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})
    monkeypatch.setattr(sec_edgar, "httpx", SimpleNamespace(AsyncClient=_FakeClient))
    with pytest.raises(RuntimeError) as excinfo:
        _run(sec_edgar._mirror_manifest("ds-x"))
    assert str(excinfo.value) == (
        "Mirror HF manifest no es objeto JSON "
        "(https://huggingface.co/datasets/ds-x/resolve/main/manifest.json)"
    )


# --- mirror_get_json (312-313, 335) ---


def _mirror_doblado(monkeypatch, response: httpx.Response):
    manifest = {
        "synced_at": "2026-11-09T00:00:00+00:00",
        "files": {"companyfacts/CIK0000320193.json": None},
    }

    async def _manifest(dataset):
        return manifest

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            return response

    monkeypatch.setattr(sec_edgar, "_mirror_manifest", _manifest)
    # El namespace doblado conserva las excepciones reales de httpx.
    monkeypatch.setattr(
        sec_edgar,
        "httpx",
        SimpleNamespace(AsyncClient=_FakeClient, HTTPStatusError=httpx.HTTPStatusError),
    )
    return manifest


def test_mirror_sin_el_documento_error_claro(monkeypatch, _settings_frescos):
    """312-313: el mirror responde 404 -> RuntimeError con SEC + mirror."""
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", DATASET)
    request = httpx.Request("GET", MIRROR_URL)
    manifest = _mirror_doblado(monkeypatch, httpx.Response(404, request=request))
    # El documento esta declarado (el 404 salta antes de verificar el sha1).
    manifest["files"]["companyfacts/CIK0000320193.json"] = "0" * 40
    bloqueo = RuntimeError("ban de IP")
    with pytest.raises(RuntimeError) as excinfo:
        _run(sec_edgar.mirror_get_json(CIK_URL, direct_error=bloqueo))
    assert str(excinfo.value) == (
        f"SEC bloqueada ({bloqueo}) y mirror HF sin el documento (404 {MIRROR_URL})"
    )


def test_mirror_json_no_objeto_fail_closed(monkeypatch, _settings_frescos):
    """335: el documento del mirror no es un objeto JSON -> fail closed."""
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", DATASET)
    crudo = b"[1, 2]"
    request = httpx.Request("GET", MIRROR_URL)
    manifest = _mirror_doblado(
        monkeypatch, httpx.Response(200, content=crudo, request=request)
    )
    manifest["files"]["companyfacts/CIK0000320193.json"] = hashlib.sha1(
        crudo, usedforsecurity=False
    ).hexdigest()
    with pytest.raises(RuntimeError) as excinfo:
        _run(sec_edgar.mirror_get_json(CIK_URL))
    assert str(excinfo.value) == f"Mirror HF returned non-object JSON ({MIRROR_URL})"


# --- _get_json: errores de red, HTTP, JSON y caida del mirror ---


def test_get_json_error_de_red_registra_y_relanza(red_doblada):
    """178-180: TransportError -> record_failure tipado y relanzar."""
    url = "https://example.com/x.json"
    llamadas = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    async def probe():
        async with _client(handler) as http:
            await sec_edgar._get_json(url, http)

    with pytest.raises(httpx.ConnectError):
        _run(probe())
    assert llamadas["n"] == 1
    assert red_doblada.failures == [("sec_edgar", "error de red: ConnectError")]


def test_get_json_retry_after_invalido_usa_backoff(red_doblada):
    """188-189: Retry-After no numerico -> espera el backoff base y reintenta."""
    url = "https://example.com/x.json"
    respuestas = [
        httpx.Response(429, headers={"retry-after": "abc"}),
        httpx.Response(200, json={"ok": True}),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        respuesta = respuestas.pop(0)
        respuesta.request = request
        return respuesta

    async def probe():
        async with _client(handler) as http:
            return await sec_edgar._get_json(url, http, max_retries=1, base_delay=1.0)

    assert _run(probe()) == {"ok": True}
    assert red_doblada.sleeps == [1.0]
    assert len(red_doblada.successes) == 1
    assert red_doblada.failures == []


def test_get_json_http_500_registra_y_falla(red_doblada):
    """203-206: 500 (no 401/403, no 400/404) -> record_failure + RuntimeError."""
    url = "https://example.com/x.json"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    async def probe():
        async with _client(handler) as http:
            await sec_edgar._get_json(url, http)

    with pytest.raises(RuntimeError) as excinfo:
        _run(probe())
    assert str(excinfo.value) == f"SEC EDGAR request failed (500 {url})"
    assert red_doblada.failures == [("sec_edgar", "HTTP 500")]


def test_get_json_404_es_dato_neutral_sin_degradar(red_doblada):
    """203->206: 404 es dato por emisor (neutral): RuntimeError SIN record_failure."""
    url = "https://example.com/inexistente.json"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    async def probe():
        async with _client(handler) as http:
            await sec_edgar._get_json(url, http)

    with pytest.raises(RuntimeError) as excinfo:
        _run(probe())
    assert str(excinfo.value) == f"SEC EDGAR request failed (404 {url})"
    assert red_doblada.failures == []


def test_get_json_respuesta_no_json(red_doblada):
    """210-212: cuerpo no JSON -> record_failure y relanzar ValueError."""
    url = "https://example.com/x.json"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"no-json", request=request)

    async def probe():
        async with _client(handler) as http:
            await sec_edgar._get_json(url, http)

    with pytest.raises(ValueError):
        _run(probe())
    assert red_doblada.failures == [("sec_edgar", "respuesta no JSON")]


def test_get_json_json_no_objeto(red_doblada):
    """214-215: JSON valido pero no objeto -> RuntimeError fail closed."""
    url = "https://example.com/x.json"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2], request=request)

    async def probe():
        async with _client(handler) as http:
            await sec_edgar._get_json(url, http)

    with pytest.raises(RuntimeError) as excinfo:
        _run(probe())
    assert str(excinfo.value) == f"SEC EDGAR returned non-object JSON ({url})"
    assert red_doblada.failures == [("sec_edgar", "JSON no objeto")]


def test_get_json_403_y_mirror_caido(
    monkeypatch, red_doblada, _settings_frescos
):
    """223-225: 403 con mirror configurado y mirror caido -> fallo tipado."""
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", DATASET)

    async def _mirror_caido(url, *, direct_error=None):
        raise RuntimeError("mirror caido")

    monkeypatch.setattr(sec_edgar, "mirror_get_json", _mirror_caido)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    async def probe():
        async with _client(handler) as http:
            await sec_edgar._get_json(CIK_URL, http)

    with pytest.raises(RuntimeError) as excinfo:
        _run(probe())
    assert str(excinfo.value) == "mirror caido"
    assert red_doblada.failures == [
        ("sec_edgar", "HTTP 401/403 (IP) y mirror fallo: RuntimeError")
    ]


# --- recent_filings (420) ---


def test_recent_filings_corta_al_llegar_al_limite(monkeypatch):
    """420: con mas filings que el limite, el bucle corta y devuelve justo el limite."""
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["a1", "a2", "a3"],
                "form": ["10-K", "10-K", "10-K"],
                "filingDate": ["2026-01-01", "2026-02-01", "2026-03-01"],
                "reportDate": ["2025-12-31", "2026-01-31", "2026-02-28"],
                "primaryDocument": ["d1.htm", "d2.htm", "d3.htm"],
            }
        }
    }

    async def _get(url, client=None, **kwargs):
        return payload

    monkeypatch.setattr(sec_edgar, "_get_json", _get)
    items = _run(sec_edgar.recent_filings("320193", limit=2))
    assert [i["accession_number"] for i in items] == ["a1", "a2"]
