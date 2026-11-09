"""Bordes de connectors/sec.py (lote 2): _get/_fetch_json, EFTS, anchors, stream.

Cero red real: los tests async usan httpx.MockTransport con cliente inyectado,
salvo los dos que ejercen el AsyncClient propio (280-285 y 715-716): ahi se
dobla el namespace sec.httpx con SimpleNamespace conservando las excepciones
reales y sustituyendo solo AsyncClient por una factoria con MockTransport.

Decisiones declaradas:
- pacer.wait doblado (no-op) en todo test que llega a _throttle: sin el, la
  cuota global intentaria una conexion real a Redis.
- _minimum_interval anulado a nivel de INSTANCIA (0.0) para no esperar el
  reloj real del ritmo compartido; los huecos del reloj se prueban en
  test_sec_pacing_bordes.py.
- max_retries=0 en todos: un solo intento sin esperas de backoff; los
  reintentos se prueban en test_sec_pacing_bordes.py.
- Registry espiado con mensajes por igualdad estricta en los tests de fallo
  tipado; en el resto se usa el registry real (como en el lote 1).
- _fetch_json doblado SOLO en el test de cancelacion (unica via determinista
  para cancelar la descarga en vuelo); el resto va por MockTransport.
- settings sustituido a nivel de instancia (SimpleNamespace) solo para el
  flag sec_efts_fallback_enabled; nunca se muta el objeto global.
- Cache: el autouse de conftest ya vacia _json_cache/_json_inflight por test;
  el test de cancelacion usa use_cache=True explicito sobre ese estado vacio.

Sin lineas declaradas inalcanzables en este lote.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.services.connectors import sec as sec_module
from app.services.connectors.sec import SECClient
from app.services.sec_ticker import CikIndex

CIK = "320193"
PADDED = "0000320193"
ACC1 = "0000320193-24-000001"
ACC2 = "0000320193-24-000002"
ACC4 = "0000320193-24-000004"


def _run(coro):
    return asyncio.run(coro)


def _pacer_noop(monkeypatch) -> None:
    from app.services.connectors import sec_pacing

    async def _wait() -> None:
        return None

    monkeypatch.setattr(sec_pacing.pacer, "wait", _wait)


def _cliente(monkeypatch, http=None, **kwargs) -> SECClient:
    cliente = SECClient(client=http, max_retries=0, **kwargs)
    # Ritmo compartido anulado solo en esta instancia: sin esperas de reloj.
    monkeypatch.setattr(cliente, "_minimum_interval", 0.0)
    return cliente


class _RegistryEspia:
    def __init__(self) -> None:
        self.exitos: list[tuple[str, float]] = []
        self.fallos: list[tuple[str, str]] = []

    def record_success(self, key: str, ms: float) -> None:
        self.exitos.append((key, ms))

    def record_failure(self, key: str, mensaje: str) -> None:
        self.fallos.append((key, mensaje))


def _espia_registry(monkeypatch) -> _RegistryEspia:
    espia = _RegistryEspia()
    monkeypatch.setattr(sec_module, "get_data_source_registry", lambda: espia)
    return espia


def _doble_httpx_con_mock(monkeypatch, handler) -> None:
    """sec.httpx con las excepciones reales y AsyncClient -> MockTransport."""
    cliente_real = httpx.AsyncClient

    def factoria(**kwargs):
        return cliente_real(transport=httpx.MockTransport(handler), **kwargs)

    falso = SimpleNamespace(**(vars(httpx) | {"AsyncClient": factoria}))
    monkeypatch.setattr(sec_module, "httpx", falso)


class _Trozos(httpx.AsyncByteStream):
    """Stream async troceado para ejercer el bucle de aiter_bytes."""

    def __init__(self, trozos: list[bytes]) -> None:
        self._trozos = trozos

    async def __aiter__(self):
        for trozo in self._trozos:
            yield trozo

    async def aclose(self) -> None:
        return None


# --- _get con AsyncClient propio (280-285) ---


def test_get_sin_cliente_crea_async_client_propio(monkeypatch):
    """280-285: sin cliente inyectado, _get crea y cierra su AsyncClient."""
    _pacer_noop(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    _doble_httpx_con_mock(monkeypatch, handler)

    async def probe():
        return await _cliente(monkeypatch, use_cache=False)._get_json(
            "https://www.sec.gov/files/company_tickers.json"
        )

    assert _run(probe()) == {"ok": True}


# --- _fetch_json: fallos tipados (384-386, 387-389, 390-392) ---


def test_fetch_json_error_500_registra_fallo(monkeypatch):
    """384-386: HTTPStatusError no-401/403/400/404 -> record_failure 'HTTP 500'."""
    _pacer_noop(monkeypatch)
    espia = _espia_registry(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}, request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            await _cliente(monkeypatch, http, use_cache=False)._get_json(
                "https://www.sec.gov/x.json"
            )

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        _run(probe())
    assert excinfo.value.response.status_code == 500
    assert espia.fallos == [("sec_edgar", "HTTP 500")]
    assert espia.exitos == []


def test_fetch_json_error_de_red_registra_fallo(monkeypatch):
    """387-389: TransportError -> record_failure con el tipo exacto y relanza."""
    _pacer_noop(monkeypatch)
    espia = _espia_registry(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("caida", request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            await _cliente(monkeypatch, http, use_cache=False)._get_json(
                "https://www.sec.gov/x.json"
            )

    with pytest.raises(httpx.ConnectError):
        _run(probe())
    assert espia.fallos == [("sec_edgar", "error de red: ConnectError")]
    assert espia.exitos == []


def test_fetch_json_respuesta_no_json_registra_fallo(monkeypatch):
    """390-392: 200 con cuerpo no JSON -> record_failure 'respuesta no JSON'."""
    _pacer_noop(monkeypatch)
    espia = _espia_registry(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>no json</html>", request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            await _cliente(monkeypatch, http, use_cache=False)._get_json(
                "https://www.sec.gov/x.json"
            )

    with pytest.raises(ValueError):
        _run(probe())
    assert espia.fallos == [("sec_edgar", "respuesta no JSON")]
    assert espia.exitos == []


# --- submissions: fallback EFTS desactivado (437, 440-441) ---


def test_submissions_error_sin_fallback_efts_relanza_el_directo(monkeypatch):
    """437/440-441: 500 con sec_efts_fallback_enabled=False relanza el error
    directo sin tocar EFTS. Settings sustituido a nivel de instancia."""
    _pacer_noop(monkeypatch)
    espia = _espia_registry(monkeypatch)
    peticiones: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        peticiones.append(str(request.url))
        return httpx.Response(500, json={}, request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            cliente = _cliente(monkeypatch, http, use_cache=False)
            monkeypatch.setattr(
                cliente,
                "settings",
                SimpleNamespace(sec_efts_fallback_enabled=False),
            )
            await cliente.submissions(CIK)

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        _run(probe())
    assert excinfo.value.response.status_code == 500
    assert peticiones == [
        f"https://data.sec.gov/submissions/CIK{PADDED}.json"
    ]
    assert espia.fallos == [("sec_edgar", "HTTP 500")]


# --- _ticker_index sin cache (415, 425->427) ---


def test_ticker_index_sin_cache_no_toca_el_indice_global(monkeypatch):
    """425->427: use_cache=False -> el indice NO se guarda en _cik_index."""
    _pacer_noop(monkeypatch)
    payload = {
        "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await _cliente(
                monkeypatch, http, use_cache=False
            )._ticker_index()

    indice = _run(probe())
    assert isinstance(indice, CikIndex)
    assert indice.lookup("AAPL") == PADDED
    assert indice.lookup("MSFFT") is None
    assert sec_module._cik_index is None


# --- efts_submissions (456-486) ---


def _hit(
    adsh: str | None,
    *,
    seq: int = 1,
    doc: str = "x:d1.htm",
    form: str = "10-K",
    fecha: str = "2026-01-01",
    periodo: str = "2025-12-31",
    con_nombre: bool = False,
) -> dict:
    source: dict = {
        "form": form,
        "file_date": fecha,
        "period_ending": periodo,
        "sequence": seq,
    }
    if adsh is not None:
        source["adsh"] = adsh
    if con_nombre:
        source["ciks"] = [PADDED]
        source["display_names"] = ["Apple Inc."]
    return {"_id": doc, "_source": source}


def test_efts_submissions_continues_break_y_payload(monkeypatch):
    """459-484: hit sin adsh (466-467), sequence no mejor (472-473), nombre
    por posicion (474-475), documento sin ':' (469), corte con pagina corta
    (483-484) y payload final por igualdad estricta."""
    _pacer_noop(monkeypatch)
    peticiones: list[str] = []
    hits = [
        _hit(None),  # sin adsh -> continue
        _hit(ACC1, seq=5, doc="a:d5.htm", con_nombre=True),
        _hit(ACC1, seq=7, doc="a:d7.htm"),  # 5 <= 7 -> continue
        _hit(
            ACC1,
            seq=3,
            doc="a:d3.htm",
            form="10-K/A",
            fecha="2026-02-01",
            periodo="2026-01-31",
        ),  # 5 <= 3 es falso -> se queda la secuencia 3
        _hit(ACC2, doc="sinpuntos"),  # doc_id sin ':' -> document ""
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        peticiones.append(str(request.url))
        return httpx.Response(200, json={"hits": {"hits": hits}}, request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await _cliente(
                monkeypatch, http, use_cache=False
            ).efts_submissions(CIK)

    resultado = _run(probe())
    assert resultado == {
        "cik": PADDED,
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [ACC1, ACC2],
                "form": ["10-K/A", "10-K"],
                "filingDate": ["2026-02-01", "2026-01-01"],
                "reportDate": ["2026-01-31", "2025-12-31"],
                "primaryDocument": ["d3.htm", ""],
                "isInlineXBRL": [None, None],
            },
            "files": [],
        },
        "_fallback": "efts-full-text-search",
        "_fallback_note": sec_module.EFTS_PARTIAL_NOTE,
    }
    # Pagina corta (< 100 hits) -> break: una sola peticion.
    assert peticiones == [
        f"https://efts.sec.gov/LATEST/search-index?ciks={PADDED}&size=100&from=0"
    ]


def test_efts_submissions_pagina_hasta_agotar_max_pages(monkeypatch):
    """483->459 (pagina llena sigue) y 459->485 (bucle agotado sin break):
    dos paginas de 100 hits -> dos peticiones y 200 filings."""
    _pacer_noop(monkeypatch)
    peticiones: list[str] = []

    def pagina(desde: int) -> dict:
        return {
            "hits": {
                "hits": [
                    _hit(f"0000320193-24-{desde + i:06d}") for i in range(100)
                ]
            }
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        peticiones.append(str(request.url))
        desde = int(request.url.params["from"])
        return httpx.Response(200, json=pagina(desde), request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await _cliente(
                monkeypatch, http, use_cache=False
            ).efts_submissions(CIK, max_pages=2)

    resultado = _run(probe())
    assert peticiones == [
        f"https://efts.sec.gov/LATEST/search-index?ciks={PADDED}&size=100&from=0",
        f"https://efts.sec.gov/LATEST/search-index?ciks={PADDED}&size=100&from=100",
    ]
    assert len(resultado["filings"]["recent"]["accessionNumber"]) == 200


def test_efts_submissions_sin_filings_lanza_runtime_error(monkeypatch):
    """485-486: EFTS sin ningun filing -> RuntimeError con mensaje exacto."""
    _pacer_noop(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hits": {"hits": []}}, request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await _cliente(
                monkeypatch, http, use_cache=False
            ).efts_submissions(CIK)

    with pytest.raises(RuntimeError) as excinfo:
        _run(probe())
    assert str(excinfo.value) == f"EFTS sin filings para CIK{PADDED}"


# --- annual_report_anchors (516-545) ---


def _payload_submissions(files: list[dict]) -> dict:
    return {
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "form": ["10-K", "8-K", "10-K", "10-K"],
                "accessionNumber": [ACC1, ACC2, "0000320193-24-000003", ""],
                "reportDate": ["2025-12-31", "2025-06-30", "", "2024-12-31"],
            },
            "files": files,
        },
    }


def test_anchors_salta_sin_report_date_y_ficheros_rotos(monkeypatch):
    """530-531 (no anual), 533->528 (sin reportDate), 539-540 (file sin
    nombre), 543-544 (file caido -> cobertura parcial, nunca rompe)."""
    _pacer_noop(monkeypatch)
    files = [
        {"name": "extra_ok.json"},
        {},  # sin nombre -> continue
        {"name": "extra_roto.json"},  # 404 -> continue
    ]
    # Los ficheros historicos tienen el formato de `recent` en raiz.
    extra_ok = {
        "form": ["10-K"],
        "accessionNumber": [ACC4],
        "reportDate": ["2026-01-31"],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("extra_ok.json"):
            return httpx.Response(200, json=extra_ok, request=request)
        if url.endswith("extra_roto.json"):
            return httpx.Response(404, json={}, request=request)
        return httpx.Response(200, json=_payload_submissions(files), request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await _cliente(
                monkeypatch, http, use_cache=False
            ).annual_report_anchors(CIK)

    anchors = _run(probe())
    assert anchors == {ACC1: "2025-12-31", ACC4: "2026-01-31"}
    assert anchors.partial is False
    assert anchors.source == "sec-submissions"


# --- index_accessions (556-574) ---


def test_index_accessions_fusiona_recent_y_ficheros(monkeypatch):
    """556-573: accession vacia saltada (562-563), file sin nombre (568-569)
    y file caido (571-573) con cobertura parcial."""
    _pacer_noop(monkeypatch)
    files = [{"name": "extra_ok.json"}, {}, {"name": "extra_roto.json"}]
    payload = _payload_submissions(files)
    # Los ficheros historicos tienen el formato de `recent` en raiz.
    extra_ok = {"accessionNumber": [ACC4]}

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("extra_ok.json"):
            return httpx.Response(200, json=extra_ok, request=request)
        if url.endswith("extra_roto.json"):
            return httpx.Response(404, json={}, request=request)
        return httpx.Response(200, json=payload, request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await _cliente(
                monkeypatch, http, use_cache=False
            ).index_accessions(CIK)

    assert _run(probe()) == {ACC1, ACC2, "0000320193-24-000003", ACC4}


# --- descarga en vuelo cancelada (338-352, 346->exit) ---


def test_get_json_descarga_en_vuelo_cancelada_se_recoge(monkeypatch):
    """338-352 y 346->exit: tarea de descarga cancelada -> se desregistra del
    inflight y _done NO recupera excepcion. _fetch_json doblado (unica via
    determinista de cancelacion); no llega a red ni pacer."""

    async def _fetch_bloqueado(self, url):
        await asyncio.Future()  # pendiente hasta que la cancelen

    monkeypatch.setattr(SECClient, "_fetch_json", _fetch_bloqueado)

    async def probe():
        cliente = _cliente(monkeypatch, use_cache=True)
        tarea = asyncio.ensure_future(
            cliente._get_json("https://www.sec.gov/x.json")
        )
        await asyncio.sleep(0)  # deja registrar la tarea en _json_inflight
        internas = list(sec_module._json_inflight.values())
        assert len(internas) == 1
        internas[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea
        await asyncio.sleep(0)  # deja correr el callback _done
        assert sec_module._json_inflight == {}

    _run(probe())


# --- filing_document_head: stream (696-716) ---


def test_filing_document_head_rechaza_host_ajeno_a_sec():
    """696-698: solo se leen documentos de sec.gov."""
    cliente = SECClient()
    with pytest.raises(ValueError) as excinfo:
        _run(cliente.filing_document_head("https://evil.example.com/x.htm"))
    assert str(excinfo.value) == "SEC filing URL must use sec.gov"


def test_filing_document_head_corta_en_max_bytes_con_cliente(monkeypatch):
    """701-714: stream troceado; 709->706 (sigue) y 709->711 (corta) con el
    resultado truncado a max_bytes."""
    _pacer_noop(monkeypatch)
    trozos = [b"0123456789", b"abcdefghij", b"KLMNOPQRST"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Trozos(trozos), request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await _cliente(
                monkeypatch, http
            ).filing_document_head(
                "https://www.sec.gov/Archives/edgar/data/320193/x.htm",
                max_bytes=15,
            )

    assert _run(probe()) == b"0123456789abcde"


def test_filing_document_head_sin_cliente_crea_async_client(monkeypatch):
    """715-716: sin cliente inyectado crea su AsyncClient (timeout 15)."""
    _pacer_noop(monkeypatch)
    contenido = b"<html>cabecera 10-K</html>"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=contenido, request=request)

    _doble_httpx_con_mock(monkeypatch, handler)

    async def probe():
        return await _cliente(monkeypatch).filing_document_head(
            "https://www.sec.gov/Archives/edgar/data/320193/x.htm"
        )

    assert _run(probe()) == contenido
