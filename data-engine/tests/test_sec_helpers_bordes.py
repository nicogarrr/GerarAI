"""Bordes de connectors/sec.py: helpers de nombres, cache JSON y errores tipados.

Cero red real: los tres tests async (recent_filings limit0, corte a limite y
filing_document) usan httpx.MockTransport con cliente inyectado y
pacer.wait doblado (sin el, la cuota global intentaria una conexion real a
Redis). Cache: el autouse _reset_sec_client_state de conftest ya vacia
_json_cache antes de cada test; los tests de cache usan ademas un dict
fresco via monkeypatch como aislamiento, asi que este modulo NO preserva
el contenido previo de la cache real (ya lo borra el reset compartido).
Mensajes por igualdad estricta.

Sin lineas declaradas inalcanzables en este lote.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.services.connectors import sec as sec_module
from app.services.connectors.sec import SECClient


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def cache_fresca(monkeypatch):
    """Dict fresco por test: aislamiento puro; la cache real ya la vacia el
    reset autouse de conftest antes de cada test, asi que no se preserva
    nada del contenido previo."""
    fresco: dict = {}
    monkeypatch.setattr(sec_module, "_json_cache", fresco)
    return fresco


# --- _efts_company_name (94) ---


def test_efts_company_name_sin_nombre_para_el_indice():
    """94: el CIK esta pero no hay nombre en esa posicion -> None."""
    source = {"ciks": ["0000000001"], "display_names": []}
    assert sec_module._efts_company_name(source, "0000000001") is None


# --- _cache_get (167-168) y _cache_entry (180) ---


def test_cache_get_entrada_caducada_se_expulsa(cache_fresca):
    """167-168: hit con deadline pasada -> pop + None (no se sirve dato viejo)."""
    cache_fresca["https://x"] = (0.0, {"a": 1})
    assert sec_module._cache_get("https://x") is None
    assert cache_fresca == {}


def test_cache_entry_empaquetada_no_se_expone(cache_fresca):
    """180: _cache_entry no devuelve entradas _Packed (van por _unpack).

    Usa la clase _Packed de produccion con un blob arbitrario: valida que
    _cache_entry no la expone, NO la descompresion de _unpack.
    """
    cache_fresca["https://x"] = (time.monotonic() + 100, sec_module._Packed(b"blob"))
    assert sec_module._cache_entry("https://x") is None


# --- _cache_put (190, 201) ---


def test_cache_put_ttl_no_positivo_no_guarda(cache_fresca):
    """190: ttl <= 0 -> no se escribe nada."""
    assert sec_module._cache_put("https://x", {"a": 1}, ttl=0) is None
    assert cache_fresca == {}


def test_cache_put_entrada_mayor_que_el_presupuesto_no_se_cachea(
    cache_fresca, monkeypatch
):
    """201: una entrada cuyo blob supera el presupuesto no se retiene."""
    monkeypatch.setattr(sec_module, "_CACHE_MAX_PACKED_BYTES", 1)
    payload = {"datos": "x" * (300 * 1024)}  # >= _PACK_MIN_JSON_BYTES: va packed
    assert sec_module._cache_put("https://x", payload, ttl=60) is None
    assert cache_fresca == {}


def test_cache_put_con_cache_llena_expulsa_la_mas_antigua(cache_fresca):
    """201: al llegar a _CACHE_MAX_ENTRIES se expulsa la entrada mas antigua.

    Identidad de la expulsada: el dict preserva orden de insercion y
    _cache_put expulsa next(iter(_json_cache)), es decir old/0.
    """
    futuro = time.monotonic() + 100
    for i in range(sec_module._CACHE_MAX_ENTRIES):
        cache_fresca[f"https://old/{i}"] = (futuro, {"i": i})
    assert sec_module._cache_put("https://nueva", {"a": 1}, ttl=60) is None
    assert "https://old/0" not in cache_fresca
    assert "https://old/1" in cache_fresca
    assert "https://nueva" in cache_fresca
    assert len(cache_fresca) == sec_module._CACHE_MAX_ENTRIES


# --- filing_index_url / filing_document_url (591, 597) ---


def test_filing_index_url_rechaza_accession_no_numerico():
    """591: accession con letras -> ValueError con mensaje exacto."""
    with pytest.raises(ValueError) as excinfo:
        SECClient.filing_index_url("320193", "0001-ABC")
    assert (
        str(excinfo.value)
        == "SEC accession number must contain only digits and hyphens"
    )


def test_filing_document_url_requiere_nombre_de_fichero():
    """597: primary_document sin nombre usable -> ValueError con mensaje exacto."""
    with pytest.raises(ValueError) as excinfo:
        SECClient.filing_document_url("320193", "0000320193-24-000001", "")
    assert str(excinfo.value) == "SEC primary document filename is required"


# --- filing_document (682) ---


def test_filing_document_rechaza_host_ajeno_a_sec():
    """682: solo se descargan documentos de sec.gov."""
    cliente = SECClient()
    with pytest.raises(ValueError) as excinfo:
        _run(cliente.filing_document("https://evil.example.com/x.htm"))
    assert str(excinfo.value) == "SEC filing URL must use sec.gov"


# --- recent_filings (625) ---


def test_recent_filings_limite_no_positivo_devuelve_vacio(monkeypatch):
    """625: limit <= 0 -> ConnectorResult vacio sin iterar filings.

    Pacer doblado (import vivo en sec/sec_pacing): sin el, la cuota global
    intentaria una conexion real a Redis aunque no haya red SEC.
    """
    from app.services.connectors import sec_pacing

    async def _wait() -> None:
        return None

    monkeypatch.setattr(sec_pacing.pacer, "wait", _wait)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"name": "Apple Inc.", "filings": {"recent": {}}},
            request=request,
        )

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await SECClient(client=http).recent_filings("320193", limit=0)

    resultado = _run(probe())
    assert resultado.items == []
    # limit <= 0 vuelve antes de metadata["company_name"]: el corte es temprano.
    assert resultado.metadata["cik"] == "0000320193"


def test_recent_filings_corta_al_llegar_al_limite(monkeypatch):
    """673: con mas filings que el limite, el bucle corta en el limite exacto."""
    from app.services.connectors import sec_pacing

    async def _wait() -> None:
        return None

    monkeypatch.setattr(sec_pacing.pacer, "wait", _wait)
    payload = {
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000001", "0000320193-24-000002"],
                "form": ["10-K", "10-K"],
                "filingDate": ["2026-01-01", "2026-02-01"],
                "reportDate": ["2025-12-31", "2026-01-31"],
                "primaryDocument": ["d1.htm", "d2.htm"],
            }
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await SECClient(client=http).recent_filings("320193", limit=1)

    resultado = _run(probe())
    assert len(resultado.items) == 1
    # Identidad del filing retenido: el primero de la respuesta (no el segundo).
    assert resultado.items[0].external_id == "0000320193-24-000001"
    assert resultado.metadata["company_name"] == "Apple Inc."


def test_filing_document_descarga_contenido_y_tipo(monkeypatch):
    """685-686: URL valida de sec.gov -> (contenido, content-type) de _get."""
    from app.services.connectors import sec_pacing

    async def _wait() -> None:
        return None

    monkeypatch.setattr(sec_pacing.pacer, "wait", _wait)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"<html>10-K</html>",
            headers={"content-type": "text/html"}, request=request,
        )

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            return await SECClient(client=http).filing_document(
                "https://www.sec.gov/Archives/edgar/data/320193/x.htm"
            )

    contenido, tipo = _run(probe())
    assert contenido == b"<html>10-K</html>"
    assert tipo == "text/html"


# --- _filing_datetime (726, 729-730) ---


def test_filing_datetime_vacio_o_invalido_devuelve_none():
    """726 y 729-730: sin valor o fecha no parseable -> None."""
    assert SECClient._filing_datetime(None) is None
    assert SECClient._filing_datetime("") is None
    assert SECClient._filing_datetime("31-12-2025") is None
